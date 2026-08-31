#!/usr/bin/env python3
"""Retroactive Markdown Apply-Patch Trimming Utility.

This script parses existing Markdown review transcripts (such as those generated
in subtasks/ directories), identifies `apply_patch` tool invocations, and truncates
large patch input payloads according to the trim rule in `trimmer.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple
import typer

from trimmer import _truncate_data

app = typer.Typer(
    help="Retroactively trim apply_patch tool inputs in existing Markdown transcript files."
)

TOOL_EXECUTED_REGEX = re.compile(
    r"^\s*[\*\-]\s*\*\*Tool Executed:\*\*\s*`([^`]+)`\s*$"
)
TOOL_INPUT_LINE_REGEX = re.compile(
    r"^(\s*[\*\-]\s*\*\*Input:\*\*\s*`)(.*)(`\s*)$"
)


def trim_apply_patch_in_text(
    content: str,
    max_input_length: int = 500,
    target_tools: Optional[List[str]] = None,
) -> Tuple[str, int]:
    """Parse markdown lines, finding tool calls and truncating their input payloads.

    Returns:
        Tuple[str, int]: (updated_content, number_of_patches_modified)
    """
    # Detect line ending style
    crlf = "\r\n" in content
    newline = "\r\n" if crlf else "\n"

    lines = content.splitlines()
    modified_count = 0
    in_tool_block = False

    for i in range(len(lines)):
        line = lines[i]

        # Check if line indicates tool execution
        tool_match = TOOL_EXECUTED_REGEX.match(line)
        if tool_match:
            tool_name = tool_match.group(1)
            if target_tools is None or tool_name in target_tools:
                in_tool_block = True
            else:
                in_tool_block = False
            continue

        # If we are immediately after a matching tool execution line
        if in_tool_block:
            input_match = TOOL_INPUT_LINE_REGEX.match(line)
            if input_match:
                prefix = input_match.group(1)
                raw_payload = input_match.group(2)
                suffix = input_match.group(3)

                # Skip if already truncated and within limit
                if "[TRUNCATED FOR REVIEW]" in raw_payload and len(raw_payload) <= max_input_length + 30:
                    in_tool_block = False
                    continue

                # Attempt to parse raw payload as JSON
                try:
                    parsed_json = json.loads(raw_payload)
                    cleaned = _truncate_data(parsed_json, max_len=max_input_length)
                    inp_str = json.dumps(cleaned, ensure_ascii=False)
                except Exception:
                    # Fallback string truncation if not strict JSON
                    if len(raw_payload) > max_input_length:
                        inp_str = raw_payload[:max_input_length] + "... [TRUNCATED FOR REVIEW]"
                    else:
                        inp_str = raw_payload

                if len(inp_str) > max_input_length:
                    inp_str = inp_str[:max_input_length] + "... [TRUNCATED FOR REVIEW]"

                # Escape backticks to preserve markdown code spans
                inp_str = inp_str.replace("`", "'")

                new_line = f"{prefix}{inp_str}{suffix}"
                if new_line != line:
                    lines[i] = new_line
                    modified_count += 1

                in_tool_block = False
                continue

            # If this line is not the input line (e.g. unexpected header or empty line), reset flag
            if line.strip().startswith("## Turn") or line.strip().startswith("* **Tool Executed:"):
                # Another turn or tool started
                t_match = TOOL_EXECUTED_REGEX.match(line)
                in_tool_block = t_match is not None and (target_tools is None or t_match.group(1) in target_tools)

    updated_content = newline.join(lines)
    if content.endswith(newline) or content.endswith("\n"):
        updated_content += newline

    return updated_content, modified_count


def process_markdown_file(
    file_path: Path,
    max_input_length: int = 500,
    dry_run: bool = False,
) -> Tuple[bool, int, int, int]:
    """Processes a single markdown file and applies trimming.

    Returns:
        Tuple[bool, int, int, int]: (is_modified, patch_count, old_byte_size, new_byte_size)
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as err:
        typer.secho(f"  [ERROR] Could not read {file_path}: {err}", fg=typer.colors.RED, err=True)
        return False, 0, 0, 0

    old_size = len(content.encode("utf-8"))
    updated_content, patch_count = trim_apply_patch_in_text(
        content=content,
        max_input_length=max_input_length,
    )

    if patch_count == 0:
        return False, 0, old_size, old_size

    new_size = len(updated_content.encode("utf-8"))

    if not dry_run:
        file_path.write_text(updated_content, encoding="utf-8")

    return True, patch_count, old_size, new_size


