"""Git utilities for diff inspection, rollbacks, and SEARCH/REPLACE block parsing."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def run_git_command(
    args: list[str],
    cwd: str | Path | None = None,
) -> tuple[int, str, str]:
    """Execute a git command and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def get_uncommitted_diff(
    file_path: str | Path | None = None,
    cwd: str | Path | None = None,
) -> str:
    """Get unstaged and staged git diff for a specific file or entire workspace."""
    args = ["diff", "HEAD"]
    if file_path:
        args.extend(["--", str(file_path)])
    code, out, _ = run_git_command(args, cwd=cwd)
    if code != 0 or not out:
        # If HEAD does not exist yet or no diff against HEAD, check unstaged git diff
        fallback_args = ["diff"]
        if file_path:
            fallback_args.extend(["--", str(file_path)])
        _, out, _ = run_git_command(fallback_args, cwd=cwd)
    return out


def get_branch_diff(
    base_branch: str = "main",
    cwd: str | Path | None = None,
) -> str:
    """Get git diff between a base branch and the current HEAD."""
    # Try 3-dot diff origin/<base>...HEAD
    code, out, _ = run_git_command(["diff", f"origin/{base_branch}...HEAD"], cwd=cwd)
    if code == 0 and out:
        return out

    # Try local 3-dot diff <base>...HEAD
    code, out, _ = run_git_command(["diff", f"{base_branch}...HEAD"], cwd=cwd)
    if code == 0 and out:
        return out

    # Fallback to direct diff against base
    code, out, _ = run_git_command(["diff", base_branch], cwd=cwd)
    if code == 0 and out:
        return out

    # Fallback to uncommitted diff
    return get_uncommitted_diff(cwd=cwd)


def get_branch_modified_file_lines(
    base_branch: str = "main",
    cwd: str | Path | None = None,
) -> dict[str, list[int]]:
    """Return map of modified files and changed line numbers compared to base branch."""
    diff_text = get_branch_diff(base_branch=base_branch, cwd=cwd)
    return parse_diff_modified_lines(diff_text)


def create_and_checkout_branch(branch_name: str, cwd: str | Path | None = None) -> bool:
    """Create and switch to a new git branch."""
    code, _, _ = run_git_command(["checkout", "-b", branch_name], cwd=cwd)
    return code == 0


def commit_files(
    files: list[str | Path],
    message: str,
    cwd: str | Path | None = None,
) -> bool:
    """Stage specified files and create a git commit."""
    paths = [str(f) for f in files]
    code, _, _ = run_git_command(["add"] + paths, cwd=cwd)
    if code != 0:
        return False
    code, _, _ = run_git_command(["commit", "-m", message], cwd=cwd)
    return code == 0


def parse_diff_modified_lines(diff_text: str) -> dict[str, list[int]]:
    """Parse unified git diff output and extract changed line numbers per file.
    
    Returns a dict mapping relative file paths to list of changed line numbers.
    """
    file_lines: dict[str, list[int]] = {}
    current_file: str | None = None

    diff_file_re = re.compile(r"^diff --git a/(.+?) b/(.+?)$")
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    for line in diff_text.splitlines():
        file_match = diff_file_re.match(line)
        if file_match:
            current_file = file_match.group(2)
            if current_file not in file_lines:
                file_lines[current_file] = []
            continue

        if current_file:
            hunk_match = hunk_re.match(line)
            if hunk_match:
                new_start = int(hunk_match.group(1))
                new_count = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
                for offset in range(new_count):
                    file_lines[current_file].append(new_start + offset)

    return file_lines


def get_modified_files(cwd: str | Path | None = None) -> list[str]:
    """Return list of modified or untracked file paths from git status."""
    code, out, _ = run_git_command(["status", "--porcelain"], cwd=cwd)
    if code != 0 or not out:
        return []

    files = []
    for line in out.splitlines():
        line = line.strip()
        if len(line) > 3:
            path = line[3:].strip()
            # If path is wrapped in quotes
            if path.startswith('"') and path.endswith('"'):
                path = path[1:-1]
            files.append(path)
    return files


