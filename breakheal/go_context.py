"""Go context extractor capturing package, imports, structs, methods, and threat scores."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from breakheal.go_ast import parse_go_ast, generate_go_api_contract


@dataclass
class GoContext:
    file_path: str
    package_name: str
    target_name: str
    function_code: str
    start_line: int
    end_line: int
    imports: list[str]
    full_source: str
    receiver_type: Optional[str] = None
    receiver_name: Optional[str] = None
    is_exported: bool = True
    api_contract: str = ""
    threat_score: int = 0
    threat_reasons: list[str] = field(default_factory=list)


def extract_go_context(
    file_path: str | Path,
    target_name: Optional[str] = None,
    line_number: Optional[int] = None,
) -> GoContext:
    """Extract Go AST metadata, target function/method, threat score, and API contract."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Go file not found: {file_path}")

    source = path.read_text(encoding="utf-8")
    parsed = parse_go_ast(source)

    if not parsed.all_functions:
        raise ValueError(f"No functions or methods found in Go file: {file_path}")

    chosen_fn = None
    if target_name:
        for f in parsed.all_functions:
            clean_recv = f.receiver_type.replace("*", "") if f.receiver_type else ""
            if f.name == target_name or (clean_recv and f"{clean_recv}.{f.name}" == target_name):
                chosen_fn = f
                break
        if not chosen_fn:
            raise ValueError(f"Function/Method '{target_name}' not found in {file_path}")
    elif line_number is not None:
        for f in parsed.all_functions:
            if f.start_line <= line_number <= f.end_line:
                chosen_fn = f
                break
        if not chosen_fn:
            chosen_fn = parsed.all_functions[0]
    else:
        # Threat Surface Ranking:
        # 1. Exported functions first
        # 2. Threat score descending (zero-division, slice bounds, panics)
        sorted_fns = sorted(
            parsed.all_functions,
            key=lambda f: (1 if f.is_exported else 0, f.threat_score),
            reverse=True,
        )
        chosen_fn = sorted_fns[0]

    clean_recv = chosen_fn.receiver_type.replace("*", "") if chosen_fn.receiver_type else ""
    target_display = f"{clean_recv}.{chosen_fn.name}" if clean_recv else chosen_fn.name
    api_contract = generate_go_api_contract(parsed, target_display)

    return GoContext(
        file_path=str(path),
        package_name=parsed.package_name,
        target_name=target_display,
        function_code=chosen_fn.source_code,
        start_line=chosen_fn.start_line,
        end_line=chosen_fn.end_line,
        imports=parsed.imports,
        full_source=source,
        receiver_type=chosen_fn.receiver_type,
        receiver_name=chosen_fn.receiver_name,
        is_exported=chosen_fn.is_exported,
        api_contract=api_contract,
        threat_score=chosen_fn.threat_score,
        threat_reasons=chosen_fn.threat_reasons,
    )


def scan_directory_for_go_functions(directory: str | Path) -> list[GoContext]:
    """Recursively find all Go functions across .go files in a directory."""
    dir_path = Path(directory).resolve()
    if not dir_path.is_dir():
        return []

    contexts: list[GoContext] = []
    for file_path in sorted(dir_path.rglob("*.go")):
        if file_path.name.endswith("_test.go") or "vendor" in file_path.parts or ".git" in file_path.parts:
            continue
        try:
            source = file_path.read_text(encoding="utf-8")
            parsed = parse_go_ast(source)
            for f in parsed.all_functions:
                clean_recv = f.receiver_type.replace("*", "") if f.receiver_type else ""
                t_name = f"{clean_recv}.{f.name}" if clean_recv else f.name
                ctx = extract_go_context(file_path, target_name=t_name)
                contexts.append(ctx)
        except Exception:
            continue

    return contexts
