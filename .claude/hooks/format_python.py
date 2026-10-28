"""Claude Code PostToolUse hook: format a Python file right after Claude edits it.

Claude Code sends the tool call as JSON on stdin. Anything unexpected (bad JSON,
a non-Python file, a missing file, no uv) is ignored, so the hook never blocks an edit.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "apps" / "api"


def main() -> None:
    try:
        event = json.load(sys.stdin)
        file_path = Path(event["tool_input"]["file_path"])
    except (ValueError, KeyError, TypeError):
        return

    if file_path.suffix != ".py" or not file_path.is_file():
        return
    # Only this repo's files: never reformat code outside the project.
    if not file_path.resolve().is_relative_to(REPO_ROOT):
        return

    try:
        subprocess.run(  # noqa: S603 - fixed command, the path is passed as one argument
            ["uv", "run", "--directory", str(API_DIR), "ruff", "format", str(file_path)],  # noqa: S607
            check=False,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return


if __name__ == "__main__":
    main()
