"""Rust context extractor capturing module, types, impl blocks, and threat scores."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from breakheal.rust_ast import parse_rust_ast, generate_rust_api_contract


@dataclass
class RustContext:
    file_path: str
    target_name: str
    function_code: str
    start_line: int
    end_line: int
    uses: list[str]
    full_source: str
    enclosing_type: Optional[str] = None
    is_pub: bool = True
    is_method: bool = False
    api_contract: str = ""
    threat_score: int = 0
    threat_reasons: list[str] = field(default_factory=list)


def extract_rust_context(
    file_path: str | Path,
    target_name: Optional[str] = None,
    line_number: Optional[int] = None,
) -> RustContext:
    """Extract Rust AST metadata, target function, threat score, and API contract."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Rust file not found: {file_path}")

    source = path.read_text(encoding="utf-8")
    parsed = parse_rust_ast(source)

    if not parsed.all_functions:
        raise ValueError(f"No functions found in Rust file: {file_path}")

    chosen_fn = None
    if target_name:
        for f in parsed.all_functions:
            if f.name == target_name or (f.enclosing_type and f"{f.enclosing_type}::{f.name}" == target_name):
                chosen_fn = f
                break
        if not chosen_fn:
            raise ValueError(f"Function '{target_name}' not found in {file_path}")
    elif line_number is not None:
        for f in parsed.all_functions:
            if f.start_line <= line_number <= f.end_line:
                chosen_fn = f
                break
        if not chosen_fn:
            chosen_fn = parsed.all_functions[0]
    else:
        # Threat Surface Ranking:
        # 1. Public functions first
        # 2. Threat score descending (unwrap, overflow, panic, slice bounds)
        sorted_fns = sorted(
            parsed.all_functions,
            key=lambda f: (1 if f.is_pub else 0, f.threat_score),
            reverse=True,
        )
        chosen_fn = sorted_fns[0]

    target_display = f"{chosen_fn.enclosing_type}::{chosen_fn.name}" if chosen_fn.enclosing_type else chosen_fn.name
    api_contract = generate_rust_api_contract(parsed, target_display)

    return RustContext(
        file_path=str(path),
        target_name=target_display,
        function_code=chosen_fn.source_code,
        start_line=chosen_fn.start_line,
        end_line=chosen_fn.end_line,
        uses=parsed.uses,
        full_source=source,
        enclosing_type=chosen_fn.enclosing_type,
        is_pub=chosen_fn.is_pub,
        is_method=chosen_fn.is_method,
        api_contract=api_contract,
        threat_score=chosen_fn.threat_score,
        threat_reasons=chosen_fn.threat_reasons,
    )


def scan_directory_for_rust_functions(directory: str | Path) -> list[RustContext]:
    """Recursively find all Rust functions across .rs files in a directory."""
    dir_path = Path(directory).resolve()
    if not dir_path.is_dir():
        return []

    contexts: list[RustContext] = []
    for file_path in sorted(dir_path.rglob("*.rs")):
        if "target" in file_path.parts or ".git" in file_path.parts:
            continue
        try:
            source = file_path.read_text(encoding="utf-8")
            parsed = parse_rust_ast(source)
            for f in parsed.all_functions:
                t_name = f"{f.enclosing_type}::{f.name}" if f.enclosing_type else f.name
                ctx = extract_rust_context(file_path, target_name=t_name)
                contexts.append(ctx)
        except Exception:
            continue

    return contexts
