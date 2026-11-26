"""Read-only inspection of the timeline and the Media Pool."""
from collections.abc import Callable
from itertools import pairwise
from typing import Any

from .. import session, timecode, timeline


def analyze(items: list[session.Item], limit: int = 10, tc: Callable[[int], str] = str,
            counts: dict[str, int] | None = None) -> dict[str, Any]:
    """Pure timeline analysis: gaps, overlaps, transitions, reused source clips. With Resolve's track counts, every
    track is listed, empty ones with 0 (docs/ISSUES.md I-11)."""
    tracks: dict[tuple[str, int], list[Any]]
    used: dict[str, list[int]]
    tracks, gaps, overlaps, used, transitions = {}, [], [], {}, 0
    for kind, n in (counts or {}).items():
        for track in range(1, int(n or 0) + 1):
            tracks[(kind, track)] = []
    for it in items:
        if it.get("type") == "transition":
            transitions += 1
            continue
        tracks.setdefault((it["track_type"], it["track"]), []).append(it)
        if it["track_type"] == "video" and it.get("type") != "generator":
            used.setdefault(it["name"], []).append(it["start"])
    for (kind, track), row in sorted(tracks.items()):
        row.sort(key=lambda x: x["start"])
        for a, b in pairwise(row):
            where = f"{'V' if kind == 'video' else 'A'}{track}"
            if b["start"] > a["end"]:
                gaps.append({"track": where, "at": tc(a["end"]), "frames": b["start"] - a["end"]})
            elif b["start"] < a["end"]:
                overlaps.append({"track": where, "at": tc(b["start"]), "frames": a["end"] - b["start"],
                                 "items": [a["id"], b["id"]]})
    reused = {n: [tc(s) for s in starts] for n, starts in sorted(used.items()) if len(starts) > 1}
    return {"items": len(items) - transitions, "transitions": transitions,
            "tracks": {f"{'V' if k == 'video' else 'A'}{t}": len(r) for (k, t), r in sorted(tracks.items())},
            "gaps": {"count": len(gaps), "first": gaps[:limit]},
            "overlaps": {"count": len(overlaps), "first": overlaps[:limit],
                         "note": "Same-track audio overlaps are usually crossfades." if overlaps else None},
            "reused_clips": reused}


def timeline_summary(args: dict[str, Any]) -> dict[str, Any]:
    """edit__timeline_summary: per-track counts, gaps, overlaps, transitions and reused clips of the
    current timeline."""
    _, _, state = session.clock()
    counts = state.get("track_counts")
    report = analyze(session.items(), args.get("limit") or 10, session.to_tc, counts)
    if not counts:
        report["note"] = "empty tracks aren't listed: restart the bridge"
    report.update({"timeline": state["timeline"], "fps": state["timeline_fps"],
                   "range": [session.to_tc(state["timeline_start_frame"]), session.to_tc(state["timeline_end_frame"])]})
    return report


DEFAULTS = {"Pan": 0, "Tilt": 0, "ZoomX": 1, "ZoomY": 1, "RotationAngle": 0, "Opacity": 100, "CropLeft": 0,
            "CropRight": 0, "CropTop": 0, "CropBottom": 0, "FlipX": False, "FlipY": False, "CompositeMode": 0,
            "AudioVolume": 0, "AudioPan": 0, "AudioPitchSemiTones": 0}


def inspect_range(args: dict[str, Any]) -> dict[str, Any]:
    """edit__inspect_range: items overlapping [start, end); details=true adds settings that differ from
    the defaults."""
    start, end = session.to_frame(args["start"]), session.to_frame(args["end"])
    hits = [x for x in session.items() if x["start"] < end and start < x["end"]]
    rows: list[dict[str, Any]] = [
        {"id": x["id"], "name": x["name"], "track": timeline.track_label(x["track_type"], x["track"]),
         "type": x.get("type"), "in": session.to_tc(x["start"]), "out": session.to_tc(x["end"]),
         "frames": x["duration"], "source_start": x.get("source_start")}
        for x in sorted(hits, key=lambda x: (x["start"], x["track_type"]))]
    clips = [r["id"] for r in rows if r["type"] != "transition"]
    details = {d["id"]: d for d in session.as_list(session.call("item_details", item_ids=clips))} if clips else {}
    _source_frames(rows, details)
    if args.get("details") and rows:
        for r in rows:
            d = details.get(r["id"])
            if d:
                props = d.get("properties") or {}
                r.update({"speed": (d.get("speed") or {}).get("Percentage"), "fades": d.get("fades"),
                          "enabled": d.get("enabled"), "color": d.get("color") or None,
                          "markers": len(d.get("markers") or {}),
                          "linked": d.get("linked"), "fusion_comps": d.get("fusion_comps"),
                          "changed_settings": {k: v for k, v in props.items()
                                               if k in DEFAULTS and v != DEFAULTS[k]}})
    return {"range": [session.to_tc(start), session.to_tc(end)], "count": len(rows), "items": rows}


def _source_frames(rows: list[dict[str, Any]], details: dict[str, Any]) -> None:
    """source_start as the clip's own frame (GetSourceStartFrame). Resolve lists the left offset in timeline
    frames, which differs for a clip at another frame rate; such a row also gets clip_fps (docs/ISSUES.md I-36)."""
    fps, _, _ = session.clock()
    media = {m.get("id"): m for m in session.media_pool()}
    for r in rows:
        d = details.get(r["id"]) or {}
        if d.get("source_start") is not None:
            r["source_start"] = d["source_start"]
        m = media.get(d.get("media_id"))
        if not m:
            continue
        try:
            rate = timecode.parse_fps(m.get("fps"))
        except ValueError:
            continue
        if abs(float(rate) - float(fps)) > 0.001:
            r["clip_fps"] = float(rate)


def find_media(args: dict[str, Any]) -> dict[str, Any]:
    """edit__find_media: Media Pool clips whose name contains `query` (case ignored), up to `limit`."""
    query, limit = (args.get("query") or "").lower(), args.get("limit") or 20
    hits = [m for m in session.media_pool() if query in (m.get("name") or "").lower()]
    return {"count": len(hits), "media": [{k: m.get(k) for k in ("id", "name", "frames", "fps", "type")}
                                          for m in hits[:limit]]}
