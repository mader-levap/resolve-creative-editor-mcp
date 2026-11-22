"""The doctor and the audit log reader."""
import json
import os
import shutil
import sys
from typing import Any

from .. import audit, bridge, paths


def audit_log(a: dict[str, Any]) -> dict[str, Any]:
    try:
        with open(audit.AUDIT, encoding="utf-8") as f:
            rows = f.readlines()
    except OSError:
        return {"entries": []}
    return {"entries": [json.loads(x) for x in rows[-(a.get("limit") or 20):]]}


def doctor(a: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        import importlib.util
        whisper = importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        whisper = False
    report = {"python": sys.version.split()[0], "ffmpeg": bool(shutil.which("ffmpeg") or os.environ.get("FFMPEG")),
              "ffprobe": bool(shutil.which("ffprobe") or os.environ.get("FFPROBE")), "faster_whisper": whisper,
              "bridge_folder": paths.DIR}
    try:
        res = bridge.call_bridge("get_state", {}, timeout=6, ack_timeout=4)
        report["bridge"] = "connected" if res.get("ok") else res.get("error")
        report["resolve"] = res.get("result")
    except Exception as exc:
        report["bridge"] = f"not running: start it from the Resolve Console ({type(exc).__name__})"
    return report
