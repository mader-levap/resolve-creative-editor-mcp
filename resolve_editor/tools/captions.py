"""Text+ captions and SRT files."""
import re
import time
from fractions import Fraction
from itertools import pairwise
from typing import Any

from .. import media, outcome, paths, prefs, rebuild, session, timecode, timeline
from . import titles

CAPTION_BIN = "Captions (Resolve Creative Editor)"
# Text+ inputs per anchor. VerticalTopCenterBottom 1 puts the block's bottom at y, so extra lines grow upward
# (live 2026-11-23, 21.2.0.6: bottom row the same for 1 and 3 lines; the default 0 centres the block on y).
ANCHORS: dict[str, dict[str, int]] = {"bottom": {"VerticalTopCenterBottom": 1}, "center": {}}


LINE_SPLITS = ("stack", "sequence")


def _wrap(words: list[str], max_chars: int) -> list[str]:
    """Greedy wrap at word boundaries; a word longer than max_chars stays one line."""
    lines, line = [], ""
    for w in words:
        if line and len(line) + 1 + len(w) > max_chars:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    return lines + [line]


def _balance(words: list[str], n: int) -> list[str]:
    """The same words on n lines, the longest as short as possible (so no long line over a short one)."""
    best: dict[tuple[int, int], tuple[int, list[str]]] = {}

    def go(i: int, k: int) -> tuple[int, list[str]]:  # words[i:] on k lines
        if (i, k) not in best:
            if k == 1:
                line = " ".join(words[i:])
                best[i, k] = (len(line), [line])
            else:
                options = []
                for j in range(i + 1, len(words) - k + 2):
                    head = " ".join(words[i:j])
                    width, rest = go(j, k - 1)
                    options.append((max(len(head), width), [head] + rest))
                best[i, k] = min(options, key=lambda o: o[0])
        return best[i, k]

    return go(0, min(n, len(words)))[1]


def _screens(text: str, max_chars: int, line_split: str, max_lines: int) -> list[str]:
    """What one segment shows, in order: one line each ("sequence"), or up to max_lines lines one under another."""
    lines = _wrap(text.split(), max_chars)
    if line_split == "sequence":
        return lines
    screens = []
    for k in range(0, len(lines), max_lines):
        group = lines[k:k + max_lines]
        screens.append("\n".join(_balance(" ".join(group).split(), len(group))))
    return screens


def split_segments(segments: list[dict[str, Any]], max_chars: int = 42, line_split: str = "stack",
                   max_lines: int = 2) -> list[dict[str, Any]]:
    """Wrap long text at word boundaries: by default up to max_lines lines one under another in one caption, more
    than that in captions one after another; line_split="sequence" puts each line in its own caption. A segment's
    time is shared by length, and captions don't overlap."""
    if line_split not in LINE_SPLITS:
        raise ValueError(f"line_split must be one of {', '.join(LINE_SPLITS)}, not {line_split!r}")
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1")
    out: list[dict[str, Any]] = []
    for s in segments:
        text = s["text"].strip()
        if not text:
            continue
        screens = _screens(text, max_chars, line_split, max_lines)
        total, t = sum(len(x) for x in screens), float(s["start"])
        for x in screens:
            end = t + (float(s["end"]) - float(s["start"])) * len(x) / total
            out.append({"start": round(t, 3), "end": round(end, 3), "text": x})
            t = end
    out.sort(key=lambda x: x["start"])
    for a, b in pairwise(out):
        a["end"] = min(a["end"], b["start"])
    return [x for x in out if x["end"] > x["start"]]


def _segments(args: dict[str, Any]) -> list[dict[str, Any]]:
    split: dict[str, Any] = {"max_chars": args.get("max_chars") or 42, "line_split": args.get("line_split") or "stack",
                             "max_lines": 2 if args.get("max_lines") is None else args["max_lines"]}
    if args.get("segments"):
        return split_segments(args["segments"], **split)
    if not args.get("path"):
        raise ValueError("provide segments, or a path to transcribe")
    transcribe = {"path": args["path"], "model": args.get("model") or "base"}
    if args.get("language"):
        transcribe["language"] = args["language"]
    return split_segments(media.run_media_tool("transcribe_audio", transcribe)["segments"], **split)


