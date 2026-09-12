"""Java Maven/JUnit 5 subprocess test runner."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class JavaTestResult:
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    combined_output: str
    target_class: str

    @property
    def failed(self) -> bool:
        return not self.passed


def find_maven_root(start_path: str | Path) -> Path | None:
    """Find the nearest directory containing pom.xml by walking upwards."""
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent

    for parent in [current] + list(current.parents):
        if (parent / "pom.xml").is_file():
            return parent
    return None


def get_maven_executable() -> str:
    """Resolve the Maven executable path across Windows and POSIX."""
    mvn = shutil.which("mvn.cmd") or shutil.which("mvn.CMD") or shutil.which("mvn")
    return mvn or "mvn"


def run_maven_test(
    maven_root: str | Path,
    test_class: str | None = None,
    timeout: float = 60.0,
) -> JavaTestResult:
    """Run Maven Surefire test for a specific test class or the whole suite."""
    root_path = Path(maven_root).resolve()
    mvn_cmd = get_maven_executable()

    cmd = [mvn_cmd, "test", "--batch-mode"]
    if test_class:
        cmd.append(f"-Dtest={test_class}")

    target_desc = test_class or "All Tests"

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=str(root_path),
            encoding="utf-8",
            errors="replace",
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        combined = f"{stdout}\n{stderr}".strip()

        return JavaTestResult(
            passed=(proc.returncode == 0),
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            combined_output=combined,
            target_class=target_desc,
        )
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        timeout_msg = f"Maven test timed out after {timeout} seconds."
        return JavaTestResult(
            passed=False,
            exit_code=-1,
            stdout=stdout,
            stderr=f"{stderr}\n{timeout_msg}".strip(),
            combined_output=f"{stdout}\n{stderr}\n{timeout_msg}".strip(),
            target_class=target_desc,
        )
    except Exception as e:
        err_msg = f"Failed to execute Maven: {e}"
        return JavaTestResult(
            passed=False,
            exit_code=-2,
            stdout="",
            stderr=err_msg,
            combined_output=err_msg,
            target_class=target_desc,
        )
