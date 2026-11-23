"""Clip settings: enabled, fades, transitions, speed, grade."""
from typing import Any

from .. import outcome, session, timecode, timeline


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
    duration = a.get("duration")
    if duration is not None:  # 0 isn't "not given", and bool counts as int in Python (ISSUES.md I-08)
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            return outcome.blocked(f"duration must be a whole number of frames above 0, or left out for Resolve's "
                                   f"default (got {duration!r})")
        options["duration"] = duration
    target = next((x for x in session.items() if x["id"] == a["item_id"]), None)
    if target is None or target.get("type") == "transition":
        return outcome.blocked(f"no clip with id {a['item_id']} on the current timeline")
    cut = target["end"] if options["position"] == "end" else target["start"]
    audio, notes = _linked_audio(target, options["position"], cut, a.get("include_linked", True) is not False)
    audio_type = a.get("audio_type") or AUDIO_CROSSFADE
    if not a.get("confirm"):  # nothing is written before the user approves (ISSUES.md I-06)
        plan = _transition_plan(target, cut, options)
        if audio:
            span = {"span": plan["span"]} if "span" in plan else {}
            plan["linked"] = [{"track": _label(x), "type": audio_type, **span} for x in audio]
        return outcome.preview(plan, ["a backup timeline is made first", *notes])
    snapshot = (timeline.snapshot_timeline({"label": "before transition"}).get("snapshot")
                if a.get("backup", True) else None)
    before = _clips()
    r = session.call("add_transition", item_id=a["item_id"], options=options)
    session.invalidate()
    differs, unchecked, got = _check_transition(r.get("id"), target, cut, options, before)
    frames = got.get("duration") or r.get("duration")
    start, end = got.get("start", r.get("start")), got.get("end", r.get("end"))
    rows: list[dict[str, Any]] = []
    for x in audio:  # the linked audio gets a matching crossfade (ISSUES.md I-07)
        ao = {"type": audio_type, "category": "audio", "position": options["position"],
              "alignment": options["alignment"], "duration": options.get("duration") or frames}
        try:
            ar = session.call("add_transition", item_id=x["id"], options=ao)
        except Exception as exc:  # the video transition stays: say so, and how to undo it
            differs.append(f"audio crossfade on {_label(x)} refused ({exc}); the video transition {r.get('id')} "
                           f"stays: remove it with legacy__delete_items or restore {snapshot or 'a backup'}")
            rows.append({"track": _label(x), "error": str(exc)})
            continue
        session.invalidate()
        d, u, g = _check_transition(ar.get("id"), x, cut, ao, before)
        differs += [f"audio crossfade on {_label(x)}: {w}" for w in d]
        unchecked += [f"{k} (audio crossfade on {_label(x)})" for k in u]
        rows.append({"track": _label(x), "transition_id": ar.get("id"), "start": _tc(g.get("start", ar.get("start"))),
                     "end": _tc(g.get("end", ar.get("end")))})
    ok = None if not differs and unchecked else not differs
    warnings = differs + ([f"could not read back the transition's {', '.join(unchecked)}"] if unchecked else []) + notes
    return outcome.op("partial" if differs else "success", ok, {"transition": r.get("name"), "frames": frames},
                      warnings, transition_id=r.get("id"), cut=_tc(cut), start=_tc(start), end=_tc(end),
                      snapshot=snapshot, **({"linked": rows} if rows else {}))


AUDIO_CROSSFADE = "Cross Fade +3 dB"  # verified live in test T5a


def _tc(frame: Any) -> str | None:
    return None if frame is None else session.to_tc(frame)


def _label(x: session.Item) -> str:
    return f"{x['track_type'][0].upper()}{x['track']}"


def _linked_audio(target: session.Item, position: str, cut: int,
                  include: bool) -> tuple[list[session.Item], list[str]]:
    """The linked audio items that get a crossfade, and warnings for those that don't (ISSUES.md I-07)."""
    if target["track_type"] != "video":
        return [], []
    details = session.as_list(session.call("item_details", item_ids=[target["id"]]))
    ids = (details[0].get("linked") if details else None) or []
    items = {x["id"]: x for x in session.items()}
    planned, notes = [], []
    for x in (items[i] for i in ids if i in items and items[i]["track_type"] == "audio"):
        own = x["end"] if position == "end" else x["start"]
        if own != cut:
            notes.append(f"linked audio on {_label(x)} {'ends' if position == 'end' else 'starts'} at "
                         f"{session.to_tc(own)}, not at the cut ({session.to_tc(cut)}): no crossfade added there")
        elif not include:
            notes.append(f"linked audio on {_label(x)} keeps a hard cut at {session.to_tc(cut)}; "
                         "include_linked=true adds a crossfade")
        else:
            planned.append(x)
    return planned, notes


def _transition_plan(target: session.Item, cut: int, options: dict[str, Any]) -> dict[str, Any]:
    plan: dict[str, Any] = {"clip": target["name"], "track": _label(target),
                            "position": options["position"], "cut": session.to_tc(cut), "type": options["type"],
                            "alignment": options["alignment"],
                            "frames": options.get("duration") or "Resolve's default (Preferences)"}
    if options.get("duration"):
        plan["span"] = [session.to_tc(f) for f in expected_span(cut, options["alignment"], options["duration"])]
    plan["spare_source_frames"] = _spare_frames(target, cut)
    return plan


def _spare_frames(target: session.Item, cut: int) -> dict[str, Any]:
    """Unused source frames on each side of the cut, for the user to judge; which side needs how many isn't known."""
    track = [x for x in session.items() if x.get("type") != "transition"
             and (x["track_type"], x["track"]) == (target["track_type"], target["track"])]
    outgoing = next((x for x in track if x["end"] == cut), None)
    incoming = next((x for x in track if x["start"] == cut), None)
    ids = [x["id"] for x in (outgoing, incoming) if x]
    details = {d["id"]: d for d in session.as_list(session.call("item_details", item_ids=ids))} if ids else {}
    media = {m.get("id"): m for m in session.media_pool()}
    fps, _, _ = session.clock()

    def spare(x: session.Item | None, side: str) -> int | str:
        if x is None:
            return f"no clip {'ends' if side == 'after' else 'starts'} at the cut"
        d = details.get(x["id"]) or {}
        m = media.get(d.get("media_id"))
        speed = float(((d.get("speed") or {}).get("Percentage")) or 100)
        if not m or x.get("source_start") is None:
            return "unknown: not a media-pool clip"
        if abs(float(timecode.parse_fps(m.get("fps"))) - float(fps)) > 0.001 or abs(speed - 100) > 0.001:
            return "unknown: the clip's frame rate or speed differs from the timeline"
        if side == "before":
            return x["source_start"]
        return int(float(m.get("frames") or 0)) - x["source_start"] - x["duration"]
    return {"after the outgoing clip": spare(outgoing, "after"), "before the incoming clip": spare(incoming, "before")}


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
