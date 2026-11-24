"""Resolve's saved user preferences, read only. The scripting API doesn't expose them (docs/ISSUES.md I-24)."""
import os
import xml.etree.ElementTree as ET
from fractions import Fraction

USER_PREFS = os.environ.get("RESOLVE_USER_PREFS") or os.path.join(
    os.environ.get("APPDATA", ""), "Blackmagic Design", "DaVinci Resolve", "Preferences", "config.user.xml")
NOTE = "from Resolve's saved preferences; a change not yet saved by Resolve may not show"


def generator_duration() -> dict[str, float] | None:
    """Preferences > User > Editing > Standard Generator Duration, the length Resolve inserts a title at:
    {"seconds": s} or {"frames": n}, or None when it can't be read."""
    try:
        root = ET.parse(USER_PREFS).getroot()
        kind = root.findtext("GeneratorDurationType") or ""
        if kind == "DURATION_IN_FRAMES":
            return {"frames": int(float(root.findtext("GeneratorDurationFrames") or ""))}
        if kind == "DURATION_IN_SECONDS":
            return {"seconds": float(root.findtext("GeneratorDurationSecs") or "")}
    except (OSError, ET.ParseError, ValueError):
        pass
    return None


def generator_frames(fps: Fraction | float) -> int | None:
    """Standard Generator Duration in frames at `fps`, or None when the preference can't be read."""
    d = generator_duration()
    if not d:
        return None
    return int(d["frames"]) if "frames" in d else round(d["seconds"] * float(fps))


def describe(d: dict[str, float] | None) -> str | None:
    """Standard Generator Duration as text ("5 s", "120 frames"), or None."""
    if not d:
        return None
    return f"{int(d['frames'])} frames" if "frames" in d else f"{d['seconds']:g} s"
