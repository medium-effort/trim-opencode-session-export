from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional
import typer

app = typer.Typer(
    help="Trim OpenCode session JSON export into a compact Markdown review transcript."
)


def _is_env_enabled(var_name: str, default: bool = True) -> bool:
    """Check if a boolean environment variable is enabled."""
    val = os.environ.get(var_name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _truncate_data(data: Any, max_len: int = 500) -> Any:
    """Recursively truncate strings inside lists or dictionaries."""
    if isinstance(data, str):
        if len(data) > max_len:
            return data[:max_len] + "... [TRUNCATED FOR REVIEW]"
        return data
    elif isinstance(data, dict):
        return {k: _truncate_data(v, max_len) for k, v in data.items()}
    elif isinstance(data, list):
        return [_truncate_data(item, max_len) for item in data]
    return data


def generate_review_transcript(
    raw_json_path: str | Path,
    output_md_path: str | Path,
    max_output_length: int = 500,
    max_input_length: int = 500,
    truncate_apply_patch: Optional[bool] = None,
) -> Path:
    raw_path = Path(raw_json_path)
    out_path = Path(output_md_path)

    if truncate_apply_patch is None:
        truncate_apply_patch = _is_env_enabled("TRUNCATE_APPLY_PATCH_INPUT", default=True)

    with open(raw_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    lines = []
    lines.append(
        f"# Evaluation Log: {data.get('info', {}).get('title', 'Session')}"
    )
    lines.append(
        f"**Target Model:** {data.get('info', {}).get('model', {}).get('id')} | **Total Cost:** ${data.get('info', {}).get('cost', 0):.4f}\n---"
    )

    for i, msg in enumerate(data.get("messages", [])):
        role = msg.get("info", {}).get("role", "unknown").upper()
        lines.append(f"\n## Turn {i+1} [{role}]")

        for part in msg.get("parts", []):
            p_type = part.get("type")

            # 1. Capture model thoughts
            if p_type == "reasoning" and part.get("text"):
                lines.append(f"\n> **Model Thought/Plan:**\n> {part['text']}\n")

            # 2. Capture regular conversational text
            elif p_type == "text" and part.get("text"):
                lines.append(f"\n**Message:**\n{part['text']}\n")

            # 3. Capture tool invocations & outputs
            elif p_type == "tool":
                tool_name = part.get("tool")
                state = part.get("state", {})
                inp = state.get("input", {})
                out = str(state.get("output", ""))

                # Truncate tool input payloads (e.g. task prompts, apply_patch diffs, file writes)
                should_truncate_input = True
                if tool_name == "apply_patch" and truncate_apply_patch is False:
                    should_truncate_input = False

                if should_truncate_input:
                    inp_clean = _truncate_data(inp, max_len=max_input_length)
                    inp_str = json.dumps(inp_clean, ensure_ascii=False)
                    if len(inp_str) > max_input_length:
                        inp_str = inp_str[:max_input_length] + "... [TRUNCATED FOR REVIEW]"
                else:
                    inp_str = json.dumps(inp, ensure_ascii=False)

                # Escape backticks so inline markdown code blocks don't break
                inp_str = inp_str.replace("`", "'")

                # Truncate massive tool outputs (like file dumps) to keep review compact
                if tool_name != "task" and len(out) > max_output_length:
                    out = out[:max_output_length] + "... [TRUNCATED FOR REVIEW]"

                lines.append(f"\n* **Tool Executed:** `{tool_name}`")
                lines.append(f"  * **Input:** `{inp_str}`")
                lines.append(f"  * **Status:** `{state.get('status')}`")
                lines.append(f"  * **Result Preview:**\n```text\n{out}\n```")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return out_path


@app.command()
def main(
    raw_json_path: Path = typer.Argument(
        ...,
        help="Path to the raw session JSON file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    output_md_path: Optional[Path] = typer.Argument(
        None,
        help="Path to write markdown review transcript. Defaults to <raw_json_stem>.md.",
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
    target_out = output_md_path or Path(f"{raw_json_path.stem}.md")
    result = generate_review_transcript(
        raw_json_path,
        target_out,
        max_output_length=max_output_length,
        max_input_length=max_input_length,
        truncate_apply_patch=truncate_apply_patch,
    )
    typer.echo(f"Generated review transcript: {result}")


if __name__ == "__main__":
    app()