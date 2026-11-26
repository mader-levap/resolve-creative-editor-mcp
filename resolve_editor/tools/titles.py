"""Text+ titles: read their text and style, and turn plain titles into captions."""
import time
from typing import Any

from .. import outcome, session, timeline
from . import captions, clips

TEXT = "StyledText"  # the Text+ input that holds the words


def read_inputs(item_ids: list[str]) -> dict[str, dict[str, Any]]:
    """The bridge's read_titles: per id {kind: title|caption, inputs, animated} or {error}."""
    if not item_ids:
        return {}
    try:
        got = session.call("read_titles", item_ids=item_ids)
    except RuntimeError as exc:
        if "unknown op" not in str(exc):
            raise
        raise RuntimeError("the Resolve bridge is older than this server and can't read titles; restart the bridge "
                           "(Workspace > Scripts > resolve_bridge)") from exc
    return got if isinstance(got, dict) else {}


# When a Text+ runs, not how it looks: Resolve keeps a title's in step with its length (179 on a 180-frame title), but
# copied onto a caption's 900-frame Text+ they stop its text early (docs/ISSUES.md I-38).
TIMING = ("GlobalIn", "GlobalOut")


def text_style(inputs: dict[str, Any]) -> dict[str, Any]:
    """Every input but the text and the timing: what a caption copies from a title."""
    return {k: v for k, v in inputs.items() if k != TEXT and k not in TIMING}


def _timing_warning(item: session.Item, inputs: dict[str, Any]) -> str | None:
    """A caption placed past the frames its Text+ runs ([GlobalIn, GlobalOut] of its own timeline) shows nothing
    there, and Resolve's viewer says "No frame available for MediaOut1" (docs/ISSUES.md I-38)."""
    first, last = inputs.get("GlobalIn"), inputs.get("GlobalOut")
    src = item.get("source_start") or 0
    shown = (src, src + item["end"] - item["start"] - 1)  # frames of its own timeline the placement shows
    problems = []
    if isinstance(first, (int, float)) and shown[0] < first:
        problems.append(f"text starts at {session.to_tc(item['start'] + int(first) - src)} (GlobalIn {first:g}), "
                        f"{int(first) - shown[0]} frames after the caption starts")
    if isinstance(last, (int, float)) and shown[1] > last:
        problems.append(f"text stops at {session.to_tc(item['start'] + int(last) + 1 - src)} (GlobalOut {last:g}), "
                        f"{shown[1] - int(last)} frames before the caption ends")
    if not problems:
        return None
    return ("; ".join(problems) + "; Resolve shows 'No frame available for MediaOut1' there. Set GlobalIn to 0 and "
            "GlobalOut to its timeline's length - 1 (legacy__style_text_plus inputs)")


def _neat(v: Any) -> Any:
    """A float as people read it: Resolve's 0.034000000000000002 is 0.034."""
    return round(v, 6) if isinstance(v, float) else v


def _rgba(inputs: dict[str, Any], n: int) -> list[Any] | None:
    keys = [f"{c}{n}" for c in ("Red", "Green", "Blue", "Alpha")]
    return [_neat(inputs.get(k)) for k in keys] if any(k in inputs for k in keys) else None


def summary(inputs: dict[str, Any]) -> dict[str, Any]:
    """The style a person reads: font, style, size, centre, anchor, text colour and outline (shading element 2)."""
    center = inputs.get("Center")
    x, y = (_neat(center[0]), _neat(center[1])) if isinstance(center, list) and len(center) >= 2 else (None, None)
    anchor = inputs.get("VerticalTopCenterBottom")
    outline = None
    if inputs.get("Enabled2") == 1:
        outline = {"thickness": _neat(inputs.get("Thickness2")), "color": _rgba(inputs, 2)}
    return {"font": inputs.get("Font"), "style": inputs.get("Style"), "size": _neat(inputs.get("Size")), "x": x, "y": y,
            "anchor": "bottom" if anchor == 1 else ("center" if not anchor else anchor),
            "color": _rgba(inputs, 1), "outline": outline}


def _candidates(args: dict[str, Any]) -> tuple[list[session.Item], list[str]]:
    """Video items to look at, in time order, and ids given that aren't on the timeline."""
    video = [x for x in session.items() if x["track_type"] == "video" and x.get("type") != "transition"]
    if args.get("item_ids"):
        by_id = {x["id"]: x for x in video}
        return [by_id[i] for i in args["item_ids"] if i in by_id], [i for i in args["item_ids"] if i not in by_id]
    if args.get("start") is not None:
        start = session.to_frame(args["start"])
        video = [x for x in video if x["end"] > start]
    if args.get("end") is not None:
        end = session.to_frame(args["end"])
        video = [x for x in video if x["start"] < end]
    if args.get("track_index"):
        video = [x for x in video if x["track"] == args["track_index"]]
    return sorted(video, key=lambda x: (x["start"], x["track"])), []


