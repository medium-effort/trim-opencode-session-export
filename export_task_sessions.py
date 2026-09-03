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
    r'<task\b[^>]*?\bid=["\']([^"\']+)["\']', re.IGNORECASE
)


class TaskCallInfo:
    """Stores information about a discovered task tool call."""

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
    """Extract session ID from a tool call dictionary."""
    state = part.get("state") or {}
    metadata = state.get("metadata") or {}

    # 1. Check state.metadata.sessionId
    session_id = metadata.get("sessionId")
    if session_id and isinstance(session_id, str) and session_id.strip():
        return session_id.strip()

    # 2. Check XML tag in state.output (e.g. <task id="ses_..." ...>)
    output = state.get("output")
    if output and isinstance(output, str):
        match = TASK_TAG_PATTERN.search(output)
        if match:
            return match.group(1).strip()

    # 3. Check top-level metadata or fields if present
    part_meta = part.get("metadata") or {}
    if "sessionId" in part_meta and isinstance(part_meta["sessionId"], str):
        return part_meta["sessionId"].strip()

    return None


def find_task_calls(data: Any) -> List[TaskCallInfo]:
    """Recursively search parsed JSON structure for task tool calls."""
    results: List[TaskCallInfo] = []
    seen_ids = set()

    def _traverse(node: Any) -> None:
        if isinstance(node, dict):
            # Check if this node is a task tool call
            if node.get("type") == "tool" and node.get("tool") == "task":
                session_id = extract_session_id_from_task_call(node)
                if session_id and session_id not in seen_ids:
                    seen_ids.add(session_id)
                    state = node.get("state") or {}
                    title = (
                        state.get("title")
                        or state.get("input", {}).get("description")
                        or ""
                    )
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


def export_task_session(
    session_id: str,
    output_file: Path,
    opencode_bin: str = "opencode",
    overwrite: bool = False,
) -> bool:
    """Run `opencode export <session_id>` and save stdout to output_file."""
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

    cmd = [resolved_bin, "export", session_id]
    use_shell = sys.platform == "win32"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=use_shell,
            check=False,
        )
    except Exception as err:
        print(
            f"  [ERROR] Failed to execute '{' '.join(cmd)}': {err}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        err_msg = result.stderr.strip() or result.stdout.strip()
        print(
            f"  [ERROR] opencode export failed (exit code {result.returncode}): {err_msg}",
            file=sys.stderr,
        )
        return False

    content = result.stdout
    if not content.strip():
        print(
            f"  [WARNING] 'opencode export {session_id}' returned empty output.",
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

