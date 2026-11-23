"""Text+ captions and SRT files."""
import time
from fractions import Fraction
from typing import Any

from .. import media, outcome, paths, prefs, session, timecode, timeline

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
    for a, b in zip(out, out[1:], strict=False):
        a["end"] = min(a["end"], b["start"])
    return [x for x in out if x["end"] > x["start"]]


def _segments(a: dict[str, Any]) -> list[dict[str, Any]]:
    split: dict[str, Any] = {"max_chars": a.get("max_chars") or 42, "line_split": a.get("line_split") or "stack",
                             "max_lines": 2 if a.get("max_lines") is None else a["max_lines"]}
    if a.get("segments"):
        return split_segments(a["segments"], **split)
    if not a.get("path"):
        raise ValueError("provide segments, or a path to transcribe")
    args = {"path": a["path"], "model": a.get("model") or "base"}
    if a.get("language"):
        args["language"] = a["language"]
    return split_segments(media.run_media_tool("transcribe_audio", args)["segments"], **split)


def caption_cards(segments: list[dict[str, Any]], fps: Fraction | float, base: int, timeline: str,
                  stamp: str = "") -> list[dict[str, Any]]:
    """One card per caption. Timeline names must be unique in a project, so each run's cards carry a time stamp; a long
    name is cut before the caption number. The bridge places a card longer than the inserted title in parts."""
    cards, prefix = [], f"{timeline} {stamp}".strip()
    for n, s in enumerate(segments, 1):
        start, end = (base + timecode.seconds_to_frames(s["start"], fps),
                      base + timecode.seconds_to_frames(s["end"], fps))
        if end > start:
            suffix = f" caption {n:04d}"
            cards.append({"name": prefix[:120 - len(suffix)] + suffix, "text": s["text"], "record_frame": start,
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
    """Which captions will be placed in parts, from Standard Generator Duration (ISSUES.md I-24)."""
    length = prefs.generator_frames(fps)
    if not length:
        return []
    long = [c for c in cards if c["frames"] > length]
    if not long:
        return []
    parts = sum(-(-c["frames"] // length) for c in long)
    return [f"captions longer than {prefs.describe(prefs.generator_duration())} ({length} frames) are placed in parts: "
            f"{len(long)} caption(s) in {parts} parts (Standard Generator Duration, {prefs.NOTE})"]


def add_captions(a: dict[str, Any]) -> dict[str, Any]:
    anchor = a.get("anchor") or "bottom"
    if anchor not in ANCHORS:
        raise ValueError(f"anchor must be bottom or center, not {anchor!r}")
    segments = _segments(a)
    fps, _, state = session.clock()
    base = session.to_frame(a["record"]) if a.get("record") is not None else state["timeline_start_frame"]
    cards = caption_cards(segments, fps, base, state["timeline"], time.strftime("%m%d-%H%M%S"))
    preview = [{"at": session.to_tc(c["record_frame"]), "frames": c["frames"], "text": c["text"]} for c in cards]
    if a.get("dry_run") or not a.get("confirm") or not cards:
        return outcome.preview({"captions": preview[: a.get("limit") or 20], "count": len(cards), "bin": CAPTION_BIN},
                               ["each caption is a small timeline in the bin; edit its text there",
                                "a caption longer than Resolve's inserted title is placed in parts sharing its text"]
                               + _parts_note(cards, fps))
    if not state.get("caption_parts"):
        return outcome.blocked("the Resolve bridge is older than this server and can't place long captions; "
                               "restart the bridge (Workspace > Scripts > resolve_bridge)")
    track = a.get("track_index")
    if not track:
        track = session.call("add_track", track_type="video")["count"]
    for c in cards:
        hit = timeline.collides("video", track, c["record_frame"], c["record_frame"] + c["frames"])
        if hit:
            return outcome.blocked(f"V{track} is busy at {session.to_tc(hit['start'])}; "
                                   "leave track_index out to use a new track")
    style: dict[str, Any] = {k: a[k] for k in ("font", "size", "y") if k in a}
    if ANCHORS[anchor]:
        style["inputs"] = ANCHORS[anchor]
    r = session.call("add_title_cards", cards=cards, folder=a.get("folder") or CAPTION_BIN, track_index=track, **style)
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
    rows = [s for s in segments if s["text"].strip()]
    return "".join(f"{i}\n{_stamp(s['start'])} --> {_stamp(s['end'])}\n{s['text'].strip()}\n\n"
                   for i, s in enumerate(rows, 1))


def export_srt(a: dict[str, Any]) -> dict[str, Any]:
    output = paths.new_output(a, ".srt")
    with open(output, "w", encoding="utf-8") as f:
        f.write(to_srt(_segments(a)))
    return outcome.op("success", True, {"file_written": output}, output=output)
