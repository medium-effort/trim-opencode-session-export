from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional
import typer

DEFAULT_EXTRACTIONS_DIR = Path(__file__).resolve().parent / "extractions"

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

    info = data.get("info") or {}
    session_id = info.get("id") or raw_path.stem
    title = info.get("title") or "Session"
    model_id = (info.get("model") or {}).get("id", "unknown") if isinstance(info.get("model"), dict) else (info.get("model") or "unknown")
    cost = info.get("cost", 0) or 0.0

    lines = []
    lines.append(f"# Evaluation Log: {title}")
    lines.append(
        f"**Session ID:** `{session_id}` | **Target Model:** {model_id} | **Total Cost:** ${cost:.4f}\n---"
    )

    turn_idx = 0
    for msg in data.get("messages", []):
        # 1. Determine role: v1 uses msg["info"]["role"], v2 uses msg["type"]
        role = msg.get("info", {}).get("role")
        if not role:
            role = msg.get("type", "unknown")
        role = str(role).upper()

        # 2. Extract parts: v1 uses msg["parts"], v2 uses msg["content"], msg["text"], or msg["summary"]
        parts = []
        if isinstance(msg.get("parts"), list) and msg["parts"]:
            parts = msg["parts"]
        elif isinstance(msg.get("content"), list) and msg["content"]:
            parts = msg["content"]
        elif msg.get("text"):
            parts = [{"type": "text", "text": msg["text"]}]
        elif msg.get("summary"):
            parts = [{"type": "summary", "text": msg["summary"]}]

        # Skip events that have no renderable message or parts (e.g. idle, model-switched, agent-switched)
        if not parts:
            continue

        turn_idx += 1
        lines.append(f"\n## Turn {turn_idx} [{role}]")

        for part in parts:
            p_type = part.get("type")

            # 1. Capture model thoughts / reasoning
            if p_type == "reasoning" and part.get("text"):
                lines.append(f"\n> **Model Thought/Plan:**\n> {part['text']}\n")

            # 2. Capture regular conversational text or compaction summary
            elif p_type in ("text", "summary") and part.get("text"):
                label = "Compaction Summary" if p_type == "summary" else "Message"
                lines.append(f"\n**{label}:**\n{part['text']}\n")

            # 3. Capture tool invocations & outputs
            elif p_type == "tool":
                tool_name = part.get("tool") or part.get("name")
                state = part.get("state", {})
                inp = state.get("input", {})

                # In v1: output is in state["output"]
                # In v2: output can be in state["output"] or state["content"]
                raw_out = state.get("output")
                if raw_out is None and "content" in state:
                    c = state.get("content")
                    if isinstance(c, list):
                        raw_out = "\n".join(
                            b.get("text", "") for b in c if isinstance(b, dict) and b.get("text")
                        )
                    elif isinstance(c, str):
                        raw_out = c
                    else:
                        raw_out = str(c) if c else ""
                out = str(raw_out or "")

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

                # Truncate massive tool outputs (like file dumps) to keep review compact.
                # Preserve task and subagent outputs intact so that XML tags and session IDs are not clipped.
                if tool_name not in ("task", "subagent") and len(out) > max_output_length:
                    out = out[:max_output_length] + "... [TRUNCATED FOR REVIEW]"

                lines.append(f"\n* **Tool Executed:** `{tool_name}`")
                lines.append(f"  * **Input:** `{inp_str}`")
                if state.get("status"):
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
        help="Path to write markdown review transcript. Defaults to extractions/<raw_json_stem>.md.",
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
    if output_md_path:
        if output_md_path.is_dir() or output_md_path.resolve() == DEFAULT_EXTRACTIONS_DIR.resolve():
            target_out = output_md_path / f"{raw_json_path.stem}.md"
        else:
            target_out = output_md_path
    else:
        target_out = DEFAULT_EXTRACTIONS_DIR / f"{raw_json_path.stem}.md"
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