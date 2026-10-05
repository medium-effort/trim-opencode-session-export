---
name: trim-opencode-session
description: >-
  Process, trim, and bundle exported OpenCode session transcripts into compact
  Markdown review logs, and automatically discover, export, and trim all subagent
  task sessions. Use whenever invoked via `/trim-opencode-session`, or when the user
  asks to process, trim, summarize, or export an OpenCode session JSON file or
  session ID (ses_...).
---

# Trim OpenCode Session Skill

This skill provides a standardized workflow and operational guide for converting raw OpenCode session exports (both OpenCode v1 and v2 formats) into compact, human-readable Markdown review transcripts with chronologically ordered and titled subtasks.

## Prerequisites

- **Python 3.10+** with `typer` installed.
- **OpenCode CLI** (`opencode`) installed and accessible in `PATH` (needed to export session transcripts and discovered subtasks).
- Authorized binary and directory paths configured in [`.agents/PATH_ALLOWLIST.md`](../PATH_ALLOWLIST.md).

---

## Toolkit Overview

The repository contains specialized Python utilities designed to process OpenCode session transcripts:

| Script | Purpose |
| :--- | :--- |
| [process_session.py](../../../process_session.py) | **Primary Orchestrator**: Trims main session, discovers subtasks, exports them to temp files, and trims each subtask into `subtasks/` with chronological prefixes. |
| [trimmer.py](../../../trimmer.py) | **Core Engine**: Converts a single session JSON file into a compact Markdown transcript with truncated tool outputs and reasoning blocks. Supports v1 & v2 schemas. |
| [export_task_sessions.py](../../../export_task_sessions.py) | **Task Exporter**: Traverses session JSON for `task` and `subagent` tool calls, extracts session IDs, and exports them via `opencode session export <id>` (v2) or `opencode export <id>` (v1). |
| [trim_md_apply_patch.py](../../../trim_md_apply_patch.py) | **Retroactive Cleaner**: Scans generated Markdown transcripts and retroactively truncates oversized `apply_patch` diff payloads. |
| [extract_task_ids.py](../../../extract_task_ids.py) | **ID Utility**: Uses regular expressions to extract `<task id="..." ...>` and `<subagent sessionID="..." ...>` tags from Markdown files. |

---

## Context Window & Token Efficiency Safeguards

> [!IMPORTANT]
> **Strict Zero-Context File Inspection**:
> 1. **Do NOT read raw session JSON files into context**: Never use `view_file` or text-reading tools to inspect raw session JSON exports. These exports can be tens of thousands of lines long and will exhaust token limits. All parsing, schema validation, and subtask discovery must be performed by running the CLI scripts.
> 2. **Do NOT read generated Markdown transcripts into context during processing**: The agent must not load generated `.md` transcripts into context simply to verify them. Verification is strictly performed via the CLI script's exit code (`0`) and stdout summary. Only inspect `.md` content if the user explicitly requests an in-depth conversation summary or analysis.

---

## Supported Input Schemas & Export Methods

### If Given a Session ID (`ses_...`)
If the user provides an OpenCode session ID instead of a file path (e.g. `/trim-opencode-session ses_...`):
Export it first to `raw_session_json/` before processing:
```powershell
# OpenCode v2.x+:
opencode session export <session_id> > raw_session_json/session_<session_id>.json

# OpenCode 1.x (legacy):
opencode export <session_id> > raw_session_json/session_<session_id>.json
```

### Supported Schemas
1. **CLI Export Format (Supported by Default)**
   - **OpenCode v2.x+**: Messages have top-level `type` (`user`, `assistant`, `synthetic`, `compaction`), user prompt in `text`, assistant blocks in `content` list, and subagents in `name: "subagent"`.
   - **OpenCode v1.x**: Messages have `info.role`, flat `parts` list, and subagents in `tool: "task"`.
2. **SQLite Database Dump Format (Requires Conversion)**
   - Direct database dumps (`{"session": {...}, "child_sessions": [...]}`) are unprocessable directly.
   - Re-export using the OpenCode CLI command above prior to processing.
   - For full schema comparison, see [SESSION_FORMAT_COMPARISON.md](../../useful_info/SESSION_FORMAT_COMPARISON.md).

---

## Standard Execution Procedure

### 1. Preview with Dry-Run (Zero Context Cost)
Always perform a dry-run first to inspect the parsed title, model, and discovered subtasks safely without reading the raw JSON file:

```powershell
python process_session.py raw_session_json/session_<session_id>.json --dry-run
```

Verify that:
- The title is human-readable (indicates valid CLI export format).
- Discovered subtasks match expected subagent invocations.
- Target folder name reflects the session title.
- Subtask markdown targets are chronologically numbered (e.g. `001_<title>.md`).

### 2. Run Full Session Processing
Execute the orchestrator to build the target bundle:

```powershell
python process_session.py raw_session_json/session_<session_id>.json
```

**Common Parameters**:
- `-o <dir>` / `--output-dir <dir>`: Custom output folder (defaults to `extractions/<sanitized_session_title>`).
- `-f` / `--overwrite`: Overwrite existing `.md` files in output directory.
- `--max-output-length <int>`: Character threshold for tool output truncation (default: 500).
- `--max-input-length <int>`: Character threshold for tool input payload truncation (default: 500).
- `--no-truncate-apply-patch`: Preserve full patch diffs (or set env `TRUNCATE_APPLY_PATCH_INPUT=false`).
- `--keep-temp`: Keep raw exported subtask JSON files in the temporary directory.

### 3. Verify Generated Bundle (Zero Token Cost)
Do **NOT** view or read the generated `.md` files into context. Confirm the generation solely through the CLI exit code (`0`) and stdout summary block:
```text
extractions/<session_title>/
├── <session_json_stem>.md   # Main session review transcript (includes Session ID in header)
└── subtasks/                # Created only if subtasks were discovered
    ├── 001_<subtask_1_title>.md
    ├── 002_<subtask_2_title>.md
    └── ...
```
If directory existence needs double-checking, use the lightweight directory listing tool rather than loading markdown files. Report the resulting file paths directly to the user.

---

## Troubleshooting & Best Practices

- **OpenCode CLI v1 vs v2 Compatibility**: `export_task_sessions.py` automatically checks `opencode --version` to run `opencode session export` (v2+) or fallback to `opencode export` (v1).
- **Windows Executable Resolution**: `export_task_sessions.py` resolves `.cmd`, `.bat`, `.exe`, and `.ps1` extensions. Ensure `opencode` is present in `PATH` or pass `--opencode-bin "C:\Program Files\nodejs\opencode.CMD"`.
- **Character Encoding**: UTF-8 output encoding is enforced with `errors='replace'` to avoid cp1252 charmap decode exceptions on Windows.
- **Retroactive Patch Trimming**: If review transcripts have already been generated with raw diffs, run `python trim_md_apply_patch.py <path_or_dir>` to truncate patch payloads without re-exporting.
