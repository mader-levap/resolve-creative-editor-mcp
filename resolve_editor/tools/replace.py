"""Moving and trimming by settings-preserving replacement."""
from collections.abc import Callable
from typing import Any

from .. import outcome, session, timecode, timeline

REFUSE_REASONS = [
    (lambda d: d.get("fusion_comps"), "it has a Fusion composition, which can't be copied"),
    (lambda d: d.get("takes"), "it has takes, which can't be copied"),
    (lambda d: (d.get("speed") or {}).get("Percentage", 100) != 100, "it has a speed change; set speed to 100% first"),
    (lambda d: not d.get("media_id"), "it isn't a media-pool clip (title, generator or compound clip)"),
]


def _plan_replace(item_id: str, include_linked: bool,
                  new_range: Callable[[session.Item], tuple[int, int, int, int]]) -> list[dict[str, Any]] | str:
    """new_range(item) -> (first, last, record, track). Returns (plan, warnings) or a reason string."""
    items = {x["id"]: x for x in session.items()}
    if item_id not in items:
        return f"timeline item not found: {item_id}"
    root = session.as_list(session.call("item_details", item_ids=[item_id]))[0]
    ids = [item_id] + [i for i in (root.get("linked") or []) if include_linked and i in items]
    details = {d["id"]: d for d in session.as_list(session.call("item_details", item_ids=ids))}
    fps, _, _ = session.clock()
    plan = []
    for i in ids:
        item, d = items[i], details[i]
        for test, why in REFUSE_REASONS:
            if test(d):
                return f"{item['name']} on {item['track_type']} {item['track']}: {why}"
        media = next((m for m in session.media_pool() if m.get("id") == d["media_id"]), None)
        if not media or abs(float(timecode.parse_fps(media.get("fps"))) - float(fps)) > 0.001:
            return f"{item['name']}: clip frame rate differs from the timeline, so source frames would not line up"
        first, last, record, track = new_range(item)
        frames = int(float(media.get("frames") or 0))
        if first < 0 or last <= first or (frames and last > frames):
            return f"{item['name']}: source range {first}-{last} is outside the clip (0-{frames})"
        hit = timeline.collides(item["track_type"], track, record, record + last - first, ignore=ids)
        if hit:
            return f"{item['name']} would overwrite {hit['name']} at {session.to_tc(hit['start'])}"
        for x in items.values():
            if (x.get("type") == "transition" and x["track_type"] == item["track_type"] and x["track"] == item["track"]
                    and x["start"] <= item["end"] and item["start"] <= x["end"]):
                return f"{item['name']} has a transition touching it; remove it in Resolve first"
        plan.append({"item": item, "detail": d, "media_id": d["media_id"], "first": first, "last": last,
                     "record": record, "track": track, "shift": item["source_start"] - first})
    return plan


