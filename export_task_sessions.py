#!/usr/bin/env python3
"""Export Task Sessions from OpenCode Session Transcript.

This script parses an exported OpenCode session JSON file, discovers all `task`
tool calls, extracts their session IDs, runs `opencode export <session_id>` for
each, and collects all resulting exported JSON files into a target directory.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import typer

DEFAULT_EXTRACTIONS_DIR = Path(__file__).resolve().parent / "extractions"

app = typer.Typer(
    help="Extract task tool call session IDs from an OpenCode session JSON export and export them."
)


TASK_TAG_PATTERN = re.compile(
    r'<(?:task|subagent)\b[^>]*?\b(?:id|sessionID|sessionId)=["\']([^"\']+)["\']', re.IGNORECASE
)


class TaskCallInfo:
    """Stores information about a discovered task or subagent tool call."""

    def __init__(
        self,
        session_id: str,
        title: str = "",
        call_id: str = "",
        status: str = "",
    ):
        self.session_id = session_id
        self.title = title
        self.call_id = call_id
        self.status = status

    def __repr__(self) -> str:
        return (
            f"TaskCallInfo(session_id={self.session_id!r}, "
            f"title={self.title!r}, status={self.status!r})"
        )


def extract_session_id_from_task_call(part: Dict[str, Any]) -> Optional[str]:
    """Extract session ID from a task or subagent tool call dictionary."""
    state = part.get("state") or {}
    metadata = state.get("metadata") or {}

    # 1. Check state.metadata for sessionId, sessionID, or id
    for key in ("sessionId", "sessionID", "id"):
        sid = metadata.get(key)
        if sid and isinstance(sid, str) and sid.strip():
            return sid.strip()

    # 2. Check XML tag in state.output (v1)
    output = state.get("output")
    if output and isinstance(output, str):
        match = TASK_TAG_PATTERN.search(output)
        if match:
            return match.group(1).strip()

    # 3. Check XML tag in state.content (v2 list or string)
    content = state.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                match = TASK_TAG_PATTERN.search(block["text"])
                if match:
                    return match.group(1).strip()
    elif isinstance(content, str):
        match = TASK_TAG_PATTERN.search(content)
        if match:
            return match.group(1).strip()

    # 4. Check top-level metadata or fields if present
    part_meta = part.get("metadata") or {}
    for key in ("sessionId", "sessionID", "id"):
        sid = part_meta.get(key)
        if sid and isinstance(sid, str) and sid.strip():
            return sid.strip()

    return None


def find_task_calls(data: Any) -> List[TaskCallInfo]:
    """Recursively search parsed JSON structure for task and subagent tool calls."""
    results: List[TaskCallInfo] = []
    seen_ids = set()

    def _traverse(node: Any) -> None:
        if isinstance(node, dict):
            # Check if this node is a task or subagent tool call
            is_tool = node.get("type") == "tool"
            tool_name = node.get("tool") or node.get("name")
            if is_tool and tool_name in ("task", "subagent"):
                session_id = extract_session_id_from_task_call(node)
                if session_id and session_id not in seen_ids:
                    seen_ids.add(session_id)
                    state = node.get("state") or {}
                    inp = state.get("input") or {}
                    title = ""
                    if isinstance(state.get("title"), str) and state["title"].strip():
                        title = state["title"].strip()
                    elif isinstance(inp, dict):
                        if isinstance(inp.get("description"), str) and inp["description"].strip():
                            title = inp["description"].strip()
                        elif isinstance(inp.get("prompt"), str) and inp["prompt"].strip():
                            title = inp["prompt"].strip()[:60]
                    call_id = node.get("callID") or node.get("id") or ""
                    status = state.get("status") or ""
                    results.append(
                        TaskCallInfo(
                            session_id=session_id,
                            title=title,
                            call_id=call_id,
                            status=status,
                        )
                    )

            # Traverse child values
            for value in node.values():
                _traverse(value)
        elif isinstance(node, list):
            for item in node:
                _traverse(item)

    _traverse(data)
    return results


def resolve_opencode_binary(opencode_bin: str = "opencode") -> Optional[str]:
    """Find the absolute path to the opencode binary or batch script."""
    # Check if the exact name/path works
    resolved = shutil.which(opencode_bin)
    if resolved:
        return resolved

    # On Windows, try common executable extensions explicitly if not found
    if sys.platform == "win32":
        for ext in [".cmd", ".bat", ".exe", ".ps1"]:
            candidate = f"{opencode_bin}{ext}"
            resolved = shutil.which(candidate)
            if resolved:
                return resolved

    return None


_OPENCODE_VERSION_CACHE: Dict[str, Optional[Tuple[int, int, int]]] = {}


def get_opencode_version(resolved_bin: str) -> Optional[Tuple[int, int, int]]:
    """Determine the semantic version tuple of the opencode CLI."""
    if resolved_bin in _OPENCODE_VERSION_CACHE:
        return _OPENCODE_VERSION_CACHE[resolved_bin]

    use_shell = sys.platform == "win32"
    version_tuple: Optional[Tuple[int, int, int]] = None
    try:
        result = subprocess.run(
            [resolved_bin, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=use_shell,
            check=False,
        )
        if result.returncode == 0:
            match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", result.stdout)
            if match:
                major = int(match.group(1))
                minor = int(match.group(2))
                patch = int(match.group(3)) if match.group(3) else 0
                version_tuple = (major, minor, patch)
    except Exception:
        pass

    _OPENCODE_VERSION_CACHE[resolved_bin] = version_tuple
    return version_tuple


def build_export_commands(
    resolved_bin: str,
    session_id: str,
) -> Tuple[List[str], Optional[List[str]]]:
    """Build primary and fallback CLI export command args based on opencode version.

    OpenCode v2.x.x uses `opencode session export <session_id>`.
    OpenCode v1.x.x and earlier used `opencode export <session_id>`.
    """
    version = get_opencode_version(resolved_bin)
    if version and version[0] >= 2:
        primary = [resolved_bin, "session", "export", session_id]
        fallback = [resolved_bin, "export", session_id]
    elif version and version[0] < 2:
        primary = [resolved_bin, "export", session_id]
        fallback = [resolved_bin, "session", "export", session_id]
    else:
        # Unknown/unparseable version: prefer v2 subcommand with v1 fallback
        primary = [resolved_bin, "session", "export", session_id]
        fallback = [resolved_bin, "export", session_id]

    return primary, fallback


def export_task_session(
    session_id: str,
    output_file: Path,
    opencode_bin: str = "opencode",
    overwrite: bool = False,
) -> bool:
    """Run `opencode session export <id>` (v2+) or `opencode export <id>` (v1) and save stdout to output_file."""
    if output_file.exists() and not overwrite:
        print(f"  [SKIPPED] File already exists: {output_file.name}")
        return True

    resolved_bin = resolve_opencode_binary(opencode_bin)
    if not resolved_bin:
        print(
            f"  [ERROR] Command not found: '{opencode_bin}'. "
            f"Please ensure opencode is installed and in your PATH, "
            f"or pass --opencode-bin /path/to/opencode",
            file=sys.stderr,
        )
        return False

    primary_cmd, fallback_cmd = build_export_commands(resolved_bin, session_id)
    use_shell = sys.platform == "win32"

    def _execute(cmd: List[str]) -> Tuple[int, str, str]:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=use_shell,
            check=False,
        )
        return res.returncode, res.stdout, res.stderr

    executed_cmd = primary_cmd
    try:
        returncode, stdout, stderr = _execute(primary_cmd)
        if returncode != 0 and fallback_cmd:
            alt_code, alt_stdout, alt_stderr = _execute(fallback_cmd)
            if alt_code == 0:
                executed_cmd = fallback_cmd
                returncode, stdout, stderr = alt_code, alt_stdout, alt_stderr
    except Exception as err:
        print(
            f"  [ERROR] Failed to execute '{' '.join(primary_cmd)}': {err}",
            file=sys.stderr,
        )
        return False

    if returncode != 0:
        err_msg = stderr.strip() or stdout.strip()
        print(
            f"  [ERROR] opencode export failed (exit code {returncode}): {err_msg}",
            file=sys.stderr,
        )
        return False

    content = stdout
    if not content.strip():
        print(
            f"  [WARNING] '{' '.join(executed_cmd)}' returned empty output.",
            file=sys.stderr,
        )
        return False

    output_file.write_text(content, encoding="utf-8")
    print(f"  [SAVED] -> {output_file}")
    return True



def export_all_tasks(
    session_json_path: Path,
    output_dir: Path,
    opencode_bin: str = "opencode",
    dry_run: bool = False,
    overwrite: bool = False,
) -> Tuple[List[Path], int, int]:
    """Discover task sessions and export them all into output_dir.

    Returns:
        (exported_file_paths, success_count, fail_count)
    """
    with open(session_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    task_calls = find_task_calls(data)
    print(
        f"Found {len(task_calls)} unique task session(s) in {session_json_path.name}:"
    )

    if not task_calls:
        print("No task tool calls found.")
        return ([], 0, 0)

    for idx, task in enumerate(task_calls, 1):
        desc = f" - {task.title}" if task.title else ""
        print(f"  {idx}. {task.session_id}{desc}")

    if dry_run:
        print("\nDry run completed. No files were exported.")
        return ([], len(task_calls), 0)

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nExporting to directory: {output_dir.resolve()}")

    exported_files: List[Path] = []
    success_count = 0
    fail_count = 0

    for idx, task in enumerate(task_calls, 1):
        print(f"\n[{idx}/{len(task_calls)}] Exporting session: {task.session_id}")
        target_file = output_dir / f"{task.session_id}.json"
        ok = export_task_session(
            session_id=task.session_id,
            output_file=target_file,
            opencode_bin=opencode_bin,
            overwrite=overwrite,
        )
        if ok:
            success_count += 1
            if target_file.exists():
                exported_files.append(target_file)
        else:
            fail_count += 1

    print("\n" + "=" * 40)
    print(f"Summary: {success_count} succeeded, {fail_count} failed.")
    print(f"Output directory: {output_dir.resolve()}")

    return (exported_files, success_count, fail_count)


@app.command()
def main(
    session_json: Path = typer.Argument(
        ...,
        help="Path to the source OpenCode session JSON export file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Directory where exported task session JSON files will be saved. Defaults to 'extractions/<session_json_stem>_tasks'.",
    ),
    opencode_bin: str = typer.Option(
        "opencode",
        "--opencode-bin",
        help="OpenCode executable name or path (default: 'opencode').",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Discover and print task session IDs without calling opencode export.",
    ),
    overwrite: bool = typer.Option(
        False,
        "-f",
        "--force",
        "--overwrite",
        help="Overwrite existing JSON files in the output directory.",
    ),
) -> None:
    if output_dir:
        if output_dir.resolve() == DEFAULT_EXTRACTIONS_DIR.resolve():
            target_output_dir = DEFAULT_EXTRACTIONS_DIR / f"{session_json.stem}_tasks"
        else:
            target_output_dir = output_dir
    else:
        target_output_dir = DEFAULT_EXTRACTIONS_DIR / f"{session_json.stem}_tasks"
    _, success, fail = export_all_tasks(
        session_json_path=session_json,
        output_dir=target_output_dir,
        opencode_bin=opencode_bin,
        dry_run=dry_run,
        overwrite=overwrite,
    )
    if fail > 0:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