def _titles(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(Text+ titles and captions in the selection with their inputs, items that aren't Text+ with the reason)."""
    found, unknown = _candidates(args)
    got = read_inputs([x["id"] for x in found])
    rows, others = [], [{"id": i, "reason": "not on this timeline"} for i in unknown]
    for x in found:
        r = got.get(x["id"]) or {"error": "no answer from the bridge"}
        if r.get("error"):
            others.append({"id": x["id"], "name": x["name"], "reason": r["error"]})
        else:
            rows.append({"item": x, "kind": r.get("kind"), "inputs": r.get("inputs") or {},
                         "animated": session.as_list(r.get("animated"))})
    return rows, others


def _details(ids: list[str]) -> dict[str, dict[str, Any]]:
    return {d["id"]: d for d in session.as_list(session.call("item_details", item_ids=ids))} if ids else {}


def _fades(detail: dict[str, Any]) -> dict[str, int]:
    fades = detail.get("fades") or {}
    return {"FadeIn": int(fades.get("FadeIn") or 0), "FadeOut": int(fades.get("FadeOut") or 0)}


def read_titles(args: dict[str, Any]) -> dict[str, Any]:
    """edit__read_titles: text, style, fades and state of the Text+ titles and captions in a selection."""
    rows, others = _titles(args)
    details = _details([r["item"]["id"] for r in rows])
    out = []
    for r in rows:
        x, d = r["item"], details.get(r["item"]["id"], {})
        row: dict[str, Any] = {"id": x["id"], "kind": r["kind"], "track": f"V{x['track']}",
                               "in": session.to_tc(x["start"]), "out": session.to_tc(x["end"]),
                               "frames": x["end"] - x["start"], "enabled": d.get("enabled", True) is not False,
                               "fades": _fades(d), "text": r["inputs"].get(TEXT, ""), "style": summary(r["inputs"])}
        warning = _timing_warning(x, r["inputs"]) if r["kind"] == "caption" else None
        if warning:
            row["warning"] = warning
        if args.get("all_inputs"):
            row["inputs"] = r["inputs"]
        if r["animated"]:
            row["animated"] = r["animated"]
        out.append(row)
    result: dict[str, Any] = {"count": len(out), "titles": out[: args.get("limit") or 200]}
    if args.get("item_ids") and others:
        result["not_titles"] = others
    return result


def _new_track_base() -> int:
    counts = session.get_state().get("track_counts") or {}
    return int(counts.get("video") or max((x["track"] for x in session.items() if x["track_type"] == "video"),
                                          default=0))


def _parts_by_card(placed: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for p in placed:
        out.setdefault(int(p.get("card") or 0), []).append(p)
    for parts in out.values():
        parts.sort(key=lambda p: p["start"])
    return out


def _whole(card: dict[str, Any], parts: list[dict[str, Any]]) -> bool:
    """The parts start at the card, follow each other and add up to its length."""
    at = card["record_frame"]
    for p in parts:
        if p["start"] != at:
            return False
        at += p["duration"]
    return at == card["record_frame"] + card["frames"]


def titles_to_captions(args: dict[str, Any]) -> dict[str, Any]:
    """edit__titles_to_captions: preview, then replace plain Text+ titles with captions (add_captions' kind) that keep
    each title's text, frames, track (or a new one), every Text+ input, fades and enabled state."""
    rows, others = _titles(args)
    if args.get("item_ids"):
        bad = others + [{"id": r["item"]["id"], "reason": "already a caption"} for r in rows if r["kind"] != "title"]
        if bad:
            return outcome.blocked("not plain Text+ titles: " + "; ".join(f"{b['id']} ({b['reason']})" for b in bad))
    titles = [r for r in rows if r["kind"] == "title"]
    if not titles:
        return outcome.blocked("no plain Text+ titles in the selection")
    ids = [r["item"]["id"] for r in titles]
    details = _details(ids)
    fps, _, state = session.clock()
    keep = args.get("keep_originals") is True
    tracks = sorted({r["item"]["track"] for r in titles})
    base = _new_track_base()
    target = {t: (base + n if keep else t) for n, t in enumerate(tracks, 1)}
    prefix = f"{state['timeline']} {time.strftime('%m%d-%H%M%S')}".strip()
    cards = []
    for n, r in enumerate(titles, 1):
        x, d = r["item"], details.get(r["item"]["id"], {})
        cards.append({"name": captions.card_name(prefix, n), "text": r["inputs"].get(TEXT, ""),
                      "record_frame": x["start"], "frames": x["end"] - x["start"], "inputs": text_style(r["inputs"]),
                      "track": target[x["track"]], "from_track": x["track"], "fades": _fades(d),
                      "enabled": d.get("enabled", True) is not False, "animated": r["animated"]})
    if not keep:
        for c in cards:
            hit = timeline.collides("video", c["track"], c["record_frame"], c["record_frame"] + c["frames"],
                                    ignore=ids)
            if hit:
                return outcome.blocked(f"V{c['track']} is busy at {session.to_tc(hit['start'])} ({hit['name']})")
    plan = [{"text": c["text"], "track": f"V{c['from_track']}", "to_track": f"V{c['track']}",
             "in": session.to_tc(c["record_frame"]), "out": session.to_tc(c["record_frame"] + c["frames"]),
             "frames": c["frames"], "fades": c["fades"], "enabled": c["enabled"], "style": summary(c["inputs"])}
            for c in cards]
    folder = args.get("folder") or captions.CAPTION_BIN
    warnings = ["each caption is a small timeline in the bin; its wording is edited there"]
    warnings += [f"keyframed inputs are not copied: {c['text']!r}: {', '.join(c['animated'])}"
                 for c in cards if c["animated"]]
    if any(c["fades"]["FadeIn"] or c["fades"]["FadeOut"] for c in cards):
        warnings.append("the captions are new clips: " + clips.FADES_NOT_SAVED)
    warnings += captions._parts_note(cards, fps)
    if not args.get("confirm"):
        return outcome.preview({"titles": plan, "count": len(cards), "bin": folder,
                                "originals": "disabled, captions on new tracks" if keep else "deleted (no ripple)"},
                               warnings + outcome.backup_notes(args))
    if not state.get("caption_parts"):
        return outcome.blocked("the Resolve bridge is older than this server and can't place long captions; "
                               "restart the bridge (Workspace > Scripts > resolve_bridge)")
    snapshot = (timeline.snapshot_timeline({"label": "before titles to captions"}).get("snapshot")
                if args.get("backup", True) else None)
    return _replace(cards, ids, keep, tracks, target, folder, snapshot, warnings)


def _replace(cards: list[dict[str, Any]], ids: list[str], keep: bool, tracks: list[int], target: dict[int, int],
             folder: str, snapshot: str | None, warnings: list[str]) -> dict[str, Any]:
    """The confirm half of titles_to_captions: originals away, captions in, fades and state, read back."""
    if keep:
        session.call("set_enabled", item_ids=ids, enabled=False)
    else:
        session.call("delete_items", item_ids=ids, ripple=False)
    session.invalidate()
    whole: dict[int, list[dict[str, Any]]] = {}  # card index -> its parts
    errors: list[str] = []
    try:
        if keep:
            for t in tracks:  # new tracks come in order, so they match the planned numbers
                got = session.call("add_track", track_type="video")["count"]
                if got != target[t]:
                    raise RuntimeError(f"the new track is V{got}, not V{target[t]}")
        for track in sorted({c["track"] for c in cards}):
            mine = [(i, c) for i, c in enumerate(cards) if c["track"] == track]
            payload = [{k: c[k] for k in ("name", "text", "record_frame", "frames", "inputs")} for _, c in mine]
            r = session.call("add_title_cards", cards=payload, folder=folder, track_index=track)
            parts = _parts_by_card(session.as_list(r.get("placed")))
            for n, (i, c) in enumerate(mine, 1):
                if _whole(c, parts.get(n, [])):
                    whole[i] = parts[n]
            if r.get("error"):
                errors.append(str(r["error"]))
                break
        fades_ok = _finish(cards, whole)
    except Exception as exc:  # the originals are gone or off: report, never leave without saying where things are
        errors.append(f"{type(exc).__name__}: {exc}")
        fades_ok = False
    session.invalidate()
    seen = {(c["name"], c["track"], c["start"]): c["text"] for c in captions._captions()}
    missing = [c for i, c in enumerate(cards)
               if i not in whole or seen.get((c["name"], c["track"], c["record_frame"])) != c["text"]]
    ok = not missing and not errors and fades_ok
    changes = {"captions_added": len(cards) - len(missing), "titles_" + ("disabled" if keep else "deleted"): len(ids)}
    if ok:
        return outcome.op("success", True, changes, warnings, snapshot=snapshot)
    back = f"the backup timeline is {snapshot}" if snapshot else "no backup was made"
    why = []
    if missing:
        why.append("not placed or not as expected: " + ", ".join(repr(c["text"]) for c in missing))
    if not fades_ok and not errors:
        why.append("fades or enabled state didn't read back as set")
    why += errors
    return outcome.op("partial", False, changes, warnings, snapshot=snapshot,
                      reason="; ".join(why) + f". The titles were {'disabled' if keep else 'deleted'}; {back}")


def _finish(cards: list[dict[str, Any]], whole: dict[int, list[dict[str, Any]]]) -> bool:
    """Fade-in on each caption's first part, fade-out on its last; disabled titles give disabled captions."""
    ok = True
    for i, parts in whole.items():
        c = cards[i]
        fade_in, fade_out = c["fades"]["FadeIn"], c["fades"]["FadeOut"]
        for n, p in enumerate(parts):
            want = (fade_in if n == 0 else 0, fade_out if n == len(parts) - 1 else 0)
            if any(want):
                r = session.call("set_fades", item_id=p["id"], fade_in=want[0], fade_out=want[1])
                got = r.get("fades") or {}
                ok &= (int(got.get("FadeIn", -1)), int(got.get("FadeOut", -1))) == want
        if not c["enabled"]:
            session.call("set_enabled", item_ids=[p["id"] for p in parts], enabled=False)
    return ok
