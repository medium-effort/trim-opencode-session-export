import sys
import re
from pathlib import Path


def extract_task_ids(md_path: str | Path) -> list[str]:
    """Extract all task IDs from an OpenCode session markdown file.

    Matches patterns like:
        <task id="ses_ffeb6618affe53Z2A9jDVRDh31" state="completed">
    """
    path = Path(md_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    content = path.read_text(encoding="utf-8")
    
    # Matches <task ... id="<ID>" ...> or <subagent ... sessionID="<ID>" ...> with double or single quotes
    pattern = re.compile(
        r'<(?:task|subagent)\b[^>]*?\b(?:id|sessionID|sessionId)=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    return pattern.findall(content)


def main():
    target_file = sys.argv[1] if len(sys.argv) > 1 else "session_for_review.md"

    try:
        task_ids = extract_task_ids(target_file)
        for task_id in task_ids:
            print(task_id)
    except FileNotFoundError as err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
