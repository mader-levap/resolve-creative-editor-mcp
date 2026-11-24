"""The doctor and the audit log reader."""
import json
import os
import shutil
import sys
from typing import Any

from .. import audit, bridge, paths, prefs


def audit_log(a: dict[str, Any]) -> dict[str, Any]:
    try:
        with open(audit.AUDIT, encoding="utf-8") as f:
            rows = f.readlines()
    except OSError:
        return {"entries": []}
    return {"entries": [_entry(x) for x in rows[-(a.get("limit") or 20):]]}


def _entry(line: str) -> Any:
    try:
        return json.loads(line)
    except ValueError:  # e.g. cut short by a crash mid-write: show it rather than fail the whole log
        return {"unreadable": line.rstrip("\n")}


def doctor(a: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        import importlib.util
        whisper = importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        whisper = False
    report = {"python": sys.version.split()[0], "ffmpeg": bool(shutil.which("ffmpeg") or os.environ.get("FFMPEG")),
              "ffprobe": bool(shutil.which("ffprobe") or os.environ.get("FFPROBE")), "faster_whisper": whisper,
              "bridge_folder": paths.DIR}
    generator = prefs.describe(prefs.generator_duration())
    if generator:  # the longest a script can make a title (docs/ISSUES.md I-24)
        report["standard_generator_duration"] = f"{generator} ({prefs.NOTE})"
    hang = bridge.read_hang()  # read first: an answer below clears it
    if hang:
        report["bridge_hang"] = hang
    try:
        res = bridge.call_bridge("get_state", {}, timeout=6, ack_timeout=4, lock_timeout=4)
        report["bridge"] = "connected" if res.get("ok") else res.get("error")
        report["resolve"] = res.get("result")
        stuck = (res.get("result") or {}).get("previous_run_stuck")
        if stuck:  # the bridge's own record of where the copy before it stopped (docs/ISSUES.md I-22)
            report["previous_run_stuck"] = stuck
    except bridge.BridgeBusy:
        report["bridge"] = "busy: another client is using it (it is running)"
    except Exception as exc:
        report["bridge"] = f"not answering ({type(exc).__name__}): {exc}"
    return report
