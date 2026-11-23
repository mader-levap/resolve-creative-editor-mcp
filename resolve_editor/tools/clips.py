"""Clip settings: enabled, fades, transitions, speed, grade."""
from typing import Any

from .. import outcome, session


def set_enabled(a: dict[str, Any]) -> dict[str, Any]:
    r = session.call("set_enabled", item_ids=a["item_ids"], enabled=bool(a["enabled"]))
    got = [d.get("enabled") for d in session.as_list(session.call("item_details", item_ids=a["item_ids"]))]
    ok = all(e == bool(a["enabled"]) for e in got)
    return outcome.op("success" if ok else "partial", ok, {"items_changed": r.get("changed")})


FADES_NOT_SAVED = ("Resolve bug (seen on free 21.2, Text+ titles): fades set by script on a clip whose fade was never "
                   "dragged by hand show and play but are lost when Resolve restarts, even after saving. Once the user "
                   "has dragged any fade handle on that clip, script fades on it are saved. Read-back can't tell the "
                   "two apart, so ask the user to drag a fade on each clip first unless they already have.")


def set_fades(a: dict[str, Any]) -> dict[str, Any]:
    fade_in, fade_out = a.get("fade_in"), a.get("fade_out")
    if fade_in is None and fade_out is None:
        return outcome.blocked("give fade_in and/or fade_out")
    # Resolve's SetFades sets both ends, so keep the current length of whichever end was not given.
    current = {}
    if fade_in is None or fade_out is None:
        current = {d["id"]: d.get("fades") or {}
                   for d in session.as_list(session.call("item_details", item_ids=a["item_ids"]))}
    results = []
    for i in a["item_ids"]:
        now = current.get(i, {})
        want_in = int(now.get("FadeIn") or 0) if fade_in is None else fade_in
        want_out = int(now.get("FadeOut") or 0) if fade_out is None else fade_out
        r = session.call("set_fades", item_id=i, fade_in=want_in, fade_out=want_out)
        fades = r.get("fades") or {}
        results.append(int(fades.get("FadeIn", -1)) == want_in and int(fades.get("FadeOut", -1)) == want_out)
    return outcome.op("success" if all(results) else "partial", all(results), {"items_changed": sum(results)},
                      warnings=[FADES_NOT_SAVED])


def expected_span(cut: int, alignment: str, frames: int) -> tuple[int, int]:
    """Where Resolve 21.2 puts a transition (live T2, ISSUES.md): left ends at the cut, right starts there, center
    puts an odd frame before it."""
    if alignment == "left":
        return cut - frames, cut
    if alignment == "right":
        return cut, cut + frames
    return cut - (frames + 1) // 2, cut + frames // 2


def _clips() -> dict[str, tuple[Any, ...]]:
    return {x["id"]: (x["track_type"], x["track"], x["start"], x["end"], x.get("source_start"))
            for x in session.items() if x.get("type") != "transition"}


def add_transition(a: dict[str, Any]) -> dict[str, Any]:
    options = {"type": a.get("type") or "Cross Dissolve", "category": a.get("category") or "simple",
               "position": a.get("position") or "end", "alignment": a.get("alignment") or "center"}
    if a.get("duration"):
        options["duration"] = a["duration"]
    target = next((x for x in session.items() if x["id"] == a["item_id"]), None)
    if target is None or target.get("type") == "transition":
        return outcome.blocked(f"no clip with id {a['item_id']} on the current timeline")
    cut = target["end"] if options["position"] == "end" else target["start"]
    before = _clips()
    r = session.call("add_transition", item_id=a["item_id"], options=options)
    session.invalidate()
    differs, unchecked, got = _check_transition(r.get("id"), target, cut, options, before)
    frames = got.get("duration") or r.get("duration")
    start, end = got.get("start", r.get("start")), got.get("end", r.get("end"))
    ok = None if not differs and unchecked else not differs
    warnings = differs + ([f"could not read back the transition's {', '.join(unchecked)}"] if unchecked else [])
    def tc(frame: Any) -> str | None:
        return None if frame is None else session.to_tc(frame)
    return outcome.op("partial" if differs else "success", ok, {"transition": r.get("name"), "frames": frames},
                      warnings, transition_id=r.get("id"), cut=tc(cut), start=tc(start), end=tc(end))


def _check_transition(tid: Any, target: session.Item, cut: int, options: dict[str, Any],
                      before: dict[str, tuple[Any, ...]]) -> tuple[list[str], list[str], dict[str, Any]]:
    """Compare what Resolve made with the request (ISSUES.md I-04): what differs, what couldn't be read, the item."""
    differs: list[str] = []
    got: dict[str, Any] = next((dict(x) for x in session.items() if x["id"] == tid), {})
    if not got:
        return [f"transition {tid} not found on the timeline after adding it"], [], {}
    where, want = (got.get("track_type"), got.get("track")), (target["track_type"], target["track"])
    if got.get("type") != "transition":
        differs.append(f"item {tid} is a {got.get('type')}, not a transition")
    if where != want:
        differs.append(f"on track {where[0]} {where[1]}, expected {want[0]} {want[1]}")
    frames = options.get("duration") or got["end"] - got["start"]
    if got["end"] - got["start"] != frames:
        differs.append(f"length {got['end'] - got['start']} frames, expected {frames}")
    span = expected_span(cut, options["alignment"], frames)
    if (got["start"], got["end"]) != span:
        differs.append(f"span {got['start']}-{got['end']}, expected {span[0]}-{span[1]} "
                       f"({options['alignment']} of the cut at {cut})")
    details = session.as_list(session.call("item_details", item_ids=[tid]))
    props = (details[0].get("properties") if details else None) or {}
    unchecked = []
    for key, name in (("type", "TransitionType"), ("category", "TransitionCategory"),
                      ("alignment", "TransitionAlignment")):
        if props.get(name) is None:
            unchecked.append(key)
        elif str(props[name]) != str(options[key]):
            differs.append(f"{key} {props[name]}, expected {options[key]}")
    after = _clips()
    changed = sorted(i for i in set(before) | set(after) if before.get(i) != after.get(i))
    if changed:
        differs.append(f"clips changed by the transition: {', '.join(changed)}")
    return differs, unchecked, got


def set_speed(a: dict[str, Any]) -> dict[str, Any]:
    if not a.get("confirm"):
        return outcome.preview({"item": a["item_id"], "percentage": a["percentage"]},
                               ["the clip keeps its timeline length, so it shows more or less of the source"])
    r = session.call("set_speed", item_id=a["item_id"], percentage=float(a["percentage"]))
    session.invalidate()
    got = (r.get("speed") or {}).get("Percentage")
    ok = got is not None and abs(float(got) - float(a["percentage"])) < 0.01
    return outcome.op("success" if ok else "failed", ok, {"speed": got})


def copy_grade(a: dict[str, Any]) -> dict[str, Any]:
    if not a.get("confirm"):
        return outcome.preview({"from": a["from_id"], "to": a["to_ids"]}, ["replaces the grade on the target clips"])
    ok = session.call("copy_grade", from_id=a["from_id"], to_ids=a["to_ids"]).get("ok")
    return outcome.op("success" if ok else "failed", None, {"clips_graded": len(a["to_ids"]) if ok else 0},
                      ["grades can't be read back by script; check the Color page"])
