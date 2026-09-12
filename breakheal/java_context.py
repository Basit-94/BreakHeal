"""Java source code extractor capturing package, imports, class, and method context."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from breakheal.java_runner import find_maven_root


@dataclass
class JavaContext:
    file_path: str
    package_name: str
    class_name: str
    method_name: str
    method_code: str
    imports: list[str]
    full_source: str
    start_line: int
    end_line: int
    maven_root: str
    target_name: str = ""  # alias for compatibility
    constructor_code: str | None = None
    fields_code: str | None = None
    is_static: bool = False
    api_contract: str = ""
    threat_score: int = 0
    threat_reasons: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.target_name:
            self.target_name = self.method_name


def _extract_package(source: str) -> str:
    match = re.search(r"^\s*package\s+([\w\.]+)\s*;", source, re.MULTILINE)
    return match.group(1) if match else ""


def _extract_imports(source: str) -> list[str]:
    matches = re.findall(r"^\s*import\s+([\w\.\*]+)\s*;", source, re.MULTILINE)
    return [f"import {m};" for m in matches]


def _extract_class_name(source: str) -> str:
    match = re.search(r"(?:public\s+|protected\s+|private\s+)?(?:final\s+|abstract\s+)?class\s+(\w+)", source)
    return match.group(1) if match else "UnknownClass"


def _extract_constructor(source: str, class_name: str) -> str | None:
    lines = source.splitlines()
    pattern = re.compile(rf"^\s*(?:(?:public|protected|private)\s+)?{re.escape(class_name)}\s*\([^)]*\)\s*(?:throws\s+[\w\s,]+)?\s*\{{")
    for i, line in enumerate(lines):
        if pattern.search(line):
            start = i
            open_braces = 0
            found_open = False
            for j in range(i, len(lines)):
                for char in lines[j]:
                    if char == "{":
                        open_braces += 1
                        found_open = True
                    elif char == "}":
                        open_braces -= 1
                if found_open and open_braces == 0:
                    return "\n".join(lines[start : j + 1])
    return None


def _extract_fields(source: str) -> str | None:
    """Extract class-level member variable declarations."""
    lines = source.splitlines()
    fields: list[str] = []
    field_pattern = re.compile(r"^\s*(?:private|protected|public)\s+(?:static\s+)?(?:final\s+)?[\w\<\>\[\],\s]+\s+\w+\s*(?:=[^;]+)?\s*;")
    for line in lines:
        if field_pattern.match(line):
            fields.append(line.strip())
    return "\n".join(fields) if fields else None


def _extract_all_type_names(source: str) -> set[str]:
    """Extract all class, enum, interface, and record names from Java source."""
    return set(re.findall(r"\b(?:class|enum|interface|record)\s+(\w+)", source))


def _extract_methods_with_spans(source: str, default_class: str = "UnknownClass") -> list[tuple[str, int, int, str, str]]:
    """Extract (method_name, start_line, end_line, method_code, enclosing_class) using bracket counting."""
    lines = source.splitlines()
    type_names = _extract_all_type_names(source)

    class_header_pattern = re.compile(
        r"^\s*(?:(?:public|protected|private|static|final|abstract)\s+)*"
        r"(?:class|interface|enum|record)\s+(\w+)"
    )

    method_pattern = re.compile(
        r"^\s*(?:(?:public|protected|private|static|final|synchronized|abstract|default)\s+)*"
        r"(?:[\w\<\>\[\],\s]+)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w\s,]+)?\s*\{"
    )

    methods: list[tuple[str, int, int, str, str]] = []
    class_stack: list[tuple[str, int]] = []
    current_brace_depth = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        # Track class entries
        class_match = class_header_pattern.search(line)
        if class_match and "{" in line:
            c_name = class_match.group(1)
            class_stack.append((c_name, current_brace_depth + 1))

        # Check for method definition
        match = method_pattern.search(line)
        if match and not (" class " in line or " interface " in line or " enum " in line):
            method_name = match.group(1)
            # Skip constructor if method_name equals any class/enum/record name or control keyword
            if method_name not in type_names and method_name not in {"if", "for", "while", "switch", "catch"}:
                start_line = i + 1
                open_braces = 0
                found_open = False
                end_line = start_line

                for j in range(i, len(lines)):
                    for char in lines[j]:
                        if char == "{":
                            open_braces += 1
                            found_open = True
                        elif char == "}":
                            open_braces -= 1

                    if found_open and open_braces == 0:
                        end_line = j + 1
                        break

                enclosing_class = class_stack[-1][0] if class_stack else default_class
                method_code = "\n".join(lines[start_line - 1 : end_line])
                methods.append((method_name, start_line, end_line, method_code, enclosing_class))
                # Advance line brace depth
                for char in method_code:
                    if char == "{":
                        current_brace_depth += 1
                    elif char == "}":
                        current_brace_depth -= 1
                # Pop closed classes
                while class_stack and current_brace_depth < class_stack[-1][1]:
                    class_stack.pop()

                i = end_line
                continue

        # Count braces for class tracking
        for char in line:
            if char == "{":
                current_brace_depth += 1
            elif char == "}":
                current_brace_depth -= 1
                while class_stack and current_brace_depth < class_stack[-1][1]:
                    class_stack.pop()

        i += 1

    return methods


def extract_java_context(
    file_path: str | Path,
    target_name: str | None = None,
    line_number: int | None = None,
) -> JavaContext:
    """Extract Java metadata, enclosing class, constructor, fields, and target method."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Java file not found: {file_path}")

    source = path.read_text(encoding="utf-8")
    maven_root = find_maven_root(path)

    # Try Tree-sitter AST extraction first
    try:
        from breakheal.java_ast import parse_java_ast, generate_java_api_contract
        ast_parsed = parse_java_ast(source)
    except Exception:
        ast_parsed = None

    if ast_parsed and ast_parsed.classes:
        package_name = ast_parsed.package_name
        imports = ast_parsed.imports
        primary_class = ast_parsed.classes[0]
        class_name = primary_class.name

        chosen_method = None
        if target_name:
            for m in ast_parsed.all_methods:
                if m.name == target_name or f"{m.enclosing_class}.{m.name}" == target_name:
                    chosen_method = m
                    break
        elif line_number is not None:
            for m in ast_parsed.all_methods:
                if m.start_line <= line_number <= m.end_line:
                    chosen_method = m
                    break

        if not chosen_method and ast_parsed.all_methods:
            # Filter out non-business / boilerplate methods
            candidate_methods = [
                m for m in ast_parsed.all_methods
                if m.name not in {"toString", "hashCode", "equals", "main"}
                and not m.name.startswith(("get", "set", "is"))
            ] or ast_parsed.all_methods

            # Threat Surface Ranking:
            # 1. Primary class priority
            # 2. Threat score descending (zero-division, overflow, array access)
            # 3. Public visibility
            candidate_methods.sort(
                key=lambda m: (
                    1 if m.enclosing_class == class_name else 0,
                    m.threat_score,
                    1 if m.visibility == "public" else 0,
                ),
                reverse=True,
            )
            chosen_method = candidate_methods[0]

        if chosen_method:
            m_name = chosen_method.name
            target_class = chosen_method.enclosing_class if chosen_method.enclosing_class == class_name else f"{class_name}.{chosen_method.enclosing_class}"
            m_code = chosen_method.source_code
            start_l = chosen_method.start_line
            end_l = chosen_method.end_line
            is_static = chosen_method.is_static
            threat_score = chosen_method.threat_score
            threat_reasons = chosen_method.threat_reasons
        else:
            m_name = class_name
            target_class = class_name
            m_code = source
            start_l = 1
            end_l = len(source.splitlines())
            is_static = False
            threat_score = 0
            threat_reasons = []

        cons_code = primary_class.constructors[0].source_code if primary_class.constructors else None
        fields_lines = [
            f"{' '.join(filter(None, [f.visibility, 'static' if f.is_static else '']))} {f.type_name} {f.name};"
            for f in primary_class.fields
        ]
        fields_code = "\n".join(fields_lines) if fields_lines else None
        api_contract = generate_java_api_contract(ast_parsed, class_name)

        return JavaContext(
            file_path=str(path),
            package_name=package_name,
            class_name=target_class,
            method_name=m_name,
            method_code=m_code,
            imports=imports,
            full_source=source,
            start_line=start_l,
            end_line=end_l,
            maven_root=str(maven_root) if maven_root else str(path.parent),
            constructor_code=cons_code,
            fields_code=fields_code,
            is_static=is_static,
            api_contract=api_contract,
            threat_score=threat_score,
            threat_reasons=threat_reasons,
        )

    # Fallback to regex-based extraction if AST is unavailable
    package_name = _extract_package(source)
    imports = _extract_imports(source)
    class_name = _extract_class_name(source)
    constructor_code = _extract_constructor(source, class_name)
    fields_code = _extract_fields(source)
    methods = _extract_methods_with_spans(source, default_class=class_name)

    selected_method: tuple[str, int, int, str, str] | None = None

    if target_name:
        for m in methods:
            if m[0] == target_name or f"{m[4]}.{m[0]}" == target_name:
                selected_method = m
                break
    elif line_number is not None:
        for m in methods:
            if m[1] <= line_number <= m[2]:
                selected_method = m
                break

    if not selected_method and methods:
        outer_business_methods = [
            m for m in methods
            if m[4] == class_name
            and not m[0].startswith("get")
            and not m[0].startswith("set")
            and not m[0].startswith("is")
            and m[0] not in {"toString", "hashCode", "equals", "main"}
        ]
        any_business_methods = [
            m for m in methods
            if not m[0].startswith("get")
            and not m[0].startswith("set")
            and not m[0].startswith("is")
            and m[0] not in {"toString", "hashCode", "equals", "main"}
        ]
        selected_method = (
            outer_business_methods[0]
            if outer_business_methods
            else (any_business_methods[0] if any_business_methods else methods[0])
        )

    if selected_method:
        m_name, start_l, end_l, m_code, m_class = selected_method
        target_class = m_class if m_class == class_name else f"{class_name}.{m_class}"
        first_line = m_code.splitlines()[0] if m_code else ""
        is_static = bool(re.search(r"\bstatic\b", first_line))
    else:
        m_name = class_name
        target_class = class_name
        start_l = 1
        end_l = len(source.splitlines())
        m_code = source
        is_static = False

    return JavaContext(
        file_path=str(path),
        package_name=package_name,
        class_name=target_class,
        method_name=m_name,
        method_code=m_code,
        imports=imports,
        full_source=source,
        start_line=start_l,
        end_line=end_l,
        maven_root=str(maven_root) if maven_root else str(path.parent),
        constructor_code=constructor_code,
        fields_code=fields_code,
        is_static=is_static,
    )



def scan_directory_for_java_methods(
    directory: str | Path,
    exclude_dirs: list[str] | None = None,
) -> list[JavaContext]:
    """Recursively find all Java methods across all .java files in a directory."""
    dir_path = Path(directory).resolve()
    if not dir_path.is_dir():
        return []

    excludes = set(exclude_dirs or [".git", "target", "build", ".gradle", "bin", ".idea", "test"])
    contexts: list[JavaContext] = []

    for file_path in sorted(dir_path.rglob("*.java")):
        if any(part in excludes for part in file_path.parts):
            continue
        # Skip test files
        if file_path.name.endswith("Test.java") or file_path.name.startswith("Test"):
            continue

        try:
            source = file_path.read_text(encoding="utf-8")
            methods = _extract_methods_with_spans(source)
            for item in methods:
                m_name = item[0]
                ctx = extract_java_context(file_path, target_name=m_name)
                contexts.append(ctx)
        except Exception:
            continue

    return contexts
