"""Placing Media Pool clips."""
from typing import Any

from .. import outcome, session, timeline


def place_clips(a: dict[str, Any]) -> dict[str, Any]:
    """edit__place_clips: preview, then place Media Pool clips at exact frames and tracks; refuses to
    overwrite, also between the clips of one call."""
    warnings: list[str]
    plan, warnings = [], []
    planned: list[tuple[str, int, int, int, int, str]] = []  # kind, track, start, end, n, name of earlier clips
    for n, spec in enumerate(a["clips"], 1):
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
        kinds = {1: ["video"], 2: ["audio"]}.get(spec.get("media_type"), ["video", "audio"])
        for kind in kinds:
            label = timeline.track_label(kind, track)
            hit = timeline.collides(kind, track, record, record + last - first)
            if hit:
                return outcome.blocked(f"{clip['name']} would overwrite {hit['name']} on {label} "
                                       f"at {session.to_tc(hit['start'])}")
            # Resolve places a clip that overlaps an earlier one of the same call shifted and shortened (I-27)
            other = next((p for p in planned if p[:2] == (kind, track) and record < p[3]
                          and p[2] < record + last - first), None)
            if other:
                return outcome.blocked(f"clip {n} ({clip['name']}) would overlap clip {other[4]} ({other[5]}) on "
                                       f"{label} at {session.to_tc(record)}; clips of one call "
                                       "can't overlap")
        planned += [(kind, track, record, record + last - first, n, clip["name"]) for kind in kinds]
        plan.append({"clip": clip["id"], "name": clip["name"], "start_frame": first, "end_frame": last,
                     "record_frame": record, "track_index": track, "media_type": spec.get("media_type"),
                     "at": session.to_tc(record), "frames": last - first})
    if not a.get("confirm"):
        return outcome.preview(plan, warnings)
    session.call("append_clips", clips=[{k: p[k] for k in ("clip", "start_frame", "end_frame", "record_frame",
                                                            "track_index", "media_type") if p[k] is not None}
                                        for p in plan])
    session.invalidate()
    landed = sum(1 for p in plan if any(x["start"] == p["record_frame"] and x["track"] == p["track_index"]
                                        and x["name"] == p["name"] for x in session.items()))
    return outcome.op("success" if landed == len(plan) else "partial", landed == len(plan), {"clips_placed": landed})