def get_modified_file_lines(cwd: str | Path | None = None) -> dict[str, list[int]]:
    """Get map of all files with unstaged/staged modifications and their changed line numbers."""
    diff_text = get_uncommitted_diff(cwd=cwd)
    result = parse_diff_modified_lines(diff_text)

    # Also handle untracked files from git status
    status_files = get_modified_files(cwd=cwd)
    for f in status_files:
        if f.endswith(".py") and f not in result:
            target = Path(cwd or ".").resolve() / f
            if target.is_file():
                try:
                    num_lines = len(target.read_text(encoding="utf-8").splitlines())
                    result[f] = list(range(1, num_lines + 1))
                except Exception:
                    result[f] = [1]

    return result


def rollback_file(file_path: str | Path, cwd: str | Path | None = None) -> bool:
    """Discard uncommitted modifications to a file using git checkout/restore."""
    path_str = str(file_path)
    code, _, _ = run_git_command(["restore", "--", path_str], cwd=cwd)
    if code != 0:
        code, _, _ = run_git_command(["checkout", "HEAD", "--", path_str], cwd=cwd)
    return code == 0


def parse_search_replace_blocks(patch_text: str) -> list[tuple[str, str]]:
    """Parse SEARCH/REPLACE blocks from LLM patch response.
    
    Expected format:
    <<<<<<< SEARCH
    [exact matching original code]
    =======
    [replacement code]
    >>>>>>>
    """
    pattern = re.compile(
        r"<<<<<<< SEARCH[ \t]*\r?\n(.*?)\r?\n=======[ \t]*\r?\n(.*?)\r?\n>>>>>>>",
        re.DOTALL,
    )
    matches = pattern.findall(patch_text)
    return matches


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def apply_search_replace(
    file_content: str,
    search_block: str,
    replace_block: str,
) -> tuple[str, bool]:
    """Replace search_block with replace_block in file_content with newline tolerance."""
    if not search_block:
        return file_content, False

    # Exact string match first
    if search_block in file_content:
        return file_content.replace(search_block, replace_block, 1), True

    # Normalize newlines and try matching
    norm_content = _normalize_newlines(file_content)
    norm_search = _normalize_newlines(search_block)
    norm_replace = _normalize_newlines(replace_block)

    if norm_search in norm_content:
        updated = norm_content.replace(norm_search, norm_replace, 1)
        # Preserve original CRLF if source used CRLF
        if "\r\n" in file_content:
            updated = updated.replace("\n", "\r\n")
        return updated, True

    # Fuzzy match: strip trailing whitespace on each line
    content_lines = norm_content.split("\n")
    search_lines = [line.rstrip() for line in norm_search.split("\n")]
    replace_lines = norm_replace.split("\n")

    for i in range(len(content_lines) - len(search_lines) + 1):
        window = [line.rstrip() for line in content_lines[i : i + len(search_lines)]]
        if window == search_lines:
            new_lines = content_lines[:i] + replace_lines + content_lines[i + len(search_lines) :]
            updated = "\n".join(new_lines)
            if "\r\n" in file_content:
                updated = updated.replace("\n", "\r\n")
            return updated, True

    return file_content, False


def apply_patch_to_file(file_path: str | Path, patch_text: str) -> bool:
    """Parse SEARCH/REPLACE blocks and write modifications directly to file."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    blocks = parse_search_replace_blocks(patch_text)
    if not blocks:
        return False

    content = path.read_text(encoding="utf-8")
    modified = False

    for search_block, replace_block in blocks:
        content, success = apply_search_replace(content, search_block, replace_block)
        if success:
            modified = True

    if modified:
        path.write_text(content, encoding="utf-8")
        return True

    return False
