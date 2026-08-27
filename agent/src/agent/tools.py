"""Tool definitions for the RLM agent environment."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

MAX_TOOL_OUTPUT_CHARS = 10_000


def truncate_output(text: str, max_chars: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    """Format large text outputs with head and tail preservation."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    omitted = len(text) - max_chars
    return text[:half] + f"\n\n... [{omitted:,} characters omitted] ...\n\n" + text[-half:]


def bash(command: str, timeout: int = 180) -> str:
    """Run a bash shell command in the container workspace.

    Args:
        command: The shell command to execute.
        timeout: Execution timeout in seconds (default: 180).

    Returns:
        Combined stdout and stderr from the command, including exit code if failed.
    """
    if not command.strip():
        return "[Error] Empty command provided."

    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        combined = (proc.stdout + proc.stderr).strip()
        if proc.returncode != 0:
            header = f"[Command exited with status {proc.returncode}]"
            full_out = f"{header}\n{combined}" if combined else header
            return truncate_output(full_out)
        return truncate_output(combined) or "(command executed successfully with no output, exit status 0)"
    except subprocess.TimeoutExpired:
        return f"[Error] Command timed out after {timeout} seconds."
    except Exception as exc:
        return f"[Error] Subprocess execution failed: {exc}"


def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
    """Read lines from a file with 1-indexed line numbers.

    Args:
        path: Path to the target file.
        start_line: First line to read (1-indexed, inclusive).
        end_line: Last line to read (1-indexed, inclusive). If None, reads up to 500 lines.

    Returns:
        Formatted file contents with line numbers or error description.
    """
    target = Path(path)
    if not target.exists():
        return f"[Error] File does not exist: {path}"
    if target.is_dir():
        return f"[Error] Path '{path}' is a directory, not a file."

    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        if total == 0:
            return f"(File '{path}' is empty)"

        start_idx = max(1, start_line) - 1
        if start_idx >= total:
            return f"[Error] start_line {start_line} exceeds total lines ({total})"

        end_limit = total if end_line is None else min(total, max(start_line, end_line))
        # Cap read block size to 500 lines per call to keep context clean
        if end_line is None and end_limit - start_idx > 500:
            end_limit = start_idx + 500

        formatted = [f"{i + 1:4d}: {lines[i]}" for i in range(start_idx, end_limit)]
        header = f"File: {path} (lines {start_idx + 1}-{end_limit} of {total}):\n"
        return header + "\n".join(formatted)
    except Exception as exc:
        return f"[Error] Failed reading '{path}': {exc}"


def write_file(path: str, content: str) -> str:
    """Write or overwrite content to a file, creating parent directories if needed.

    Args:
        path: Path to the destination file.
        content: String content to write.

    Returns:
        Status message indicating success or failure.
    """
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"[Success] Wrote {len(content)} characters ({len(content.splitlines())} lines) to '{path}'"
    except Exception as exc:
        return f"[Error] Failed writing to '{path}': {exc}"


def patch_file(path: str, target: str, replacement: str) -> str:
    """Perform a surgical, precise string replacement in a file.

    Args:
        path: Path to the target file to edit.
        target: Exact string to be replaced (must match uniquely).
        replacement: String to replace the target with.

    Returns:
        Status message confirming replacement or reporting ambiguity/absence.
    """
    file_path = Path(path)
    if not file_path.exists():
        return f"[Error] File not found: {path}"

    try:
        content = file_path.read_text(encoding="utf-8")
        occurrences = content.count(target)

        if occurrences == 0:
            return f"[Error] Target string not found in '{path}'. Ensure whitespace and formatting match exactly."
        if occurrences > 1:
            return f"[Error] Target string found {occurrences} times in '{path}'. Include more surrounding lines to make it unique."

        updated = content.replace(target, replacement, 1)
        file_path.write_text(updated, encoding="utf-8")
        return f"[Success] Successfully patched '{path}'"
    except Exception as exc:
        return f"[Error] Failed patching '{path}': {exc}"


def find_files(pattern: str = "*", root: str = ".") -> list[str]:
    """Find files matching a glob pattern relative to root directory.

    Args:
        pattern: Glob pattern (e.g. '*.py', '*.sql', '**/*.csv').
        root: Root directory to search within (default: current directory).

    Returns:
        List of matching relative file paths.
    """
    base = Path(root)
    if not base.exists():
        return []

    ignored_dirs = {".git", "__pycache__", ".venv", "jobs", ".pytest_cache", ".ruff_cache"}
    matches: list[str] = []

    try:
        for p in base.glob(pattern):
            # Check if path contains ignored directory
            if any(part in ignored_dirs for part in p.parts):
                continue
            if p.is_file():
                matches.append(str(p.relative_to(base) if root == "." else p))
    except Exception:
        pass

    return sorted(matches)


def grep_search(query: str, root: str = ".", is_regex: bool = False) -> str:
    """Search for matching strings or regular expressions across files.

    Args:
        query: String or regex to search for.
        root: Search path (default: current directory).
        is_regex: True if query is a regex pattern, False for literal substring search.

    Returns:
        Line matches with file paths and line numbers.
    """
    cmd = ["grep", "-rn", "-I"]
    if not is_regex:
        cmd.append("-F")
    cmd.extend([
        "--exclude-dir=.git",
        "--exclude-dir=__pycache__",
        "--exclude-dir=.venv",
        "--exclude-dir=jobs",
        "--exclude-dir=.pytest_cache",
        query,
        root,
    ])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        lines = proc.stdout.strip().splitlines()
        if not lines:
            return f"No matches found for '{query}' in '{root}'."
        if len(lines) > 60:
            return "\n".join(lines[:60]) + f"\n\n... [{len(lines) - 60} additional matches truncated] ..."
        return "\n".join(lines)
    except Exception as exc:
        return f"[Error] grep execution failed: {exc}"


def duckdb_query(query: str, db_path: str = "") -> str:
    """Execute a SQL query via DuckDB CLI or python and return tabular results.

    Args:
        query: The SQL query to execute.
        db_path: Path to the duckdb database file, or empty for in-memory / direct table querying.

    Returns:
        Tabular query results or error message.
    """
    # Prefer CLI when available
    if shutil.which("duckdb"):
        cmd = ["duckdb"]
        if db_path and db_path.strip():
            cmd.append(db_path.strip())
        cmd.extend(["-c", query])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            res = (proc.stdout + proc.stderr).strip()
            if proc.returncode != 0:
                return f"[DuckDB Exit {proc.returncode}]\n{res}"
            return truncate_output(res) or "(0 rows returned)"
        except Exception as exc:
            return f"[Error] DuckDB CLI failed: {exc}"

    # Fallback to python duckdb module if present
    try:
        import duckdb  # type: ignore

        conn = duckdb.connect(db_path) if db_path and db_path.strip() else duckdb.connect()
        df = conn.execute(query).df()
        return truncate_output(str(df))
    except Exception as exc:
        return f"[Error] DuckDB query failed: {exc}"


ALL_TOOLS: Sequence = [
    bash,
    read_file,
    write_file,
    patch_file,
    find_files,
    grep_search,
    duckdb_query,
]
