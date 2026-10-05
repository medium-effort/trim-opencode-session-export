#!/usr/bin/env python3
"""OpenCode Session Processing & Bundling Orchestrator.

This script takes an exported OpenCode session JSON file and:
1. Creates a target folder in extractions/ named after the session JSON (or user-specified).
2. Generates a compact Markdown review transcript of the main session using `trimmer.py`.
3. Discovers all subtask sessions and exports them via `export_task_sessions.py` into a temporary folder.
4. Trims each subtask session into a Markdown transcript inside a `subtasks/` subdirectory.
5. Cleans up the temporary export folder.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Optional
import typer

from export_task_sessions import export_all_tasks, find_task_calls
from trimmer import generate_review_transcript

DEFAULT_EXTRACTIONS_DIR = Path(__file__).resolve().parent / "extractions"


def sanitize_name(name: str, max_length: int = 100, replace_spaces: bool = False) -> str:
    """Sanitize title for filesystem naming, removing invalid characters."""
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', name)
    if replace_spaces:
        cleaned = re.sub(r'[\s_]+', '_', cleaned)
    else:
        cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip(' ._')
    return cleaned[:max_length] if cleaned else "untitled"


app = typer.Typer(
    help="Process an exported OpenCode session: trim main session and export & trim all subtasks."
)


@app.command()
def main(
    session_json: Path = typer.Argument(
        ...,
        help="Path to the exported OpenCode session JSON file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Target output directory (defaults to extractions/<session_json_stem>).",
    ),
    opencode_bin: str = typer.Option(
        "opencode",
        "--opencode-bin",
        help="OpenCode executable name or path (default: 'opencode').",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Discover and display main session and subtask targets without writing or exporting.",
    ),
    overwrite: bool = typer.Option(
        False,
        "-f",
        "--force",
        "--overwrite",
        help="Overwrite existing markdown files in output directory.",
    ),
    keep_temp: bool = typer.Option(
        False,
        "--keep-temp",
        help="Retain raw exported subtask JSON files instead of deleting temporary directory.",
    ),
    temp_dir: Optional[Path] = typer.Option(
        None,
        "--temp-dir",
        help="Custom directory to store intermediate subtask JSON files.",
    ),
    max_output_length: int = typer.Option(
        500,
        "--max-output-length",
        help="Maximum character length for tool output previews before truncation.",
    ),
    max_input_length: int = typer.Option(
        500,
        "--max-input-length",
        help="Maximum character length for tool input payloads before truncation.",
    ),
    truncate_apply_patch: bool = typer.Option(
        True,
        "--truncate-apply-patch/--no-truncate-apply-patch",
        envvar="TRUNCATE_APPLY_PATCH_INPUT",
        help="Whether to truncate apply_patch tool inputs (defaults to True or TRUNCATE_APPLY_PATCH_INPUT env var).",
    ),
) -> None:
    """Process an exported OpenCode session transcript into a bundled review structure."""
    try:
        with open(session_json, "r", encoding="utf-8") as f:
            session_data = json.load(f)
    except json.JSONDecodeError as err:
        typer.secho(f"Error: Invalid JSON in {session_json}: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as err:
        typer.secho(f"Error reading {session_json}: {err}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    info = session_data.get("info") or {}
    title = info.get("title") or session_json.stem
    model_id = (info.get("model") or {}).get("id", "unknown") if isinstance(info.get("model"), dict) else (info.get("model") or "unknown")
    cost = info.get("cost") or 0.0

    task_calls = find_task_calls(session_data)

    if output_dir:
        if output_dir.resolve() == DEFAULT_EXTRACTIONS_DIR.resolve():
            folder_name = sanitize_name(title, replace_spaces=False)
            target_root = DEFAULT_EXTRACTIONS_DIR / folder_name
        else:
            target_root = output_dir
    else:
        folder_name = sanitize_name(title, replace_spaces=False)
        target_root = DEFAULT_EXTRACTIONS_DIR / folder_name

    pad_width = max(2, len(str(len(task_calls))))

    typer.secho("=" * 60, fg=typer.colors.CYAN)
    typer.secho(f"OpenCode Session Processor: {session_json.name}", fg=typer.colors.CYAN, bold=True)
    typer.secho(f"  Title: {title}", fg=typer.colors.WHITE)
    typer.secho(f"  Model: {model_id} | Cost: ${cost:.4f}", fg=typer.colors.WHITE)
    typer.secho(f"  Discovered Subtasks: {len(task_calls)}", fg=typer.colors.WHITE)
    typer.secho(f"  Target Directory: {target_root.resolve()}", fg=typer.colors.WHITE)
    typer.secho("=" * 60, fg=typer.colors.CYAN)

    if dry_run:
        typer.secho("\n[DRY RUN] Planned Actions:", fg=typer.colors.YELLOW, bold=True)
        typer.secho(f"  1. Main review transcript -> {target_root / f'{session_json.stem}.md'}")
        typer.secho(f"  2. Subtasks folder -> {target_root / 'subtasks'}")
        for idx, task in enumerate(task_calls, 1):
            title_part = sanitize_name(task.title, max_length=60, replace_spaces=True) if task.title else task.session_id
            subtask_md_name = f"{idx:0{pad_width}d}_{title_part}.md"
            typer.secho(f"     - [{idx}/{len(task_calls)}] {task.session_id} -> {target_root / 'subtasks' / subtask_md_name}")
        typer.secho("\nDry run completed. No files were created.", fg=typer.colors.YELLOW)
        return

    # Step 1: Create folders
    target_root.mkdir(parents=True, exist_ok=True)
    subtasks_dir = target_root / "subtasks"
    subtasks_dir.mkdir(parents=True, exist_ok=True)

    # Step 2: Trim main session
    main_md_path = target_root / f"{session_json.stem}.md"
    if main_md_path.exists() and not overwrite:
        typer.secho(f"[SKIPPED] Main transcript already exists: {main_md_path.name}", fg=typer.colors.YELLOW)
    else:
        typer.secho(f"\n[1/3] Trimming main session -> {main_md_path.name}...", fg=typer.colors.GREEN)
        generate_review_transcript(
            session_json,
            main_md_path,
            max_output_length=max_output_length,
            max_input_length=max_input_length,
            truncate_apply_patch=truncate_apply_patch,
        )
        typer.secho(f"  [SAVED] Main transcript: {main_md_path.resolve()}", fg=typer.colors.GREEN)

    # Step 3: Export task sessions to temporary folder
    typer.secho(f"\n[2/3] Exporting {len(task_calls)} subtask session(s)...", fg=typer.colors.GREEN)

    if not task_calls:
        typer.secho("  No subtasks found in this session.", fg=typer.colors.WHITE)
        typer.secho("\n" + "=" * 60, fg=typer.colors.CYAN)
        typer.secho(f"Complete! Main transcript available at: {main_md_path.resolve()}", fg=typer.colors.GREEN, bold=True)
        return

    # Handle temporary directory lifecycle
    cleanup_temp = not keep_temp
    if temp_dir:
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_folder_path = temp_dir
        temp_context = None
    else:
        temp_context = tempfile.TemporaryDirectory(prefix="opencode_tasks_")
        temp_folder_path = Path(temp_context.name)

    exported_jsons: List[Path] = []
    trimmed_subtasks: List[Path] = []
    failed_subtasks: List[str] = []

    try:
        exported_jsons, success_count, fail_count = export_all_tasks(
            session_json_path=session_json,
            output_dir=temp_folder_path,
            opencode_bin=opencode_bin,
            dry_run=False,
            overwrite=True,
        )

        # Step 4: Trim each subtask session into subtasks/
        typer.secho(f"\n[3/3] Trimming {len(task_calls)} subtask session(s) into subtasks/...", fg=typer.colors.GREEN)

        for idx, task in enumerate(task_calls, 1):
            task_json = temp_folder_path / f"{task.session_id}.json"
            title_part = sanitize_name(task.title, max_length=60, replace_spaces=True) if task.title else task.session_id
            subtask_md_name = f"{idx:0{pad_width}d}_{title_part}.md"
            subtask_md_path = subtasks_dir / subtask_md_name

            if not task_json.exists():
                typer.secho(f"  [{idx}/{len(task_calls)}] [MISSING] {task.session_id} not exported", fg=typer.colors.RED, err=True)
                failed_subtasks.append(task.session_id)
                continue

            if subtask_md_path.exists() and not overwrite:
                typer.secho(f"  [{idx}/{len(task_calls)}] [SKIPPED] {subtask_md_name} exists", fg=typer.colors.YELLOW)
                trimmed_subtasks.append(subtask_md_path)
                continue

            try:
                generate_review_transcript(
                    task_json,
                    subtask_md_path,
                    max_output_length=max_output_length,
                    max_input_length=max_input_length,
                    truncate_apply_patch=truncate_apply_patch,
                )
                typer.secho(f"  [{idx}/{len(task_calls)}] [TRIMMED] -> subtasks/{subtask_md_name}", fg=typer.colors.GREEN)
                trimmed_subtasks.append(subtask_md_path)
            except Exception as err:
                typer.secho(f"  [{idx}/{len(task_calls)}] [ERROR] Failed to trim {subtask_md_name}: {err}", fg=typer.colors.RED, err=True)
                failed_subtasks.append(task.session_id)

    finally:
        if cleanup_temp:
            if temp_context:
                temp_context.cleanup()
            elif temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            typer.secho(f"\n[INFO] Temporary JSON files retained at: {temp_folder_path.resolve()}", fg=typer.colors.BLUE)

    # Step 5: Summary Report
    typer.secho("\n" + "=" * 60, fg=typer.colors.CYAN)
    typer.secho("Processing Complete Summary:", fg=typer.colors.CYAN, bold=True)
    typer.secho(f"  Output Directory: {target_root.resolve()}", fg=typer.colors.WHITE)
    typer.secho(f"  Main Transcript:  {main_md_path.name}", fg=typer.colors.GREEN)
    typer.secho(f"  Subtasks Trimmed: {len(trimmed_subtasks)} / {len(task_calls)}", fg=typer.colors.GREEN)
    if failed_subtasks:
        typer.secho(f"  Failed / Missing Subtasks: {len(failed_subtasks)} ({', '.join(failed_subtasks)})", fg=typer.colors.RED)
    typer.secho("=" * 60, fg=typer.colors.CYAN)


if __name__ == "__main__":
    app()