def _matches(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    keys = set(old.get("properties") or {}) & set(new.get("properties") or {})
    diff = [k for k in keys if old["properties"][k] != new["properties"][k]]
    for k in ("fades", "color", "enabled"):
        if old.get(k) != new.get(k):
            diff.append(k)
    return diff


def _replace(plan: list[dict[str, Any]], backup: bool = True) -> dict[str, Any]:
    """Build replacements on staging tracks, copy settings, then swap. Original survives any failure before the swap."""
    snapshot = timeline.snapshot_timeline({"label": "before edit"}).get("snapshot") if backup else None
    staged: list[session.Item]
    staging, staged, done = {}, [], []

    def stage_track(kind: str) -> int:
        if kind not in staging:
            staging[kind] = session.call("add_track", track_type=kind)["count"]
        return staging[kind]

    def cleanup() -> None:
        if staged:
            session.call("delete_items", item_ids=[s["id"] for s in staged])
        for kind, track in staging.items():
            try:
                session.call("delete_empty_track", track_type=kind, track=track)
            except RuntimeError:
                pass
        session.invalidate()

    try:
        for p in plan:
            kind = p["item"]["track_type"]
            s = timeline.append_one(p["media_id"], kind, p["first"], p["last"], p["record"], stage_track(kind))
            staged.append(s)
            report = session.call("copy_settings", from_id=p["item"]["id"], to_id=s["id"], kind=kind,
                                  marker_shift=p["shift"])
            if report["failed"]:
                raise RuntimeError(f"could not copy {', '.join(report['failed'])} to the replacement")
            p["staged"] = s
    except Exception as exc:
        cleanup()
        return outcome.op("failed", reason=f"nothing changed: {exc}", snapshot=snapshot)

    session.call("delete_items", item_ids=[p["item"]["id"] for p in plan])
    session.invalidate()
    try:
        for p in plan:
            kind = p["item"]["track_type"]
            n = timeline.append_one(p["media_id"], kind, p["first"], p["last"], p["record"], p["track"])
            session.call("copy_settings", from_id=p["staged"]["id"], to_id=n["id"], kind=kind, marker_shift=0)
            done.append((p, n))
    except Exception as exc:
        for _, n in done:
            session.call("delete_items", item_ids=[n["id"]])
        restored = []
        for p in plan:
            item = p["item"]
            r = timeline.append_one(p["media_id"], item["track_type"], item["source_start"],
                                    item["source_start"] + item["duration"], item["start"], item["track"])
            session.call("copy_settings", from_id=p["staged"]["id"], to_id=r["id"], kind=item["track_type"],
                         marker_shift=p["first"] - item["source_start"])
            restored.append(r["id"])
        if len(restored) > 1:
            session.call("link_items", item_ids=restored)
        cleanup()
        return outcome.op("failed", reason=f"swap failed ({exc}); the original was rebuilt with its settings",
                          snapshot=snapshot, warnings=["keyframes on the original are lost"])

    if len(done) > 1:
        session.call("link_items", item_ids=[n["id"] for _, n in done])
    after = {d["id"]: d for d in session.as_list(session.call("item_details", item_ids=[n["id"] for _, n in done]))}
    problems = []
    for p, n in done:
        diff = _matches(p["detail"], after[n["id"]])
        if diff:
            problems.append(f"{p['item']['name']}: {', '.join(diff)} differ")
    cleanup()
    changes = [{"item": p["item"]["name"], "track": f"{p['item']['track_type'][0].upper()}{p['track']}",
                "from": [session.to_tc(p["item"]["start"]), p["item"]["duration"]],
                "to": [session.to_tc(p["record"]), p["last"] - p["first"]], "new_id": n["id"]} for p, n in done]
    return outcome.op("success" if not problems else "partial", not problems, {"replaced": changes},
                      ["keyframes are not copied"] + problems, snapshot=snapshot)


def _replace_tool(a: dict[str, Any], new_range: Callable[[session.Item], tuple[int, int, int, int]],
                  verb: str) -> dict[str, Any]:
    plan = _plan_replace(a["item_id"], a.get("include_linked", True), new_range)
    if isinstance(plan, str):
        return outcome.blocked(plan)
    rows = [{"item": p["item"]["name"], "track": f"{p['item']['track_type'][0].upper()}{p['track']}",
             "from": [session.to_tc(p["item"]["start"]), p["item"]["duration"]],
             "to": [session.to_tc(p["record"]), p["last"] - p["first"]]}
            for p in plan]
    if not a.get("confirm"):
        return outcome.preview({verb: rows,
                                "method": "replacement built and settings copied before the original is removed"},
                               ["keyframes are not copied", "a backup timeline is made first"])
    return _replace(plan, a.get("backup", True))


def move_item(a: dict[str, Any]) -> dict[str, Any]:
    target = session.to_frame(a["record"])
    root = next((x for x in session.items() if x["id"] == a["item_id"]), None)
    if not root:
        return outcome.blocked(f"timeline item not found: {a['item_id']}")
    shift = target - root["start"]
    return _replace_tool(a, lambda it: (it["source_start"], it["source_start"] + it["duration"], it["start"] + shift,
                                        a.get("track_index") or it["track"] if it["id"] == a["item_id"]
                                        else it["track"]),
                         "move")


def trim_item(a: dict[str, Any]) -> dict[str, Any]:
    head, tail = a.get("head_frames") or 0, a.get("tail_frames") or 0
    if not head and not tail:
        return outcome.blocked("give head_frames and/or tail_frames")
    return _replace_tool(a, lambda it: (it["source_start"] + head, it["source_start"] + it["duration"] - tail,
                                        it["start"] + head, it["track"]), "trim")
