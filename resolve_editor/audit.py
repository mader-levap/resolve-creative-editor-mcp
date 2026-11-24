"""The log of changes made through this server."""
import contextlib
import json
import os
import time
from typing import Any

from . import paths

AUDIT = os.path.join(paths.DIR, "audit.jsonl")


def log_audit(tool: str, args: dict[str, Any], status: str) -> None:
    """Append one line to the audit log. Never raises: a log that can't be written is skipped."""
    with contextlib.suppress(OSError), open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, "args": args,
                            "status": status}, ensure_ascii=False, default=str) + "\n")
