# OpenCode Session JSON Format Comparison & Issue Analysis

This document provides a detailed breakdown of the structural differences between:
1. **CLI Export Format** (as seen in `opencode_export_format_example.json`, produced by `opencode export <session_id>`)
2. **SQLite Database Export Format** (as seen in `session_ses_fd5f1699fffek6gGkSvq82SSB6.json`, exported directly from `opencode.db`)

It also explains exactly why the current workspace processing scripts (`process_session.py`, `trimmer.py`, and `export_task_sessions.py`) fail when processing SQLite database exports.

---

## 1. High-Level Problem Summary

The workspace pipeline was built assuming all input JSON files strictly follow the **CLI Export Format**. 

When fed a **SQLite Database Export**:
1. **Metadata Missing:** Session title defaults to the filename, model displays as `unknown`, and cost displays as `$0.0000`.
2. **Empty Markdown Transcripts:** Message roles resolve to `[UNKNOWN]`, and all message contents (reasoning thoughts, conversational messages, and tool invocations) are completely omitted because `part.type` is not found at top-level.
3. **Subtasks Ignored:** Discovered subtasks evaluate to `0` because child sessions are recorded under the root array `child_sessions` rather than inline `tool == "task"` calls.

---

## 2. Structural Difference Matrix

| Feature / Location | CLI Export (`opencode_export_format_example.json`) | SQLite Export (`session_ses_fd5f1699fffek6gGkSvq82SSB6.json`) |
| :--- | :--- | :--- |
| **Top-level Keys** | `["info", "messages"]` | `["session", "child_sessions", "todos", "session_inputs", "session_messages", "messages"]` |
| **Session Metadata Root** | `data["info"]` | `data["session"]` |
| **Session Title** | `data["info"]["title"]` | `data["session"]["title"]` |
| **Model Info** | `data["info"]["model"]["id"]` | `data["session"]["model"]["id"]` |
| **Session Cost** | `data["info"]["cost"]` | `data["session"]["cost"]` |
| **Tokens Layout** | Nested object: `data["info"]["tokens"]["input"]` | Flat keys: `data["session"]["tokens_input"]` |
| **Timestamps** | Nested object: `data["info"]["time"]["created"]` | Flat key: `data["session"]["time_created"]` |
| **Message Metadata** | `msg["info"]` | `msg["data"]` |
| **Message Role** | `msg["info"]["role"]` (`user` / `assistant`) | `msg["data"]["role"]` (`user` / `assistant`) |
| **Message IDs** | `msg["info"]["id"]`, `msg["info"]["sessionID"]` | Top-level table columns: `msg["id"]`, `msg["session_id"]` |
| **Part Payload Location** | Flat: `part["type"]`, `part["text"]`, `part["tool"]` | Nested under `data`: `part["data"]["type"]`, `part["data"]["text"]`, `part["data"]["tool"]` |
| **Part State (Tools)** | `part["state"]` (`input`, `output`, `status`) | `part["data"]["state"]` (`input`, `output`, `status`) |
| **Subtask / Child Sessions** | Discovered via inline tool calls: `part["tool"] == "task"` | Root array: `data["child_sessions"]` (list of `{id, title, ...}`) |

---

## 3. Side-by-Side Schema Examples

### A. Root & Metadata Structure

#### CLI Export (`opencode_export_format_example.json`)
```json
{
  "info": {
    "id": "ses_0009cb46bffe2trvJc4kD6kZPe",
    "slug": "curious-harbor",
    "projectID": "f6880dafc5e6ed984c06463ab7eec2d32f938450",
    "directory": "D:\\Users\\Ethereal\\!Safeplace\\Godot Projects Migrasi\\Hunter-Corp",
    "title": "Read Star_Rating_Staff.pdf with Citra",
    "agent": "build",
    "model": {
      "id": "gpt-5.6-luna",
      "providerID": "opencode-go",
      "variant": "high"
    },
    "cost": 0.0025882,
    "tokens": {
      "input": 9,
      "output": 440,
      "reasoning": 304,
      "cache": { "read": 23278, "write": 15265 }
    },
    "time": {
      "created": 1786696125332,
      "updated": 1786696148618
    }
  },
  "messages": [ ... ]
}
```

