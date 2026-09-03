---
description: Process an exported OpenCode session JSON file into a compact Markdown review transcript and bundle its subtasks.
---

# Process OpenCode Session Transcript

This workflow orchestrates the end-to-end processing of an exported OpenCode session transcript into a bundled, readable review log. It trims lengthy tool inputs/outputs in the main session, detects all dispatched subtasks, exports them via the OpenCode CLI, and trims each subtask into a dedicated Markdown file under `subtasks/`.

## Prerequisites

- **Python 3.10+** with `typer` installed.
- **OpenCode CLI** (`opencode`) installed and accessible in your system `PATH` (needed to export discovered subtask sessions).
- The target session file must be in the standard OpenCode CLI export format (`info` and `messages` keys).

---

> [!IMPORTANT]
> **Context Window & Token Efficiency Safeguards**:
> 1. **Never read raw session JSON files**: These exports can be tens of thousands of lines long and will exhaust your context window. Schema validation and parsing are handled entirely by `process_session.py`.
> 2. **Do NOT read generated Markdown files into context**: Never use `view_file` to read the resulting `.md` transcripts simply to verify them. Verify success strictly from the CLI script's exit code (`0`) and stdout summary block. Only inspect `.md` transcripts if the user explicitly requests conversation analysis or a content summary.

---

## Workflow Steps

### Step 1: Zero-Token Format Check via Dry-Run
Do **NOT** open or read the JSON file. Instead, run `process_session.py` with the `--dry-run` flag to inspect detected metadata and discovered subtasks safely via terminal output:

```bash
python process_session.py <path/to/session.json> --dry-run
```

**Evaluate the dry-run output:**
- **Valid CLI Export Format**:
  - `Title`: Shows the actual conversation title (e.g., `"Markdown notes web app brief"`).
  - `Model`: Shows the model ID (e.g., `"x-preview-f-free"`).
  - `Discovered Subtasks`: Lists count of subtasks found.
  - -> **Proceed to Step 2.**
- **SQLite Database Dump Format (Unprocessable as-is)**:
  - `Title`: Defaults to the raw filename stem.
  - `Model`: Shows `unknown`.
  - `Discovered Subtasks`: Shows `0` (even if child sessions exist).
  - -> **Action**: Do not proceed. Re-export the session using the OpenCode CLI first:
    ```bash
    opencode export <session_id> > session_<session_id>.json
    ```
    (See [SESSION_FORMAT_COMPARISON.md](../useful_info/SESSION_FORMAT_COMPARISON.md) for full schema details).

### Step 2: Execute Session Processing
Run the processor on the target JSON file:

```bash
python process_session.py <path/to/session.json>
```

#### Useful CLI Flags:
- `--output-dir <path>` (`-o`): Specify a custom target directory (defaults to `extractions/<session_stem>`).
- `--overwrite` (`-f`): Overwrite existing markdown files if previously generated.
- `--max-output-length <int>`: Max characters for tool outputs before truncation (default: 500).
- `--max-input-length <int>`: Max characters for tool input payloads before truncation (default: 500).
- `--no-truncate-apply-patch`: Preserve full patch diff payloads for `apply_patch` tool calls.
- `--keep-temp`: Keep raw exported subtask JSON files instead of cleaning them up.

### Step 3: Zero-Token Verification & Report
Do **NOT** read the generated Markdown file into context.
1. Confirm the process exited with code `0` and check the summary printed to stdout:
   - Output directory location
   - Main transcript filename
   - Subtasks trimmed count
2. Report completion directly to the user with clickable links to the output folder and `.md` file.
