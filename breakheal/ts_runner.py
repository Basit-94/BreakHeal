"""Subprocess test runner for TypeScript and JavaScript using Node.js or Vitest."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from breakheal.runner import TestResult


def resolve_node_cmd() -> str:
    """Find node executable in PATH."""
    node_bin = shutil.which("node")
    if not node_bin:
        raise FileNotFoundError("Node.js runtime not found in PATH.")
    return node_bin


def run_node_test(
    test_path: Path,
    cwd: Optional[Path] = None,
    timeout: float = 30.0,
) -> TestResult:
    """Execute a test file using Node.js built-in test runner."""
    node_bin = resolve_node_cmd()
    exec_cwd = cwd or test_path.parent

    # If the file is TypeScript, run with experimental strip types or tsx if available
    cmd = [node_bin]
    if test_path.suffix in (".ts", ".mts"):
        cmd.extend(["--experimental-strip-types"])
    cmd.extend(["--test", str(test_path.resolve())])

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(exec_cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        passed = proc.returncode == 0
        combined = f"{proc.stdout}\n{proc.stderr}".strip()

        return TestResult(
            passed=passed,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            combined_output=combined,
            target_path=str(test_path),
        )

    except subprocess.TimeoutExpired as e:
        stdout = e.stdout or "" if isinstance(e.stdout, str) else ""
        stderr = e.stderr or "" if isinstance(e.stderr, str) else ""
        return TestResult(
            passed=False,
            exit_code=-1,
            stdout=stdout,
            stderr=f"Execution timed out after {timeout} seconds.\n{stderr}",
            combined_output=f"Timeout: {timeout}s",
            target_path=str(test_path),
        )
    except Exception as e:
        return TestResult(
            passed=False,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            combined_output=f"Error executing test: {str(e)}",
            target_path=str(test_path),
        )
