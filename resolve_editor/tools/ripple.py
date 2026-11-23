"""Ripple trim: in place, no rebuild."""
from collections.abc import Collection
from typing import Any

from .. import outcome, session, timeline


# Titles can't be moved by script, but a ripple delete shifts everything after the deleted item on all tracks. So:
# shorten the item in place (trim_tail), drop an n-frame filler into the gap it leaves, ripple-delete the filler.
def _filler_source(frames: int, prefer: str | None = None,
                   exclude: Collection[str] = ()) -> dict[str, Any] | None:
    usable = [m for m in session.media_pool() if m.get("type") == "Timeline" and m.get("name") not in exclude
              and int(float(m.get("frames") or 0)) >= frames]
    return next((m for m in usable if m.get("name") == prefer), None) or (usable[0] if usable else None)


def _positions() -> dict[str, tuple[int, int]]:
    """Every item's span, transitions included: the ripple moves them too, so they are checked after it (I-05)."""
    return {x["id"]: (x["start"], x["end"]) for x in session.items()}


def _plan(items: dict[str, session.Item], ids: list[str],
          n: int) -> list[session.Item] | dict[str, Any]:
    """Check every item; returns the items to trim, or a blocked result."""
    details = {d["id"]: d for d in session.as_list(session.call("item_details", item_ids=ids))}
    plan = []
    for i in ids:
        it = items[i]
        where = f"{it['name']} at {session.to_tc(it['start'])}"
        if it["track_type"] != "video":
            return outcome.blocked(f"{where}: only video items can be ripple-trimmed this way")
        if (details.get(i) or {}).get("linked"):
            return outcome.blocked(f"{where}: it has linked audio/video; use trim_item")
        if it["duration"] <= n:
            return outcome.blocked(f"{where}: it is only {it['duration']} frames long")
        new_end = it["end"] - n
        for x in items.values():
            if x["id"] == i:
                continue
            if x.get("type") == "transition":
                if (x["track_type"], x["track"]) == ("video", it["track"]):
                    if x["start"] <= it["end"] and it["start"] <= x["end"]:
                        return outcome.blocked(f"{where} has a transition touching it; remove it in Resolve first")
                elif x["start"] < it["end"] and x["end"] > new_end:  # the ripple shifts every track (ISSUES.md I-05)
                    return outcome.blocked(f"{where}: a transition on {x['track_type'][0].upper()}{x['track']} at "
                                           f"{session.to_tc(x['start'])} overlaps the frames being removed; "
                                           "remove it in Resolve first")
            elif x["start"] < it["end"] and x["end"] > new_end:
                return outcome.blocked(f"{where}: {x['name']} on {x['track_type'][0].upper()}{x['track']} "
                                       f"at {session.to_tc(x['start'])} overlaps the frames being removed")
        plan.append(it)
    return plan


