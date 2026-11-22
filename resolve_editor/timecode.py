"""Frame rates and timecode: pure maths."""
from fractions import Fraction
import re

NTSC = {23.976: Fraction(24000, 1001), 29.97: Fraction(30000, 1001), 47.952: Fraction(48000, 1001),
        59.94: Fraction(60000, 1001), 119.88: Fraction(120000, 1001)}


def parse_fps(value):
    """Resolve reports rates like 30, '29.97' or '23.976'. Returns an exact Fraction."""
    match = re.search(r"\d+(?:\.\d+)?", str(value if value is not None else ""))
    if not match:
        raise ValueError(f"unreadable frame rate: {value!r}")
    rate = float(match.group())
    for nominal, exact in NTSC.items():
        if abs(rate - nominal) < 0.01:
            return exact
    return Fraction(rate).limit_denominator(1001)


def frame_to_tc(frame, fps, drop=False):
    base = round(float(fps))
    frame = int(frame)
    if drop:  # SMPTE drop frame: skip 2 (or 4) frame numbers each minute except every tenth
        skip = round(base / 15)
        per_ten, per_minute = base * 600 - skip * 9, base * 60 - skip
        tens, rest = divmod(frame, per_ten)
        frame += skip * 9 * tens + (skip * ((rest - skip) // per_minute) if rest > skip else 0)
    sep = ";" if drop else ":"
    return (f"{frame // (base * 3600):02d}:{frame // (base * 60) % 60:02d}:{frame // base % 60:02d}"
            f"{sep}{frame % base:02d}")


def tc_to_frame(tc, fps, drop=False):
    parts = [int(x) for x in re.split(r"[:;.]", tc.strip())]
    if len(parts) != 4:
        raise ValueError(f"timecode must look like 01:00:12:05, got {tc!r}")
    h, m, s, f = parts
    base = round(float(fps))
    frame = ((h * 60 + m) * 60 + s) * base + f
    if drop:
        minutes = h * 60 + m
        frame -= round(base / 15) * (minutes - minutes // 10)
    return frame


def seconds_to_frames(seconds, fps):
    return round(Fraction(str(seconds)) * fps)