def card_name(prefix: str, n: int) -> str:
    """The name of caption n's own timeline, "<timeline> <stamp> caption NNNN" (CAPTION_NAME finds it); a long prefix
    is cut before the caption number."""
    suffix = f" caption {n:04d}"
    return prefix[:120 - len(suffix)] + suffix


def caption_cards(segments: list[dict[str, Any]], fps: Fraction | float, base: int, timeline: str,
                  stamp: str = "") -> list[dict[str, Any]]:
    """One card per caption. Timeline names must be unique in a project, so each run's cards carry a time stamp.
    The bridge places a card longer than the inserted title in parts."""
    cards, prefix = [], f"{timeline} {stamp}".strip()
    for n, s in enumerate(segments, 1):
        start, end = (base + timecode.seconds_to_frames(s["start"], fps),
                      base + timecode.seconds_to_frames(s["end"], fps))
        if end > start:
            cards.append({"name": card_name(prefix, n), "text": s["text"], "record_frame": start,
                          "frames": end - start})
    return cards


def _complete(cards: list[dict[str, Any]], placed: list[dict[str, Any]]) -> int:
    """Captions whose parts start at the caption, follow each other without gaps and add up to its length."""
    done = 0
    for i, c in enumerate(cards, 1):
        at = c["record_frame"]
        for p in sorted((p for p in placed if p.get("card") == i), key=lambda p: p["start"]):
            if p["start"] != at:
                break
            at += p["duration"]
        done += at == c["record_frame"] + c["frames"]
    return done