#### SQLite DB Export (`session_ses_fd5f1699fffek6gGkSvq82SSB6.json`)
```json
{
  "session": {
    "id": "ses_fd5f1699fffek6gGkSvq82SSB6",
    "project_id": "f0e79bf7eedb479172f2b8e5492e9c16cb001f01",
    "slug": "happy-forest",
    "directory": "G:/antigravity_projects/markdown-note-webapp-test/mnwa-by-crewmate",
    "path": "G:/antigravity_projects/markdown-note-webapp-test/mnwa-by-crewmate",
    "title": "Markdown notes web app brief",
    "agent": "frontman",
    "model": {
      "id": "x-preview-f-free",
      "providerID": "opencode",
      "variant": "high"
    },
    "cost": 0.0,
    "tokens_input": 16678,
    "tokens_output": 2494,
    "tokens_reasoning": 707,
    "tokens_cache_read": 340480,
    "tokens_cache_write": 0,
    "time_created": 1787411994208,
    "time_updated": 1787418858244
  },
  "child_sessions": [
    {
      "id": "ses_fd5e66df3ffePcIrFvNoaOznr5",
      "title": "Write crewmate failure report (@executor subagent)",
      "directory": "G:/antigravity_projects/markdown-note-webapp-test/mnwa-by-crewmate",
      "time_created": 1787412713996
    }
  ],
  "todos": [],
  "session_inputs": [],
  "session_messages": [],
  "messages": [ ... ]
}
```

---

### B. Message Structure

#### CLI Export (`opencode_export_format_example.json`)
```json
{
  "info": {
    "id": "msg_fff634bdb001vhpS7sJcjzjM5t",
    "sessionID": "ses_0009cb46bffe2trvJc4kD6kZPe",
    "role": "user",
    "agent": "build",
    "model": {
      "providerID": "opencode-go",
      "modelID": "gpt-5.6-luna",
      "variant": "high"
    },
    "time": {
      "created": 1786696125541
    }
  },
  "parts": [ ... ]
}
```

#### SQLite DB Export (`session_ses_fd5f1699fffek6gGkSvq82SSB6.json`)
```json
{
  "id": "msg_02a0e9725001htB9j21RTv9rfY",
  "session_id": "ses_fd5f1699fffek6gGkSvq82SSB6",
  "time_created": 1787411994524,
  "time_updated": 1787412338068,
  "data": {
    "role": "user",
    "agent": "frontman",
    "model": {
      "providerID": "opencode",
      "modelID": "x-preview-f-free",
      "variant": "high"
    },
    "time": {
      "created": 1787411994524
    }
  },
  "parts": [ ... ]
}
```

---

### C. Part Structure (Text & Reasoning)

#### CLI Export (`opencode_export_format_example.json`)
```json
{
  "type": "reasoning",
  "text": "**Reading PDF with Citra**\n\nI need to read a PDF...",
  "time": { "start": 1786696133759, "end": 1786696133859 },
  "id": "prt_fff636c7f001qMEBhMlnYJR82M",
  "sessionID": "ses_0009cb46bffe2trvJc4kD6kZPe",
  "messageID": "msg_fff634cb4001goMLygG39Pjmpd"
}
```

#### SQLite DB Export (`session_ses_fd5f1699fffek6gGkSvq82SSB6.json`)
```json
{
  "id": "prt_02a0eb40c0013yee0wGpew9BoG",
  "message_id": "msg_02a0e9846001rD9D2yDvn9eMh7",
  "session_id": "ses_fd5f1699fffek6gGkSvq82SSB6",
  "time_created": 1787412001804,
  "time_updated": 1787412004244,
  "data": {
    "type": "reasoning",
    "text": "The user wants me to turn the reference.md into a brief...",
    "time": { "start": 1787412001804, "end": 1787412004242 }
  }
}
```

