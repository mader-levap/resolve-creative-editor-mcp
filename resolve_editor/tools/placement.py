"""Placing Media Pool clips."""
import math
from fractions import Fraction
from typing import Any

from .. import outcome, session, timecode, timeline


def _timeline_frames(clip: dict[str, Any], source: int, fps: Fraction) -> tuple[int, bool, str | None]:
    """(timeline frames, whether exact, warning) for `source` frames of a clip. Resolve converts a clip whose frame
    rate differs from the timeline's: a 30 fps clip takes twice as many frames on a 60 fps timeline (docs/ISSUES.md
    I-30). A length that isn't whole is rounded up for the checks; an unknown rate keeps the source length."""
    try:
        rate = timecode.parse_fps(clip.get("fps"))
    except ValueError:
        rate = Fraction(0)
    if not rate:
        return source, True, (f"{clip['name']}: frame rate unknown, so its length on the timeline is taken as "
                              f"{source} frames unchecked")
    length = source * fps / rate
    if length.denominator == 1:
        return int(length), True, None
    return math.ceil(length), False, (f"{clip['name']}: {source} frames at {float(rate):g} fps are "
                                      f"{float(length):.2f} timeline frames; checked as {math.ceil(length)}, and "
                                      "Resolve may round it by a frame")


def place_clips(args: dict[str, Any]) -> dict[str, Any]:
    """edit__place_clips: preview, then place Media Pool clips at exact frames and tracks; refuses to
    overwrite, also between the clips of one call. Lengths on the timeline are in timeline frames."""
    warnings: list[str]
    plan, warnings, exact = [], [], []
    planned: list[tuple[str, int, int, int, int, str]] = []  # kind, track, start, end, n, name of earlier clips
    fps, _, _ = session.clock()
    for n, spec in enumerate(args["clips"], 1):
        clip = timeline.find_clip(spec["clip"])
        first = spec.get("start_frame") or 0
        frames = int(float(clip.get("frames") or 0))  # 0 when unknown: then only the bridge can check
        last = spec.get("end_frame") or frames
        record, track = session.to_frame(spec["record"]), spec.get("track_index") or 1
        if last <= first:
            return outcome.blocked(f"{clip['name']}: end_frame must be greater than start_frame")
        if first < 0 or (frames and last > frames):  # end_frame is exclusive (docs/ISSUES.md I-28)
            return outcome.blocked(f"{clip['name']}: source range {first}-{last} is outside the clip "
                                   f"(0-{frames or '?'})")
        span, whole, note = _timeline_frames(clip, last - first, fps)
        if note:
            warnings.append(note)
        kinds = {1: ["video"], 2: ["audio"]}.get(spec.get("media_type"), ["video", "audio"])
        for kind in kinds:
            label = timeline.track_label(kind, track)
            hit = timeline.collides(kind, track, record, record + span)
            if hit:
                return outcome.blocked(f"{clip['name']} would overwrite {hit['name']} on {label} "
                                       f"at {session.to_tc(hit['start'])}")
            # Resolve places a clip that overlaps an earlier one of the same call shifted and shortened (I-27)
            other = next((p for p in planned if p[:2] == (kind, track) and record < p[3]
                          and p[2] < record + span), None)
            if other:
                return outcome.blocked(f"clip {n} ({clip['name']}) would overlap clip {other[4]} ({other[5]}) on "
                                       f"{label} at {session.to_tc(record)}; clips of one call "
                                       "can't overlap")
        planned += [(kind, track, record, record + span, n, clip["name"]) for kind in kinds]
        row = {"clip": clip["id"], "name": clip["name"], "start_frame": first, "end_frame": last,
               "record_frame": record, "track_index": track, "media_type": spec.get("media_type"),
               "at": session.to_tc(record), "frames": span, "source_frames": last - first}
        if span != last - first or not whole:
            row["clip_fps"] = float(timecode.parse_fps(clip.get("fps")))
        plan.append(row)
        exact.append(whole)
    if not args.get("confirm"):
        return outcome.preview(plan, warnings)
    session.call("append_clips", clips=[{k: p[k] for k in ("clip", "start_frame", "end_frame", "record_frame",
                                                            "track_index", "media_type") if p[k] is not None}
                                        for p in plan])
    session.invalidate()
    # landed: at its frame on its track with the expected length, within a frame when that isn't whole (I-30)
    landed = sum(1 for p, whole in zip(plan, exact)
                 if any(x["start"] == p["record_frame"] and x["track"] == p["track_index"] and x["name"] == p["name"]
                        and abs(x["duration"] - p["frames"]) <= (0 if whole else 1) for x in session.items()))
    return outcome.op("success" if landed == len(plan) else "partial", landed == len(plan), {"clips_placed": landed},
                      warnings=warnings)
