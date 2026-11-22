"""Placing Media Pool clips."""
from .. import outcome, session, timeline


def place_clips(a):
    plan, warnings = [], []
    for spec in a["clips"]:
        clip = timeline.find_clip(spec["clip"])
        first = spec.get("start_frame") or 0
        last = spec.get("end_frame") or int(float(clip.get("frames") or 0))
        record, track = session.to_frame(spec["record"]), spec.get("track_index") or 1
        if last <= first:
            return outcome.blocked(f"{clip['name']}: end_frame must be greater than start_frame")
        kinds = {1: ["video"], 2: ["audio"]}.get(spec.get("media_type"), ["video", "audio"])
        for kind in kinds:
            hit = timeline.collides(kind, track, record, record + last - first)
            if hit:
                return outcome.blocked(f"{clip['name']} would overwrite {hit['name']} on {kind[0].upper()}{track} "
                                       f"at {session.to_tc(hit['start'])}")
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