---

### D. Part Structure (Tool Invocations)

#### CLI Export (`opencode_export_format_example.json`)
```json
{
  "type": "tool",
  "tool": "citra_read_pdf",
  "callID": "call_y9ARmtlm8kr4CDtnTe1VymYl",
  "state": {
    "status": "completed",
    "input": { "sources": [{ "path": ".agents\\specs\\Star_Rating_Staff.pdf" }] },
    "output": "The tool call succeeded...",
    "title": ""
  },
  "id": "prt_fff636de7001onfeYOsH7uujlv",
  "sessionID": "ses_0009cb46bffe2trvJc4kD6kZPe",
  "messageID": "msg_fff634cb4001goMLygG39Pjmpd"
}
```

#### SQLite DB Export (`session_ses_fd5f1699fffek6gGkSvq82SSB6.json`)
```json
{
  "id": "prt_02a0ec5090016NIA6yDrHq3X4Q",
  "message_id": "msg_02a0e9846001rD9D2yDvn9eMh7",
  "session_id": "ses_fd5f1699fffek6gGkSvq82SSB6",
  "time_created": 1787412006153,
  "time_updated": 1787412006456,
  "data": {
    "type": "tool",
    "tool": "crewmate_create_brief",
    "callID": "call_39bdddf37f87401e966a91d0",
    "state": {
      "status": "completed",
      "input": {},
      "output": "{\"ok\":true,\"id\":\"1c9c5cde\"}",
      "title": "Brief created: 1c9c5cde"
    }
  }
}
```

---

## 4. Code Breakdown: Where Current Scripts Break

### 1. In `process_session.py`
* **Line 103–106:**
  ```python
  info = session_data.get("info") or {}
  title = info.get("title") or session_json.stem
  model_id = (info.get("model") or {}).get("id", "unknown")
  cost = info.get("cost") or 0.0
  ```
  * **Failure:** `session_data.get("info")` returns `None`. Thus `title` defaults to `session_ses_fd5f1699fffek6gGkSvq82SSB6`, `model_id` becomes `unknown`, and `cost` becomes `0.0`.

### 2. In `trimmer.py`
* **Line 53–56:**
  ```python
  lines.append(f"# Evaluation Log: {data.get('info', {}).get('title', 'Session')}")
  lines.append(f"**Target Model:** {data.get('info', {}).get('model', {}).get('id')} | **Total Cost:** ${data.get('info', {}).get('cost', 0):.4f}\n---")
  ```
  * **Failure:** Header displays `# Evaluation Log: Session` and `Target Model: None`.
* **Line 60:**
  ```python
  role = msg.get("info", {}).get("role", "unknown").upper()
  ```
  * **Failure:** `msg.get("info")` returns `{}` because role is in `msg["data"]["role"]`. Every turn header becomes `## Turn N [UNKNOWN]`.
* **Line 64–75:**
  ```python
  for part in msg.get("parts", []):
      p_type = part.get("type")
      if p_type == "reasoning" and part.get("text"): ...
      elif p_type == "text" and part.get("text"): ...
      elif p_type == "tool": ...
  ```
  * **Failure:** `part.get("type")` returns `None` because the part data is inside `part["data"]["type"]`. **Every single message, thought, and tool is skipped entirely.**

### 3. In `export_task_sessions.py`
* **Line 77–114:**
  `find_task_calls` traverses objects looking for `type == "tool"` and `tool == "task"`.
  * **Failure:** In SQLite-dumped sessions, subagents are linked via the parent session relation (`WHERE parent_id = ?`) and listed under `data["child_sessions"]`. Because there is no inline `task` tool call in the messages, `find_task_calls` discovers `0` subtasks. The child subagent session (`ses_fd5e66df3ffePcIrFvNoaOznr5`: *"Write crewmate failure report (@executor subagent)"*) is completely ignored.
