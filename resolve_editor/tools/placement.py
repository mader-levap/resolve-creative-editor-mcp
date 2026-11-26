"""Placing Media Pool clips."""
import math
from fractions import Fraction
from typing import Any

from .. import outcome, session, timecode, timeline


def _timeline_frames(clip: dict[str, Any], source: int, fps: Fraction) -> tuple[int, bool, str | None]:
    """(timeline frames, whether exact, warning) for `source` frames of a clip. Resolve converts a clip whose frame
    rate differs from the timeline's: a 30 fps clip takes twice as many frames on a 60 fps timeline (docs/ISSUES.md
    I-30). A length that isn't whole is rounded up for the checks; an unknown rate keeps the source length."""
    try:
        rate = timecode.parse_fps(clip.get("fps"))
    except ValueError:
        rate = Fraction(0)
    if not rate:
        return source, True, (f"{clip['name']}: frame rate unknown, so its length on the timeline is taken as "
                              f"{source} frames unchecked")
    length = source * fps / rate
    if length.denominator == 1:
        return int(length), True, None
    return math.ceil(length), False, (f"{clip['name']}: {source} frames at {float(rate):g} fps are "
                                      f"{float(length):.2f} timeline frames; checked as {math.ceil(length)}, and "
                                      "Resolve may round it by a frame")


def _split_pairs(plan: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(video, audio) parts of one call with the same clip, source range and record frame. Resolve links only the
    parts of one append, which share a track number, so such parts come out unlinked (docs/ISSUES.md I-37)."""
    def key(p: dict[str, Any]) -> tuple[Any, ...]:
        return p["clip"], p["start_frame"], p["end_frame"], p["record_frame"]
    audio = [p for p in plan if p["media_type"] == 2]
    pairs = []
    for v in (p for p in plan if p["media_type"] == 1):
        a = next((a for a in audio if key(a) == key(v)), None)
        if a:
            audio.remove(a)
            pairs.append((v, a))
    return pairs


def _pair_label(v: dict[str, Any], a: dict[str, Any]) -> str:
    return (f"video on {timeline.track_label('video', v['track_index'])} and audio on "
            f"{timeline.track_label('audio', a['track_index'])} of {v['name']} at {v['at']}")


def _link(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> tuple[int, list[str]]:
    """Link each placed pair and read it back: (pairs linked, warnings)."""
    def find(p: dict[str, Any], kind: str) -> session.Item | None:
        return next((x for x in session.items() if x["track_type"] == kind and x["start"] == p["record_frame"]
                     and x["track"] == p["track_index"] and x["name"] == p["name"]), None)
    done, warnings = 0, []
    for v, a in pairs:
        xv, xa = find(v, "video"), find(a, "audio")
        if not xv or not xa:
            continue  # not placed: the count of placed clips already says so
        ids = [xv["id"], xa["id"]]
        try:
            session.call("link_items", item_ids=ids)
        except RuntimeError as exc:
            warnings.append(f"{_pair_label(v, a)} are not linked ({exc}): {ids[0]}, {ids[1]}")
            continue
        back = {d["id"]: d.get("linked") or [] for d in session.as_list(session.call("item_details", item_ids=ids))}
        if ids[1] in back.get(ids[0], []) and ids[0] in back.get(ids[1], []):
            done += 1
        else:
            warnings.append(f"{_pair_label(v, a)} are not linked (Resolve didn't link them): {ids[0]}, {ids[1]}; "
                            "link them in Resolve")
    return done, warnings


def place_clips(args: dict[str, Any]) -> dict[str, Any]:
    """edit__place_clips: preview, then place Media Pool clips at exact frames and tracks; refuses to
    overwrite, also between the clips of one call. Lengths on the timeline are in timeline frames."""
    warnings: list[str]
    plan, warnings, exact = [], [], []
    planned: list[tuple[str, int, int, int, int, str]] = []  # kind, track, start, end, n, name of earlier clips
    fps, _, _ = session.clock()
    for n, spec in enumerate(args["clips"], 1):
        clip = timeline.find_clip(spec["clip"])
        first = spec.get("start_frame") or 0
        frames = int(float(clip.get("frames") or 0))  # 0 when unknown: then only the bridge can check
        last = spec.get("end_frame") or frames
        record, track = session.to_frame(spec["record"]), spec.get("track_index") or 1
        if last <= first:
            return outcome.blocked(f"{clip['name']}: end_frame must be greater than start_frame")
        if first < 0 or (frames and last > frames):  # end_frame is exclusive (docs/ISSUES.md I-28)
            return outcome.blocked(f"{clip['name']}: source range {first}-{last} is outside the clip "
                                   f"(0-{frames or '?'})")
        span, whole, note = _timeline_frames(clip, last - first, fps)
        if note:
            warnings.append(note)
        kinds = {1: ["video"], 2: ["audio"]}.get(spec.get("media_type"), ["video", "audio"])
        for kind in kinds:
            label = timeline.track_label(kind, track)
            hit = timeline.collides(kind, track, record, record + span)
            if hit:
                return outcome.blocked(f"{clip['name']} would overwrite {hit['name']} on {label} "
                                       f"at {session.to_tc(hit['start'])}")
            # Resolve places a clip that overlaps an earlier one of the same call shifted and shortened (I-27)
            other = next((p for p in planned if p[:2] == (kind, track) and record < p[3]
                          and p[2] < record + span), None)
            if other:
                return outcome.blocked(f"clip {n} ({clip['name']}) would overlap clip {other[4]} ({other[5]}) on "
                                       f"{label} at {session.to_tc(record)}; clips of one call "
                                       "can't overlap")
        planned += [(kind, track, record, record + span, n, clip["name"]) for kind in kinds]
        row = {"clip": clip["id"], "name": clip["name"], "start_frame": first, "end_frame": last,
               "record_frame": record, "track_index": track, "media_type": spec.get("media_type"),
               "at": session.to_tc(record), "frames": span, "source_frames": last - first}
        if span != last - first or not whole:
            row["clip_fps"] = float(timecode.parse_fps(clip.get("fps")))
        plan.append(row)
        exact.append(whole)
    link = args.get("link", True) is not False
    pairs = _split_pairs(plan)
    if not link:
        warnings += [f"{_pair_label(v, a)} stay unlinked (link=false)" for v, a in pairs]
    if not args.get("confirm"):
        return outcome.preview(plan, warnings + [f"{_pair_label(v, a)} will be linked" for v, a in pairs if link])
    session.call("append_clips", clips=[{k: p[k] for k in ("clip", "start_frame", "end_frame", "record_frame",
                                                            "track_index", "media_type") if p[k] is not None}
                                        for p in plan])
    session.invalidate()
    # landed: at its frame on its track with the expected length, within a frame when that isn't whole (I-30)
    landed = sum(1 for p, whole in zip(plan, exact)
                 if any(x["start"] == p["record_frame"] and x["track"] == p["track_index"] and x["name"] == p["name"]
                        and abs(x["duration"] - p["frames"]) <= (0 if whole else 1) for x in session.items()))
    changes: dict[str, Any] = {"clips_placed": landed}
    ok = landed == len(plan)
    if link and pairs:
        session.invalidate()
        linked, problems = _link(pairs)
        changes["linked"] = linked
        warnings += problems
        ok = ok and not problems
    return outcome.op("success" if ok else "partial", ok, changes, warnings=warnings)