def _trim_one(p: session.Item, n: int, filler: dict[str, Any] | None, items: dict[str, Any],
              done: list[str], snapshot: str | None) -> dict[str, Any] | None:
    """Trim one item and ripple what follows; returns a failed result, or None if the timeline matches the plan."""
    before = _positions()
    old_end = before[p["id"]][1]
    new_end = old_end - n
    later = any(s >= old_end for s, _ in before.values())
    if later and not filler:
        return outcome.op("failed", reason="no timeline in the media pool is long enough to use as a filler",
                          changes={"trimmed": len(done)}, snapshot=snapshot)
    session.call("trim_tail", item_id=p["id"], frames=n)
    session.invalidate()
    if later:
        f = None
        try:
            f = timeline.append_one(filler["id"], "video", 0, n, new_end, p["track"])  # type: ignore[index]  # later implies filler (checked above)
            session.call("delete_items", item_ids=[f["id"]], ripple=True)
        except Exception as exc:
            session.invalidate()
            if f and f["id"] in _positions():
                session.call("delete_items", item_ids=[f["id"]], ripple=False)
            session.call("trim_tail", item_id=p["id"], frames=-n)  # put the end back; nothing else has moved
            session.invalidate()
            return outcome.op("failed", reason=f"{p['name']} at {session.to_tc(p['start'])}: "
                              f"ripple failed ({exc}); its end was restored",
                              changes={"trimmed": len(done)}, snapshot=snapshot)
        session.invalidate()
    after = _positions()
    wrong = []
    for i, (s, e) in before.items():
        want = (s, new_end) if i == p["id"] else (s - n, e - n) if s >= old_end else (s, e)
        if after.get(i) != want:
            wrong.append(f"{items.get(i, {}).get('name', i)} at {session.to_tc(s)}: "
                         f"expected {session.to_tc(want[0])}, "
                         f"got {session.to_tc(after[i][0]) if i in after else 'missing'}")
    wrong += [f"unexpected item {i} at {session.to_tc(after[i][0])}" for i in set(after) - set(before)]
    if wrong:
        return outcome.op("failed", False, {"trimmed": len(done)}, wrong[:5],
                          reason="timeline doesn't match the plan; restore from the snapshot if needed",
                          snapshot=snapshot)
    return None


def ripple_trim(a: dict[str, Any]) -> dict[str, Any]:
    n = a.get("tail_frames") or 0
    if n <= 0:
        return outcome.blocked("tail_frames must be a positive number of frames (this tool only shortens)")
    items = {x["id"]: x for x in session.items()}
    ids = list(dict.fromkeys(a["item_ids"]))
    missing = [i for i in ids if i not in items]
    if missing:
        return outcome.blocked(f"timeline item not found: {missing}")
    plan = _plan(items, ids, n)
    if isinstance(plan, dict):
        return plan

    def shift(x: session.Item) -> int:  # total frames x moves back once every planned trim is done
        return n * sum(1 for p in plan if p["end"] <= x["start"])
    rows = [{"item": p["name"], "track": f"V{p['track']}", "was": [session.to_tc(p["start"]), session.to_tc(p["end"])],
             "now": [session.to_tc(p["start"] - shift(p)), session.to_tc(p["end"] - n - shift(p))]}
            for p in sorted(plan, key=lambda x: x["start"])]
    moved = sum(1 for x in items.values() if x["id"] not in ids and x.get("type") != "transition" and shift(x))
    ends = max((x["end"] - shift(x) - (n if x["id"] in ids else 0) for x in items.values()), default=0)
    first_cut = min(p["end"] - n for p in plan)
    _, _, state = session.clock()
    warnings = []
    markers = session.call("list_markers") or {}
    if any(state["timeline_start_frame"] + int(float(f)) >= first_cut for f in markers):
        warnings.append("timeline ruler markers after the first trim may not move with the clips")
    if not a.get("confirm"):
        return outcome.preview({"trim": rows, "frames_each": n, "other_clips_moved_back": moved,
                                "timeline_ends": session.to_tc(ends)}, warnings)

    snapshot = (timeline.snapshot_timeline({"label": "before ripple trim"}).get("snapshot")
                if a.get("backup", True) else None)
    filler = _filler_source(n, prefer=snapshot, exclude={state["timeline"]})
    done: list[str] = []
    for p in sorted(plan, key=lambda x: x["start"], reverse=True):  # later first, so earlier positions don't change
        failed = _trim_one(p, n, filler, items, done, snapshot)
        if failed:
            return failed
        done.append(p["id"])
    final = _positions()
    rows = [{"item": items[i]["name"], "track": f"V{items[i]['track']}",
             "now": [session.to_tc(final[i][0]), session.to_tc(final[i][1])]}
            for i in sorted(done, key=lambda i: final[i][0])]
    return outcome.op("success", True, {"trimmed": len(done), "frames_each": n}, warnings, snapshot=snapshot,
                      items=rows, timeline_ends=session.to_tc(max((e for _, e in final.values()), default=0)))
