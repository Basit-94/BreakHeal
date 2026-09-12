"""AST parsing to extract module-level imports and target enclosing functions/classes."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeContext:
    file_path: str
    module_name: str
    target_name: str
    target_code: str
    imports: list[str]
    full_source: str
    start_line: int
    end_line: int
    is_class: bool = False
    class_name: str | None = None
    is_method: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    constructor_code: str | None = None
    class_context: str | None = None


class _ImportExtractor(ast.NodeVisitor):
    def __init__(self, source_lines: list[str]):
        self.source_lines = source_lines
        self.imports: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        segment = self._get_segment(node)
        if segment:
            self.imports.append(segment)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        segment = self._get_segment(node)
        if segment:
            self.imports.append(segment)
        self.generic_visit(node)

    def _get_segment(self, node: ast.AST) -> str:
        if hasattr(node, "lineno") and hasattr(node, "end_lineno") and node.end_lineno:
            lines = self.source_lines[node.lineno - 1 : node.end_lineno]
            return "\n".join(lines).strip()
        return ""


def extract_imports(source: str) -> list[str]:
    """Extract all import statements from Python source code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    extractor = _ImportExtractor(source.splitlines())
    extractor.visit(tree)
    return extractor.imports


def _annotate_parents(tree: ast.AST) -> None:
    """Attach parent pointers to AST nodes to resolve enclosing classes."""
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent  # type: ignore[attr-defined]


def _find_enclosing_node_by_line(tree: ast.AST, line_number: int) -> tuple[ast.AST | None, ast.ClassDef | None]:
    best_match = None
    min_span = float("inf")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lineno = getattr(node, "lineno", None)
            end_lineno = getattr(node, "end_lineno", None)
            if lineno is not None and end_lineno is not None:
                if lineno <= line_number <= end_lineno:
                    span = end_lineno - lineno
                    if span < min_span:
                        min_span = span
                        best_match = node

    enclosing_class = None
    if best_match and not isinstance(best_match, ast.ClassDef):
        curr = getattr(best_match, "_parent", None)
        while curr is not None:
            if isinstance(curr, ast.ClassDef):
                enclosing_class = curr
                break
            curr = getattr(curr, "_parent", None)

    return best_match, enclosing_class


def _find_node_by_name(tree: ast.AST, target_name: str) -> tuple[ast.AST | None, ast.ClassDef | None]:
    # Support Class.method syntax
    if "." in target_name:
        class_part, method_part = target_name.split(".", 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_part:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_part:
                        return item, node

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if getattr(node, "name", None) == target_name:
                enclosing_class = None
                if not isinstance(node, ast.ClassDef):
                    curr = getattr(node, "_parent", None)
                    while curr is not None:
                        if isinstance(curr, ast.ClassDef):
                            enclosing_class = curr
                            break
                        curr = getattr(curr, "_parent", None)
                return node, enclosing_class
    return None, None


def extract_context(
    file_path: str | Path,
    target_name: str | None = None,
    line_number: int | None = None,
) -> CodeContext:
    """Extract AST context including module imports, class outline, constructor, and target snippet."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    _annotate_parents(tree)
    source_lines = source.splitlines()

    target_node: ast.AST | None = None
    enclosing_class: ast.ClassDef | None = None

    if target_name:
        target_node, enclosing_class = _find_node_by_name(tree, target_name)
    elif line_number is not None:
        target_node, enclosing_class = _find_enclosing_node_by_line(tree, line_number)

    # If still not found, pick the first function or class in the file
    if target_node is None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                target_node = node
                break

    # If there are no functions/classes, target the entire module
    if target_node is None:
        name = path.stem
        start_line = 1
        end_line = len(source_lines)
        target_code = source
        is_class = False
        is_method = False
        class_name = None
        is_static = False
        is_classmethod = False
        constructor_code = None
        class_context = None
    else:
        name = getattr(target_node, "name", path.stem)
        start_line = target_node.lineno  # type: ignore[attr-defined]
        end_line = target_node.end_lineno or start_line  # type: ignore[attr-defined]
        target_code = "\n".join(source_lines[start_line - 1 : end_line])
        is_class = isinstance(target_node, ast.ClassDef)

        if enclosing_class is not None:
            is_method = True
            class_name = enclosing_class.name
            # Check decorator list
            decorators = getattr(target_node, "decorator_list", [])
            is_static = any(getattr(d, "id", "") == "staticmethod" for d in decorators)
            is_classmethod = any(getattr(d, "id", "") == "classmethod" for d in decorators)

            # Find constructor __init__
            constructor_code = None
            for item in enclosing_class.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    c_start = item.lineno
                    c_end = item.end_lineno or c_start
                    constructor_code = "\n".join(source_lines[c_start - 1 : c_end])
                    break

            # Build class outline
            methods = [
                m.name for m in enclosing_class.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            class_context = f"Class {class_name} with methods: {', '.join(methods)}"
        else:
            is_method = False
            class_name = None
            is_static = False
            is_classmethod = False
            constructor_code = None
            class_context = None

    imports = extract_imports(source)
    module_name = path.stem

    return CodeContext(
        file_path=str(path),
        module_name=module_name,
        target_name=name,
        target_code=target_code,
        imports=imports,
        full_source=source,
        start_line=start_line,
        end_line=end_line,
        is_class=is_class,
        class_name=class_name,
        is_method=is_method,
        is_static=is_static,
        is_classmethod=is_classmethod,
        constructor_code=constructor_code,
        class_context=class_context,
    )


def detect_targets_from_diff(
    file_path: str | Path,
    changed_lines: list[int] | None = None,
) -> list[CodeContext]:
    """Find all functions/classes overlapping with changed lines in a file."""
    path = Path(file_path).resolve()
    if not path.is_file():
        return []

    if not changed_lines:
        return [extract_context(path)]

    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [extract_context(path)]

    matched_nodes: dict[str, ast.AST] = {}
    for line in changed_lines:
        node, enclosing_class = _find_enclosing_node_by_line(tree, line)
        if node and hasattr(node, "name"):
            if enclosing_class:
                target_key = f"{enclosing_class.name}.{node.name}"
            else:
                target_key = node.name
            matched_nodes[target_key] = node

    if not matched_nodes:
        return [extract_context(path)]

    contexts = []
    for name, _ in matched_nodes.items():
        contexts.append(extract_context(path, target_name=name))
    return contexts


def scan_directory_for_functions(
    directory: str | Path,
    exclude_dirs: list[str] | None = None,
) -> list[CodeContext]:
    """Recursively discover and extract all functions and class methods across all Python files in a directory."""
    dir_path = Path(directory).resolve()
    if not dir_path.is_dir():
        return []

    excludes = set(exclude_dirs or [".git", "__pycache__", ".pytest_cache", "venv", ".venv", "build", "dist", "tests"])
    contexts: list[CodeContext] = []

    for file_path in sorted(dir_path.rglob("*.py")):
        # Skip excluded dirs and test files
        if any(part in excludes for part in file_path.parts):
            continue
        if file_path.name.startswith("test_") or file_path.name.endswith("_test.py"):
            continue

        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
        except Exception:
            continue

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    ctx = extract_context(file_path, target_name=node.name)
                    contexts.append(ctx)
                except Exception:
                    continue
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not item.name.startswith("__"):
                            try:
                                ctx = extract_context(file_path, target_name=f"{node.name}.{item.name}")
                                contexts.append(ctx)
                            except Exception:
                                continue

    return contexts

