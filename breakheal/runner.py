"""Subprocess pytest runner returning execution status, output, and error logs."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    combined_output: str
    target_path: str

    @property
    def failed(self) -> bool:
        return not self.passed


def find_project_root(start_path: str | Path | None = None) -> Path:
    """Locate the nearest repository root containing pyproject.toml, .git, or setup.py."""
    current = Path(start_path).resolve() if start_path else Path.cwd()
    if current.is_file():
        current = current.parent
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").is_file() or (parent / ".git").is_dir() or (parent / "setup.py").is_file():
            return parent
    return Path.cwd()


def run_pytest(
    target_path: str | Path,
    extra_args: list[str] | None = None,
    timeout: float = 30.0,
    cwd: str | Path | None = None,
) -> TestResult:
    """Run pytest on the target path and return structured TestResult."""
    target_str = str(target_path)
    cmd = [sys.executable, "-m", "pytest", target_str]
    if extra_args:
        cmd.extend(extra_args)

    # Ensure Python path includes root directory first so top-level imports resolve cleanly
    env = os.environ.copy()
    root_dir = str(find_project_root(cwd or target_path))
    exec_cwd = str(cwd) if cwd else root_dir
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths_to_add = f"{root_dir}{os.pathsep}{exec_cwd}"
    env["PYTHONPATH"] = (
        f"{paths_to_add}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else paths_to_add
    )

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=exec_cwd,
            env=env,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = f"{stdout}\n{stderr}".strip()
        return TestResult(
            passed=(proc.returncode == 0),
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            combined_output=combined,
            target_path=target_str,
        )
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        timeout_msg = f"Pytest execution timed out after {timeout} seconds."
        return TestResult(
            passed=False,
            exit_code=-1,
            stdout=stdout,
            stderr=f"{stderr}\n{timeout_msg}".strip(),
            combined_output=f"{stdout}\n{stderr}\n{timeout_msg}".strip(),
            target_path=target_str,
        )
    except Exception as e:
        err_msg = f"Failed to execute pytest: {e}"
        return TestResult(
            passed=False,
            exit_code=-2,
            stdout="",
            stderr=err_msg,
            combined_output=err_msg,
            target_path=target_str,
        )


def run_regression_suite(
    test_paths: list[str | Path] | None = None,
    cwd: str | Path | None = None,
    timeout: float = 60.0,
) -> TestResult:
    """Run baseline test suite across repository to verify no regressions."""
    root_dir = find_project_root(cwd)

    if test_paths and len(test_paths) > 0:
        first = str(test_paths[0])
        rest = [str(p) for p in test_paths[1:]]
        return run_pytest(first, extra_args=rest, timeout=timeout, cwd=root_dir)

    # Discover candidate test suites in root
    candidates = []
    for d in ["tests", "demo_repo"]:
        p = root_dir / d
        if p.is_dir():
            candidates.append(d)

    if not candidates:
        candidates = ["."]

    extra_args = candidates[1:] if len(candidates) > 1 else []
    extra_args.extend(["-k", "not test_breakheal_"])

    return run_pytest(candidates[0], extra_args=extra_args, timeout=timeout, cwd=root_dir)
