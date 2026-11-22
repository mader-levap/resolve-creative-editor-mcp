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


def add_transition(a: dict[str, Any]) -> dict[str, Any]:
    options = {"type": a.get("type") or "Cross Dissolve", "category": a.get("category") or "simple",
               "position": a.get("position") or "end", "alignment": a.get("alignment") or "center"}
    if a.get("duration"):
        options["duration"] = a["duration"]
    r = session.call("add_transition", item_id=a["item_id"], options=options)
    session.invalidate()
    ok = not a.get("duration") or r.get("duration") == a["duration"]
    return outcome.op("success" if ok else "partial", ok, {"transition": r.get("name"), "at": session.to_tc(r["start"]),
                                                           "frames": r.get("duration")}, transition_id=r.get("id"))


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
