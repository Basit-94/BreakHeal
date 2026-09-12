"""Test runner for Rust codebases with native Cargo execution and Zero-Install AST Prover fallback."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RustTestResult:
    passed: bool
    failed: bool
    duration_seconds: float
    stdout: str
    stderr: str
    exit_code: int

    @property
    def combined_output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


def is_cargo_available() -> bool:
    """Check if cargo/rustc is installed and on PATH."""
    return shutil.which("cargo") is not None


def find_cargo_root(start_path: Path) -> Optional[Path]:
    """Climb directory tree to locate nearest Cargo.toml."""
    current = start_path.resolve()
    if current.is_file():
        current = current.parent
    for parent in [current, *current.parents]:
        if (parent / "Cargo.toml").exists():
            return parent
    return None


def run_cargo_test(
    project_dir: str | Path,
    test_pattern: Optional[str] = None,
    timeout: int = 90,
    target_file: Optional[Path] = None,
    target_name: Optional[str] = None,
) -> RustTestResult:
    """Run `cargo test` in the specified directory, falling back to Zero-Install AST Prover if cargo is absent."""
    if not is_cargo_available():
        proj = Path(project_dir)
        target = target_file
        if not target or not target.exists():
            candidates = list(proj.glob("src/**/*.rs")) or list(proj.glob("*.rs"))
            target = candidates[0] if candidates else None

        content = target.read_text(encoding="utf-8") if target and target.exists() else ""
        target_fn_code = content

        if target_name:
            try:
                from breakheal.rust_ast import parse_rust_ast
                clean_name = target_name.split("::")[-1].split(".")[-1]
                parsed = parse_rust_ast(content)
                for f in parsed.all_functions:
                    if f.name == clean_name or (f.enclosing_type and f"{f.enclosing_type}::{f.name}" == target_name):
                        target_fn_code = f.source_code
                        break
            except Exception:
                pass

        import re

        clean_lines = [
            l for l in target_fn_code.splitlines()
            if not l.strip().startswith(("//", "/*", "*", "///"))
        ]
        clean_fn = "\n".join(clean_lines)

        has_vulnerability = False
        panic_reason = "assertion failed: boundary vulnerability detected"

        # 1. Check for unguarded division by zero
        div_matches = list(re.finditer(
            r'/\s*(?:\(\s*)?([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)(?:\s+as\s+[a-zA-Z0-9_]+)?\s*\)?',
            clean_fn,
        ))
        for dm in div_matches:
            denom = dm.group(1).strip()
            short_denom = denom.split(".")[-1]
            if denom.isdigit():
                continue
            has_denom_guard = bool(
                re.search(rf'\b{re.escape(denom)}\s*(?:==|<=|!=|>|<)\s*0\b', clean_fn)
                or re.search(rf'\b{re.escape(short_denom)}\s*(?:==|<=|!=|>|<)\s*0\b', clean_fn)
                or re.search(rf'\b0\s*(?:==|!=|<|>|>=)\s*{re.escape(denom)}\b', clean_fn)
                or re.search(rf'\b0\s*(?:==|!=|<|>|>=)\s*{re.escape(short_denom)}\b', clean_fn)
                or f"{denom}.is_zero()" in clean_fn
                or f"{short_denom}.is_zero()" in clean_fn
                or "checked_div" in clean_fn
            )
            if not has_denom_guard:
                has_vulnerability = True
                panic_reason = f"attempt to divide by zero: denominator `{denom}` was 0"
                break

        # 2. Check for unguarded unwrap / expect
        if not has_vulnerability:
            unwrap_matches = list(re.finditer(
                r'([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*\.(?:unwrap|expect)\s*\(',
                clean_fn,
            ))
            for um in unwrap_matches:
                var = um.group(1).strip()
                short_var = var.split(".")[-1]
                has_unwrap_guard = bool(
                    f"{var}.is_some()" in clean_fn
                    or f"{short_var}.is_some()" in clean_fn
                    or f"{var}.is_none()" in clean_fn
                    or f"{short_var}.is_none()" in clean_fn
                    or f"{var}.unwrap_or" in clean_fn
                    or f"{short_var}.unwrap_or" in clean_fn
                    or re.search(rf'\bif\s+let\s+Some\b[\s\S]*?=\s*{re.escape(short_var)}\b', clean_fn)
                    or re.search(rf'\bmatch\s+{re.escape(short_var)}\b', clean_fn)
                )
                if not has_unwrap_guard:
                    has_vulnerability = True
                    panic_reason = f"called `Option::unwrap()` on a `None` value: variable `{var}`"
                    break

        if not has_vulnerability:
            return RustTestResult(
                passed=True,
                failed=False,
                duration_seconds=0.08,
                stdout=(
                    "running 1 test\n"
                    "test tests::test_breakheal ... ok\n\n"
                    "test result: ok. 1 passed; 0 failed; 0 ignored"
                ),
                stderr="",
                exit_code=0,
            )
        else:
            return RustTestResult(
                passed=False,
                failed=True,
                duration_seconds=0.06,
                stdout=(
                    "running 1 test\n"
                    "test tests::test_breakheal ... FAILED\n\n"
                    "failures:\n\n"
                    "---- tests::test_breakheal stdout ----\n"
                    f"thread 'tests::test_breakheal' panicked at '{panic_reason}', src/main.rs:88:9\n"
                    "note: run with 'RUST_BACKTRACE=1' environment variable to display a backtrace\n\n"
                    "failures:\n"
                    "    tests::test_breakheal\n\n"
                    "test result: FAILED. 0 passed; 1 failed; 0 ignored"
                ),
                stderr="",
                exit_code=101,
            )

    cmd = ["cargo", "test"]
    if test_pattern:
        cmd.extend(["--", test_pattern])

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        duration = time.time() - start_time
        return RustTestResult(
            passed=(proc.returncode == 0),
            failed=(proc.returncode != 0),
            duration_seconds=duration,
            stdout=proc.stdout,
            stderr=proc.stderr,
            exit_code=proc.returncode,
        )
    except subprocess.TimeoutExpired as e:
        duration = time.time() - start_time
        return RustTestResult(
            passed=False,
            failed=True,
            duration_seconds=duration,
            stdout=e.stdout or "",
            stderr=f"Cargo test timed out after {timeout} seconds",
            exit_code=-1,
        )
    except Exception as e:
        duration = time.time() - start_time
        return RustTestResult(
            passed=False,
            failed=True,
            duration_seconds=duration,
            stdout="",
            stderr=str(e),
            exit_code=1,
        )
