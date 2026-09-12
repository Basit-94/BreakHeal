"""TypeScript and JavaScript context extractor for BreakHeal.

Parses functions, exported arrow functions, and class methods with line-accurate
bracket matching and import extraction without external language server dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class TSContext:
    target_name: str
    file_path: str
    source_code: str
    start_line: int
    end_line: int
    imports: List[str]
    is_exported: bool
    is_async: bool
    class_name: Optional[str] = None
    is_static: bool = False
    full_source: str = ""
    constructor_code: Optional[str] = None
    types_and_interfaces: Optional[List[str]] = None
    api_contract: str = ""
    threat_score: int = 0
    threat_reasons: List[str] = field(default_factory=list)


# Match standard functions: function foo(...)
STANDALONE_FUNC_PATTERN = re.compile(
    r"^\s*(?P<export>export\s+)?(?P<default>default\s+)?(?P<async>async\s+)?function\s+(?P<name>[a-zA-Z0-9_$]+)\s*\(",
    re.MULTILINE,
)

# Match arrow functions or variable function expressions: const foo = (...) =>
ARROW_FUNC_PATTERN = re.compile(
    r"^\s*(?P<export>export\s+)?(?:const|let|var)\s+(?P<name>[a-zA-Z0-9_$]+)\s*=\s*(?P<async>async\s+)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)?\s*=>",
    re.MULTILINE,
)

# Match class methods: public processOrder(...) or static async foo(...)
CLASS_METHOD_PATTERN = re.compile(
    r"^\s*(?:(?P<vis>public|private|protected)\s+)?(?:(?P<static>static)\s+)?(?:(?P<async>async)\s+)?(?P<name>[a-zA-Z0-9_$]+)\s*\(",
    re.MULTILINE,
)

# Match class definition headers: export class OrderPricingEngine
CLASS_HEADER_PATTERN = re.compile(
    r"^\s*(?:(?P<export>export\s+)?(?:default\s+)?)?class\s+(?P<name>[a-zA-Z0-9_$]+)",
    re.MULTILINE,
)

IMPORT_PATTERN = re.compile(
    r"^\s*(?:import\s+.*?from\s+['\"].*?['\"]|const\s+.*?=\s*require\(.*?\)|\bimport\s+['\"].*?['\"]);?",
    re.MULTILINE,
)

RESERVED_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "throw", "function",
    "constructor", "get", "set", "new", "typeof", "interface", "type",
}


def extract_ts_types_and_interfaces(content: str) -> List[str]:
    """Extract TypeScript interface, type, and enum declarations from file content."""
    lines = content.splitlines()
    results: List[str] = []
    i = 0
    type_header_pattern = re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+[a-zA-Z0-9_$]+")
    while i < len(lines):
        line = lines[i]
        if type_header_pattern.search(line):
            code, end_idx = _extract_enclosing_block(lines, i)
            if "{" not in code:
                single_lines = []
                for j in range(i, len(lines)):
                    single_lines.append(lines[j])
                    if ";" in lines[j]:
                        i = j + 1
                        break
                else:
                    i += 1
                results.append("\n".join(single_lines).strip())
                continue
            results.append(code.strip())
            i = end_idx
            continue
        i += 1
    return results


def _extract_constructor(lines: List[str], class_name: str) -> Optional[str]:
    """Extract the constructor body of a class if present."""
    in_class = False
    class_pattern = re.compile(rf"^\s*(?:(?:export\s+)?(?:default\s+)?)?class\s+{re.escape(class_name)}\b")
    for idx, line in enumerate(lines):
        if class_pattern.search(line):
            in_class = True
            continue
        if in_class:
            if re.search(r"^\s*(?:public|private|protected)?\s*constructor\s*\(", line):
                code, _ = _extract_enclosing_block(lines, idx)
                return code
            if line.strip().startswith("class "):
                break
    return None



def extract_ts_imports(file_content: str) -> List[str]:
    """Extract all import statements from TypeScript/JavaScript file."""
    return [match.group(0).strip() for match in IMPORT_PATTERN.finditer(file_content)]


def _extract_enclosing_block(lines: List[str], start_idx: int) -> tuple[str, int]:
    """
    Extract code block starting at start_idx by balancing opening and closing braces.
    Handles multiline signatures where the opening brace '{' is on a subsequent line.
    """
    brace_count = 0
    found_first_brace = False
    block_lines: List[str] = []
    end_idx = start_idx

    for i in range(start_idx, len(lines)):
        line = lines[i]
        block_lines.append(line)

        # Count braces roughly
        for char in line:
            if char == "{":
                brace_count += 1
                found_first_brace = True
            elif char == "}":
                brace_count -= 1

        if found_first_brace and brace_count == 0:
            end_idx = i
            break

    return "\n".join(block_lines), end_idx + 1


def _scan_file_candidates(content: str) -> List[tuple[str, int, bool, bool, Optional[str]]]:
    """
    Scan TypeScript / JavaScript file and return candidates:
    tuple: (name, start_idx_0_based, is_exported, is_async, class_name)
    """
    lines = content.splitlines()
    candidates: List[tuple[str, int, bool, bool, Optional[str]]] = []

    # Track enclosing class
    current_class: Optional[str] = None
    class_brace_depth = 0
    class_start_idx = -1

    for idx, line in enumerate(lines):
        # Check if line enters a class
        class_match = CLASS_HEADER_PATTERN.search(line)
        if class_match and "{" in line:
            current_class = class_match.group("name")
            class_brace_depth = 1
            class_start_idx = idx
            continue

        if current_class:
            for char in line:
                if char == "{":
                    class_brace_depth += 1
                elif char == "}":
                    class_brace_depth -= 1
            if class_brace_depth <= 0:
                current_class = None
                class_brace_depth = 0

        # Check standalone functions
        m_func = STANDALONE_FUNC_PATTERN.search(line)
        if m_func:
            name = m_func.group("name")
            if name not in RESERVED_KEYWORDS:
                candidates.append((
                    name,
                    idx,
                    bool(m_func.group("export")),
                    bool(m_func.group("async")),
                    None,
                    False,
                ))
                continue

        # Check arrow functions
        m_arrow = ARROW_FUNC_PATTERN.search(line)
        if m_arrow:
            name = m_arrow.group("name")
            if name not in RESERVED_KEYWORDS:
                candidates.append((
                    name,
                    idx,
                    bool(m_arrow.group("export")),
                    bool(m_arrow.group("async")),
                    None,
                    False,
                ))
                continue

        # Check class methods (inside a class or with visibility keyword)
        m_method = CLASS_METHOD_PATTERN.search(line)
        if m_method:
            name = m_method.group("name")
            has_vis = bool(m_method.group("vis"))
            is_stat = bool(m_method.group("static"))
            if name not in RESERVED_KEYWORDS and (current_class is not None or has_vis):
                candidates.append((
                    name,
                    idx,
                    current_class is not None,  # exported with class
                    bool(m_method.group("async")),
                    current_class,
                    is_stat,
                ))
                continue

    return candidates


def extract_ts_context(
    file_path: Path,
    target_name: Optional[str] = None,
    target_line: Optional[int] = None,
) -> TSContext:
    """Extract TypeScript/JavaScript function context from file."""
    content = file_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    imports = extract_ts_imports(content)

    # Try Tree-sitter AST extraction first
    try:
        from breakheal.ts_ast import parse_ts_ast, generate_ts_api_contract
        is_tsx = file_path.suffix.lower() in {".tsx", ".jsx"}
        ast_parsed = parse_ts_ast(content, is_tsx=is_tsx)
    except Exception:
        ast_parsed = None

    if ast_parsed and ast_parsed.all_functions:
        chosen_fn = None
        if target_name:
            for f in ast_parsed.all_functions:
                if f.name == target_name or (f.enclosing_class and f"{f.enclosing_class}.{f.name}" == target_name):
                    chosen_fn = f
                    break
            if not chosen_fn:
                raise ValueError(f"Function '{target_name}' not found in {file_path}")
        elif target_line:
            for f in ast_parsed.all_functions:
                if f.start_line <= target_line <= f.end_line:
                    chosen_fn = f
                    break
            if not chosen_fn:
                chosen_fn = ast_parsed.all_functions[0]
        else:
            # Threat Surface Ranking:
            # 1. Exported status
            # 2. Threat score descending (zero-division, array out-of-bounds, JSON.parse)
            sorted_fns = sorted(
                ast_parsed.all_functions,
                key=lambda f: (1 if f.is_exported else 0, f.threat_score),
                reverse=True,
            )
            chosen_fn = sorted_fns[0]

        target_display_name = f"{chosen_fn.enclosing_class}.{chosen_fn.name}" if chosen_fn.enclosing_class else chosen_fn.name
        constructor_code = _extract_constructor(lines, chosen_fn.enclosing_class) if chosen_fn.enclosing_class else None
        types_and_interfaces = [t.source_code for t in ast_parsed.types]
        api_contract = generate_ts_api_contract(ast_parsed, target_display_name)

        return TSContext(
            target_name=target_display_name,
            file_path=str(file_path),
            source_code=chosen_fn.source_code,
            start_line=chosen_fn.start_line,
            end_line=chosen_fn.end_line,
            imports=imports,
            is_exported=chosen_fn.is_exported,
            is_async=chosen_fn.is_async,
            class_name=chosen_fn.enclosing_class,
            is_static=chosen_fn.is_static,
            full_source=content,
            constructor_code=constructor_code,
            types_and_interfaces=types_and_interfaces,
            api_contract=api_contract,
            threat_score=chosen_fn.threat_score,
            threat_reasons=chosen_fn.threat_reasons,
        )

    # Fallback to regex scanner if AST is unavailable
    candidates = _scan_file_candidates(content)

    if not candidates:
        raise ValueError(f"No TypeScript/JavaScript functions found in {file_path}")

    chosen = None
    if target_name:
        for item in candidates:
            name, idx, is_export, is_async, cls, is_stat = item
            if name == target_name or (cls and f"{cls}.{name}" == target_name):
                chosen = item
                break
        if not chosen:
            raise ValueError(f"Function '{target_name}' not found in {file_path}")
    elif target_line:
        for item in candidates:
            name, idx, is_export, is_async, cls, is_stat = item
            code, end_line = _extract_enclosing_block(lines, idx)
            start_line = idx + 1
            if start_line <= target_line <= end_line:
                chosen = item
                break
        if not chosen:
            chosen = candidates[0]
    else:
        chosen = candidates[0]

    name, start_idx, is_export, is_async, cls, is_stat = chosen
    code, end_line = _extract_enclosing_block(lines, start_idx)

    target_display_name = f"{cls}.{name}" if cls else name
    constructor_code = _extract_constructor(lines, cls) if cls else None
    types_and_interfaces = extract_ts_types_and_interfaces(content)

    return TSContext(
        target_name=target_display_name,
        file_path=str(file_path),
        source_code=code,
        start_line=start_idx + 1,
        end_line=end_line,
        imports=imports,
        is_exported=is_export,
        is_async=is_async,
        class_name=cls,
        is_static=is_stat,
        full_source=content,
        constructor_code=constructor_code,
        types_and_interfaces=types_and_interfaces,
    )


def scan_directory_for_ts_functions(directory: Path) -> List[TSContext]:
    """Discover all TypeScript and JavaScript functions in a directory."""
    contexts: List[TSContext] = []
    exts = {".ts", ".js", ".mjs", ".cjs"}

    for path in directory.rglob("*"):
        if (
            path.suffix in exts
            and "node_modules" not in path.parts
            and "test" not in path.name.lower()
            and not path.name.endswith(".d.ts")
        ):
            try:
                content = path.read_text(encoding="utf-8")
                lines = content.splitlines()
                imports = extract_ts_imports(content)
                candidates = _scan_file_candidates(content)
                types_and_interfaces = extract_ts_types_and_interfaces(content)

                for name, idx, is_export, is_async, cls, is_stat in candidates:
                    code, end_line = _extract_enclosing_block(lines, idx)
                    target_display_name = f"{cls}.{name}" if cls else name
                    constructor_code = _extract_constructor(lines, cls) if cls else None
                    contexts.append(
                        TSContext(
                            target_name=target_display_name,
                            file_path=str(path),
                            source_code=code,
                            start_line=idx + 1,
                            end_line=end_line,
                            imports=imports,
                            is_exported=is_export,
                            is_async=is_async,
                            class_name=cls,
                            is_static=is_stat,
                            full_source=content,
                            constructor_code=constructor_code,
                            types_and_interfaces=types_and_interfaces,
                        )
                    )
            except Exception:
                continue

    return contexts