def _parts_note(cards: list[dict[str, Any]], fps: Fraction) -> list[str]:
    """Which captions will be placed in parts, from Standard Generator Duration (docs/ISSUES.md I-24)."""
    length = prefs.generator_frames(fps)
    if not length:
        return []
    long = [c for c in cards if c["frames"] > length]
    if not long:
        return []
    parts = sum(-(-c["frames"] // length) for c in long)
    return [f"captions longer than {prefs.describe(prefs.generator_duration())} ({length} frames) are placed in parts: "
            f"{len(long)} caption(s) in {parts} parts (Standard Generator Duration, {prefs.NOTE})"]


EXPLICIT = {"font": "Font", "style": "Style", "size": "Size"}  # add_captions arguments and the Text+ inputs they set


def _style(args: dict[str, Any]) -> dict[str, Any]:
    """What add_title_cards gets: font, style, size, x and y as given, and `inputs`: every input of the `match` title
    but its text, the anchor (unless match brings one and none is given), then the caller's inputs. The bridge sets
    inputs last, so an explicit argument also replaces the same input from match."""
    anchor = args.get("anchor")
    if anchor is not None and anchor not in ANCHORS:
        raise ValueError(f"anchor must be bottom or center, not {anchor!r}")
    own = args.get("inputs") or {}
    if not isinstance(own, dict):
        raise ValueError("inputs must be an object of Text+ input ids and values")
    if titles.TEXT in own:
        raise ValueError(f"inputs can't set {titles.TEXT}: the text comes from the segments")
    for key in titles.TIMING:
        if key in own:
            raise ValueError(f"inputs can't set {key}: it decides when the Text+ runs, and a caption keeps its full "
                             "length (docs/ISSUES.md I-38)")
    inputs: dict[str, Any] = {}
    if args.get("match"):
        got = titles.read_inputs([args["match"]]).get(args["match"]) or {}
        if got.get("error") or not got:
            raise ValueError(f"match: {args['match']} is not a Text+ title or caption ({got.get('error')})")
        inputs.update(titles.text_style(got.get("inputs") or {}))
    if anchor is not None or not args.get("match"):
        inputs.pop("VerticalTopCenterBottom", None)
        inputs.update(ANCHORS[anchor or "bottom"])
    inputs.update(own)
    style: dict[str, Any] = {k: args[k] for k in ("font", "style", "size", "x", "y") if args.get(k) is not None}
    for k, name in EXPLICIT.items():
        if k in style and name in inputs:
            inputs[name] = style[k]
    if ("x" in style or "y" in style) and isinstance(inputs.get("Center"), list):
        center = inputs["Center"]
        inputs["Center"] = [style.get("x", center[0]), style.get("y", center[1])]
    if inputs:
        style["inputs"] = inputs
    return style


def _shown(style: dict[str, Any]) -> dict[str, Any]:
    """The style as Text+ inputs, for the preview."""
    shown = dict(style.get("inputs") or {})
    shown.update({name: style[k] for k, name in EXPLICIT.items() if k in style})
    if "x" in style or "y" in style:
        center = shown.get("Center") or [0.5, 0.5]
        shown["Center"] = [style.get("x", center[0]), style.get("y", center[1])]
    return shown


def add_captions(args: dict[str, Any]) -> dict[str, Any]:
    """edit__add_captions: preview, then Text+ captions from segments or a transcription, one small timeline
    each, on a new track or the one given."""
    style = _style(args)
    segments = _segments(args)
    fps, _, state = session.clock()
    base = session.to_frame(args["record"]) if args.get("record") is not None else state["timeline_start_frame"]
    cards = caption_cards(segments, fps, base, state["timeline"], time.strftime("%m%d-%H%M%S"))
    preview = [{"at": session.to_tc(c["record_frame"]), "frames": c["frames"], "text": c["text"]} for c in cards]
    if args.get("dry_run") or not args.get("confirm") or not cards:
        return outcome.preview({"captions": preview[: args.get("limit") or 20], "count": len(cards),
                                "bin": args.get("folder") or CAPTION_BIN, "style": _shown(style)},
                               ["each caption is a small timeline in the bin; edit its text there",
                                "a caption longer than Resolve's inserted title is placed in parts sharing its text"]
                               + _parts_note(cards, fps))
    if not state.get("caption_parts"):
        return outcome.blocked("the Resolve bridge is older than this server and can't place long captions; "
                               "restart the bridge (Workspace > Scripts > resolve_bridge)")
    track = args.get("track_index")
    if not track:
        track = session.call("add_track", track_type="video")["count"]
    for c in cards:
        hit = timeline.collides("video", track, c["record_frame"], c["record_frame"] + c["frames"])
        if hit:
            return outcome.blocked(f"V{track} is busy at {session.to_tc(hit['start'])}; "
                                   "leave track_index out to use a new track")
    r = session.call("add_title_cards", cards=cards, folder=args.get("folder") or CAPTION_BIN, track_index=track,
                     **style)
    session.invalidate()
    placed = session.as_list(r.get("placed"))
    complete = _complete(cards, placed)
    ok = complete == len(cards)
    return outcome.op("success" if ok else ("partial" if placed else "failed"), ok,
                      {"captions_added": complete, "parts": len(placed), "track": f"V{track}"},
                      [r["error"]] if r.get("error") else [])


def _stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(segments: list[dict[str, Any]]) -> str:
    """SubRip text of the segments, numbered from 1; segments without text are left out."""
    rows = [s for s in segments if s["text"].strip()]
    return "".join(f"{i}\n{_stamp(s['start'])} --> {_stamp(s['end'])}\n{s['text'].strip()}\n\n"
                   for i, s in enumerate(rows, 1))


def export_srt(args: dict[str, Any]) -> dict[str, Any]:
    """edit__export_srt: write segments, or a transcription, to a new .srt file (never overwrites one)."""
    output = paths.new_output(args, ".srt")
    with open(output, "w", encoding="utf-8") as f:
        f.write(to_srt(_segments(args)))
    return outcome.op("success", True, {"file_written": output}, output=output)


# Placed captions are clips of their own small timelines, named "<timeline> <stamp> caption NNNN"; the parts of a
# caption longer than the inserted title share that name (add_title_cards).
CAPTION_NAME = re.compile(r" caption \d{4}$")


def _captions(with_text: bool = True) -> list[dict[str, Any]]:
    """Every caption on the current timeline, in time order: n (from 1), name, track, start, end, parts, text."""
    groups: dict[tuple[int, str], list[session.Item]] = {}
    for x in session.items():
        if x["track_type"] == "video" and x.get("type") != "transition" and CAPTION_NAME.search(x["name"] or ""):
            groups.setdefault((x["track"], x["name"]), []).append(x)
    rows: list[dict[str, Any]] = []
    for (track, name), parts in groups.items():
        parts.sort(key=lambda x: x["start"])
        rows.append({"name": name, "track": track, "start": parts[0]["start"], "end": parts[-1]["end"],
                     "parts": parts})
    rows.sort(key=lambda c: (c["start"], c["track"]))
    texts: dict[str, Any] = {}
    if with_text and rows:
        try:
            texts = session.call("caption_texts", item_ids=[c["parts"][0]["id"] for c in rows])
        except RuntimeError as exc:
            if "unknown op" not in str(exc):
                raise
            raise RuntimeError("the Resolve bridge is older than this server and can't read caption text; restart "
                               "the bridge (Workspace > Scripts > resolve_bridge)") from exc
    for n, c in enumerate(rows, 1):
        got = texts.get(c["parts"][0]["id"]) or {}
        c.update(n=n, text=got.get("text", ""), text_error=got.get("error"))
    return rows


def _row(c: dict[str, Any]) -> dict[str, Any]:
    row = {"n": c["n"], "text": c["text"], "track": f"V{c['track']}", "in": session.to_tc(c["start"]),
           "out": session.to_tc(c["end"]), "frames": c["end"] - c["start"], "ids": [x["id"] for x in c["parts"]],
           "name": c["name"]}
    if c.get("text_error"):
        row["text_error"] = c["text_error"]
    return row


def list_captions(args: dict[str, Any]) -> dict[str, Any]:
    """edit__list_captions: captions placed by add_captions, in time order, filtered by text, time range or
    track."""
    rows = _captions()
    if args.get("text"):
        rows = [c for c in rows if args["text"].lower() in c["text"].lower()]
    if args.get("start") is not None:
        start = session.to_frame(args["start"])
        rows = [c for c in rows if c["end"] > start]
    if args.get("end") is not None:
        end = session.to_frame(args["end"])
        rows = [c for c in rows if c["start"] < end]
    if args.get("track_index"):
        rows = [c for c in rows if c["track"] == args["track_index"]]
    return {"count": len(rows), "captions": [_row(c) for c in rows[: args.get("limit") or 200]]}


def shift_captions(args: dict[str, Any]) -> dict[str, Any]:
    """Move a caption (all its parts) by a signed time and, unless following=false, every later caption on its track.
    Clips can't be moved by script, so each part is rebuilt with its settings (rebuild.py), all in one go."""
    if (args.get("seconds") is None) == (args.get("frames") is None):
        return outcome.blocked("give the shift as seconds or frames (signed: negative is earlier), not both")
    fps, _, state = session.clock()
    shift = args["frames"] if args.get("frames") is not None else timecode.seconds_to_frames(args["seconds"], fps)
    if not shift:
        return outcome.blocked("the shift is 0 frames, nothing to move")
    rows = _captions()
    key = args["caption"]
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        target = next((c for c in rows if c["n"] == int(key)), None)
        if not target:
            return outcome.blocked(f"no caption {key}: this timeline has {len(rows)} (see list_captions)")
    else:
        target = next((c for c in rows if key in [x["id"] for x in c["parts"]]), None)
        if not target:
            return outcome.blocked(f"{key} is not a caption on this timeline (see list_captions)")
    following = args.get("following", True) is not False
    moved = [c for c in rows if c is target or (following and c["track"] == target["track"]
                                                 and c["start"] > target["start"])]
    ids = {x["id"] for c in moved for x in c["parts"]}
    if min(c["start"] for c in moved) + shift < state["timeline_start_frame"]:
        return outcome.blocked(f"caption {target['n']} would start before the timeline start "
                               f"({session.to_tc(state['timeline_start_frame'])})")
    by_id = {x["id"]: c for c in rows for x in c["parts"]}
    for c in moved:
        for x in c["parts"]:
            hit = timeline.collides("video", c["track"], x["start"] + shift, x["end"] + shift, ignore=ids)
            if hit:
                other = by_id.get(hit["id"])
                what = f"caption {other['n']} (\"{other['text']}\")" if other else hit["name"]
                hint = ("; use following=true to move the later captions too"
                        if other and not following and other["start"] > target["start"]
                        else "; use a smaller shift or move that one first")
                return outcome.blocked(f"caption {c['n']} (\"{c['text']}\") would land on {what} at "
                                       f"{session.to_tc(hit['start'])}{hint}")
    plan: list[dict[str, Any]] = []
    for c in moved:
        for x in c["parts"]:
            part = rebuild.plan(x["id"], False, lambda it: (it["source_start"],
                                it["source_start"] + it["duration"], it["start"] + shift, it["track"]),
                                moving=ids)
            if isinstance(part, str):
                return outcome.blocked(part)
            plan += part
    rows_out = [{"n": c["n"], "text": c["text"], "track": f"V{c['track']}", "from": session.to_tc(c["start"]),
                 "to": session.to_tc(c["start"] + shift), "parts": len(c["parts"])} for c in moved]
    if not args.get("confirm"):
        return outcome.preview({"captions": rows_out, "shift_frames": shift, "following": following},
                               ["each part is rebuilt with its settings (keyframes are not copied)",
                                *outcome.backup_notes(args)])
    result = rebuild.run(plan, args.get("backup", True))
    result["captions"] = rows_out
    if result["_operation"]["status"] == "success":  # read back: every caption at its new start, all parts there
        after = {(c["name"], c["start"]): len(c["parts"]) for c in _captions(with_text=False)}
        missing = [r for r, c in zip(rows_out, moved, strict=True)
                   if after.get((c["name"], c["start"] + shift)) != len(c["parts"])]
        if missing:
            result["_operation"].update(status="partial", verification="contradiction")
            result["_operation"]["warnings"].append(
                f"not where expected after the move: captions {', '.join(str(r['n']) for r in missing)}")
    return result


def caption_usage() -> tuple[list[str], dict[str, list[str]]]:
    """(Every caption timeline in the project, caption timeline name -> the timelines that place it), from the
    bridge's caption_usage."""
    try:
        r = session.call("caption_usage")
    except RuntimeError as exc:
        if "unknown op" not in str(exc):
            raise
        raise RuntimeError("the Resolve bridge is older than this server and can't see which timelines use a "
                           "caption; restart the bridge (Workspace > Scripts > resolve_bridge)") from exc
    used = r.get("used_by") if isinstance(r.get("used_by"), dict) else {}
    return session.as_list(r.get("captions")), {k: session.as_list(v) for k, v in used.items()}


def _pick(rows: list[dict[str, Any]], keys: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The captions named by n (from list_captions) or by the id of any part, each once; and the keys that match
    none."""
    picked: list[dict[str, Any]] = []
    unknown = []
    for key in keys:
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            hit = next((c for c in rows if c["n"] == int(key)), None)
        else:
            hit = next((c for c in rows if key in [x["id"] for x in c["parts"]]), None)
        if hit is None:
            unknown.append(str(key))
        elif hit not in picked:
            picked.append(hit)
    return picked, unknown


def remove_captions(args: dict[str, Any]) -> dict[str, Any]:
    """edit__remove_captions: preview, then delete every part of the captions (no ripple). By default a backup is
    made, and it still places the caption timelines, so they stay. With delete_timelines=true no backup is made and
    their own timelines are deleted too, unless a timeline (an older backup included) still places them: deleting
    one that a timeline places leaves that clip Media Offline (live 2026-11-25)."""
    rows = _captions()
    picked, unknown = _pick(rows, list(args.get("captions") or []))
    if unknown:
        return outcome.blocked(f"no caption {', '.join(unknown)} on this timeline (see list_captions)")
    if not picked:
        return outcome.blocked("give the captions to remove: n from list_captions or the id of any part")
    current = session.get_state()["timeline"]
    ids = {x["id"] for c in picked for x in c["parts"]}
    drop = args.get("delete_timelines") is True
    delete, kept = [], []
    if drop:
        known, used = caption_usage()
        names = [n for n in dict.fromkeys(c["name"] for c in picked) if n in known]  # a timeline gone already: skip
        left = {x["name"] for x in session.items() if x["track_type"] == "video" and x["id"] not in ids}
        for name in names:
            users = [t for t in used.get(name, []) if t != current] + ([current] if name in left else [])
            if users:
                kept.append({"name": name, "used_by": users})
            else:
                delete.append(name)
    plan = [{"n": c["n"], "text": c["text"], "track": f"V{c['track']}", "in": session.to_tc(c["start"]),
             "out": session.to_tc(c["end"]), "parts": len(c["parts"])} for c in picked]
    if drop:
        notes = ["the parts are deleted without ripple",
                 "no backup is made: it would still place the caption timelines, and deleting them would leave "
                 "its clips Media Offline"]
    else:
        notes = ["; ".join(["the parts are deleted without ripple", *outcome.backup_notes(args)]),
                 "the caption timelines stay, because the backup places them; after deleting the backup, "
                 "delete_unused_captions removes them"]
    if not args.get("confirm"):
        return outcome.preview({"captions": plan, "timelines_deleted": delete, "timelines_kept": kept}, notes)
    backup = not drop and args.get("backup", True) is not False
    snapshot = timeline.snapshot_timeline({"label": "before removing captions"}).get("snapshot") if backup else None
    session.call("delete_items", item_ids=sorted(ids), ripple=False)
    session.invalidate()
    still = [x["id"] for x in session.items() if x["id"] in ids]
    if still:
        return outcome.op("partial", False, {"parts_deleted": len(ids) - len(still)}, snapshot=snapshot,
                          reason=f"{len(still)} part(s) are still on the timeline; no caption timeline was deleted")
    if delete:
        session.call("delete_timeline", names=delete)
    changes = {"captions_removed": len(picked), "parts_deleted": len(ids), "timelines_deleted": len(delete)}
    return outcome.op("success", True, changes, snapshot=snapshot, captions=plan, kept=kept)


def delete_unused_captions(args: dict[str, Any]) -> dict[str, Any]:
    """edit__delete_unused_captions: preview, then delete the caption timelines (from add_captions) that no timeline
    in the project places any more."""
    names, used = caption_usage()
    unused = [n for n in names if not used.get(n)]
    if not args.get("confirm"):
        return outcome.preview({"count": len(unused), "timelines": unused[: args.get("limit") or 200]},
                               ["caption timelines are found by name (\"... caption NNNN\") with a Text+ on V1",
                                "Media Pool entries only; there is no backup, but Resolve's Edit > Undo may work"])
    if unused:
        session.call("delete_timeline", names=unused)
    left, _ = caption_usage()
    gone = [n for n in unused if n not in left]
    ok = len(gone) == len(unused)
    return outcome.op("success" if ok else "partial", ok, {"timelines_deleted": len(gone)},
                      **({} if ok else {"reason": f"still there: {', '.join(n for n in unused if n in left)}"}))
