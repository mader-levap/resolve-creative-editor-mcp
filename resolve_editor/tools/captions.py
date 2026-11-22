"""Text+ captions and SRT files."""
import time

from .. import media, outcome, paths, session, timecode, timeline

CAPTION_BIN = "Captions (Resolve Creative Editor)"
MAX_CARD_FRAMES = 150  # Text+ is inserted at Resolve's standard 5 s length and can't be lengthened by script


def split_segments(segments, max_chars=42):
    """Split long lines at word boundaries, sharing time by length, and stop lines overlapping."""
    out = []
    for s in segments:
        words, text = s["text"].split(), s["text"].strip()
        if not text:
            continue
        lines, line = [], ""
        for w in words:
            if line and len(line) + 1 + len(w) > max_chars:
                lines.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        lines.append(line)
        total, t = sum(len(x) for x in lines), float(s["start"])
        for x in lines:
            end = t + (float(s["end"]) - float(s["start"])) * len(x) / total
            out.append({"start": round(t, 3), "end": round(end, 3), "text": x})
            t = end
    out.sort(key=lambda x: x["start"])
    for a, b in zip(out, out[1:]):
        a["end"] = min(a["end"], b["start"])
    return [x for x in out if x["end"] > x["start"]]


def _segments(a):
    if a.get("segments"):
        return split_segments(a["segments"], a.get("max_chars") or 42)
    if not a.get("path"):
        raise ValueError("provide segments, or a path to transcribe")
    args = {"path": a["path"], "model": a.get("model") or "base"}
    if a.get("language"):
        args["language"] = a["language"]
    return split_segments(media.run_media_tool("transcribe_audio", args)["segments"], a.get("max_chars") or 42)


def caption_cards(segments, fps, base, timeline, stamp=""):
    """Timeline names must be unique in a project, so each run's cards carry a time stamp."""
    cards, timeline = [], f"{timeline} {stamp}".strip()
    for n, s in enumerate(segments, 1):
        start, end = base + timecode.seconds_to_frames(s["start"], fps), base + timecode.seconds_to_frames(s["end"], fps)
        while end - start > 0:  # a card can be at most 5 s, so longer lines continue on a second card
            frames = min(end - start, MAX_CARD_FRAMES)
            cards.append({"name": f"{timeline} caption {n:04d}{'' if frames == end - start else '+'}"[:120],
                          "text": s["text"], "record_frame": start, "frames": frames})
            start += frames
    return cards


def add_captions(a):
    segments = _segments(a)
    fps, _, state = session.clock()
    base = session.to_frame(a["record"]) if a.get("record") is not None else state["timeline_start_frame"]
    cards = caption_cards(segments, fps, base, state["timeline"], time.strftime("%m%d-%H%M%S"))
    preview = [{"at": session.to_tc(c["record_frame"]), "frames": c["frames"], "text": c["text"]} for c in cards]
    if a.get("dry_run") or not a.get("confirm") or not cards:
        return outcome.preview({"captions": preview[: a.get("limit") or 20], "count": len(cards), "bin": CAPTION_BIN},
                               ["each caption is a small timeline in the bin; edit its text there"])
    track = a.get("track_index")
    if not track:
        track = session.call("add_track", track_type="video")["count"]
    for c in cards:
        hit = timeline.collides("video", track, c["record_frame"], c["record_frame"] + c["frames"])
        if hit:
            return outcome.blocked(f"V{track} is busy at {session.to_tc(hit['start'])}; leave track_index out to use a new track")
    style = {k: a[k] for k in ("font", "size", "y") if k in a}
    r = session.call("add_title_cards", cards=cards, folder=a.get("folder") or CAPTION_BIN, track_index=track, **style)
    session.invalidate()
    placed = session.as_list(r.get("placed"))
    ok = len(placed) == len(cards) and all(p["duration"] == c["frames"] for p, c in zip(placed, cards))
    return outcome.op("success" if ok else ("partial" if placed else "failed"), ok,
                      {"captions_added": len(placed), "track": f"V{track}"}, [r["error"]] if r.get("error") else [])


def _stamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(segments):
    rows = [s for s in segments if s["text"].strip()]
    return "".join(f"{i}\n{_stamp(s['start'])} --> {_stamp(s['end'])}\n{s['text'].strip()}\n\n"
                   for i, s in enumerate(rows, 1))


def export_srt(a):
    output = paths.new_output(a, ".srt")
    with open(output, "w", encoding="utf-8") as f:
        f.write(to_srt(_segments(a)))
    return outcome.op("success", True, {"file_written": output}, output=output)