@app.command()
def main(
    target_path: Path = typer.Argument(
        ...,
        help="Path to a markdown file or directory containing markdown files.",
        exists=True,
        readable=True,
    ),
    max_input_length: int = typer.Option(
        500,
        "--max-input-length",
        help="Maximum character length for patch input before truncation.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Simulate the trimming without writing changes to disk.",
    ),
    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        "-r",
        help="Search directory recursively for .md files.",
    ),
) -> None:
    """Trim apply_patch inputs in one or more Markdown session transcripts."""
    files_to_process: List[Path] = []

    if target_path.is_file():
        if target_path.suffix.lower() == ".md":
            files_to_process.append(target_path)
        else:
            typer.secho(f"Target file {target_path} is not a Markdown (.md) file.", fg=typer.colors.YELLOW)
            return
    elif target_path.is_dir():
        pattern = "**/*.md" if recursive else "*.md"
        files_to_process = sorted(list(target_path.glob(pattern)))

    if not files_to_process:
        typer.secho(f"No Markdown files found at {target_path}.", fg=typer.colors.YELLOW)
        return

    mode_label = "[DRY RUN] " if dry_run else ""
    typer.secho("=" * 60, fg=typer.colors.CYAN)
    typer.secho(f"{mode_label}Apply-Patch Markdown Trimmer", fg=typer.colors.CYAN, bold=True)
    typer.secho(f"  Target: {target_path.resolve()}", fg=typer.colors.WHITE)
    typer.secho(f"  Files Found: {len(files_to_process)}", fg=typer.colors.WHITE)
    typer.secho(f"  Max Input Length: {max_input_length}", fg=typer.colors.WHITE)
    typer.secho("=" * 60, fg=typer.colors.CYAN)

    modified_files = 0
    total_patches = 0
    total_old_bytes = 0
    total_new_bytes = 0

    for idx, md_file in enumerate(files_to_process, 1):
        is_mod, patch_count, old_bytes, new_bytes = process_markdown_file(
            file_path=md_file,
            max_input_length=max_input_length,
            dry_run=dry_run,
        )

        total_old_bytes += old_bytes
        total_new_bytes += new_bytes

        if is_mod:
            modified_files += 1
            total_patches += patch_count
            bytes_saved = old_bytes - new_bytes
            action_tag = "[WOULD TRIM]" if dry_run else "[TRIMMED]"
            typer.secho(
                f"  [{idx}/{len(files_to_process)}] {action_tag} {md_file.name}: "
                f"{patch_count} patch(es), saved {bytes_saved:,} bytes ({old_bytes:,} -> {new_bytes:,} B)",
                fg=typer.colors.GREEN,
            )
        else:
            typer.secho(
                f"  [{idx}/{len(files_to_process)}] [UNCHANGED] {md_file.name} (no oversized apply_patch)",
                fg=typer.colors.WHITE,
            )

    bytes_saved_total = total_old_bytes - total_new_bytes
    typer.secho("\n" + "=" * 60, fg=typer.colors.CYAN)
    typer.secho(f"{mode_label}Trimming Summary:", fg=typer.colors.CYAN, bold=True)
    typer.secho(f"  Files Processed: {len(files_to_process)}", fg=typer.colors.WHITE)
    typer.secho(f"  Files Modified:  {modified_files}", fg=typer.colors.GREEN if modified_files > 0 else typer.colors.WHITE)
    typer.secho(f"  Patches Trimmed: {total_patches}", fg=typer.colors.GREEN if total_patches > 0 else typer.colors.WHITE)
    typer.secho(f"  Bytes Saved:     {bytes_saved_total:,} bytes", fg=typer.colors.GREEN if bytes_saved_total > 0 else typer.colors.WHITE)
    typer.secho("=" * 60, fg=typer.colors.CYAN)


if __name__ == "__main__":
    app()
