"""Live checks against a REAL DaVinci Resolve. Not part of the automated tests.

Requires Resolve open with a project and the bridge running. Everything happens in a new bin _RCE_LIVE_<time> (the
test clip, the scratch timeline of the same name, its backups and the captions); your current timeline is compared
before and after. At the end the bin you had selected is current again and the run's bin is deleted with everything
in it, unless --keep is given. Run: python tests/live/live_resolve.py
One or more areas only: --only captions,markers (areas: clips, transitions, markers, captions, reads).
"""
import os
import pathlib
import subprocess
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from resolve_editor import dispatch, paths, prefs, session  # noqa: E402  (needs the sys.path line above)
from resolve_editor.tools import clips as clip_tools  # noqa: E402

RESULTS: list[tuple[str, bool]] = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  :: {str(detail)[:400]}"))


def B(op, **a):
    return session.call(op, **a)


def _refusal(op, **a):
    """The error text of a call expected to be refused, or "" when it succeeds."""
    try:
        B(op, **a)
    except RuntimeError as exc:
        return str(exc)
    return ""


def status(r):
    return r.get("_operation", {}).get("status")


def transitions(clip, start, name):
    """A valid transition must land exactly where asked; refusals must be the ones seen live
    (docs/ISSUES.md I-12, T3/T4)."""
    pairs = {"valid": (1000, 30), "no spare": (1200, 300), "misspelled": (1400, 30)}  # record offset, first source
    r = dispatch.run("place_clips", {"clips": [c for at, src in pairs.values() for c in (
        {"clip": clip, "start_frame": src, "end_frame": src + 60, "record": start + at},
        {"clip": clip, "start_frame": 120, "end_frame": 180, "record": start + at + 60})],
        "confirm": True, "timeline": name})
    check("transition clips placed", status(r) == "success", r)
    outgoing = {x["start"] - start: x for x in session.items() if x["track_type"] == "video"}

    def add(case, **extra):
        return dispatch.run("add_transition", {"item_id": outgoing[pairs[case][0]]["id"], "duration": 10,
                                               "confirm": True, "timeline": name, **extra})

    def span(cut, alignment):
        return [session.to_tc(f) for f in clip_tools.expected_span(cut, alignment, 10)]

    cut = start + 1060
    r = add("valid")
    linked = (r.get("linked") or [{}])[0]
    verdict = (status(r), r.get("_operation", {}).get("verification"))
    check("valid transition passes", verdict == ("success", "passed"), r)
    check("valid transition at the exact span", [r.get("start"), r.get("end")] == span(cut, "center"), r)
    check("linked audio crossfade at the same span", [linked.get("start"), linked.get("end")] == span(cut, "center"), r)
    cut = start + 1260  # the outgoing clip ends at the source's last frame
    r = add("no spare")
    check("no spare frames, centred: refused naming the side",
          status(r) == "failed" and "after the outgoing clip" in str(r.get("reason")), r)
    r = add("no spare", alignment="left")
    check("no spare frames, left: made at the exact span",
          status(r) == "success" and [r.get("start"), r.get("end")] == span(cut, "left"), r)
    r = add("misspelled", type="Cross Disolve")
    check("misspelled type: refused pointing at the type", status(r) == "failed" and "type" in str(r.get("reason")), r)


def captions(start, name):
    """Each caption covers its time exactly, in parts no longer than the inserted title, whatever Standard Generator
    Duration is; when the saved preference can be read, the title length must match it (docs/ISSUES.md I-24)."""
    title = prefs.generator_frames(30)  # the scratch timeline is 30 fps
    long_end = 2.2 + (title / 30 + 2 if title else 6.8)  # longer than one title when the length is known
    segs: list[dict[str, Any]] = [{"start": 0.5, "end": 2.0, "text": "First caption"},
                                  {"start": 2.2, "end": long_end, "text": "A long one"},
                                  {"start": long_end + 0.5, "end": long_end + 2, "text": "Last words"}]
    r = dispatch.run("add_captions", {"segments": segs, "confirm": True, "timeline": name,
                                      "folder": name})  # the run's bin
    check("captions placed with exact lengths", status(r) == "success", r)
    track = max(x["track"] for x in session.items() if x["track_type"] == "video")
    parts: dict[str, list[Any]] = {}
    for x in sorted(session.items(), key=lambda x: x["start"]):
        if x["track_type"] == "video" and x["track"] == track:
            parts.setdefault(x["name"], []).append(x)
    rows = [sorted(v, key=lambda x: x["start"]) for _, v in sorted(parts.items())]
    want = [(start + round(s["start"] * 30), round(s["end"] * 30) - round(s["start"] * 30)) for s in segs]
    got = [(p[0]["start"], sum(x["duration"] for x in p)) for p in rows]
    gapless = all(a["end"] == b["start"] for p in rows for a, b in zip(p, p[1:], strict=False))
    check("each caption covers its time without gaps", got == want and gapless, (want, got))
    full = {x["duration"] for p in rows for x in p[:-1]}  # every part but the last is one whole title
    check("parts are one title long, the last no longer",
          len(full) <= 1 and all(p[-1]["duration"] <= min(full or {p[-1]["duration"]}) for p in rows), rows)
    if title:
        check(f"inserted title matches Standard Generator Duration ({title} frames)", full == {title}, full)
    shift_captions(name, track, len(rows[1]))


def shift_captions(name, track, long_parts):
    """Captions are found by their text and moved with every later one by default, parts together; other tracks stay;
    a move onto another caption is refused."""
    def listed():
        return {c["n"]: (c["text"], session.to_frame(c["in"]), len(c["ids"]))
                for c in dispatch.run("list_captions", {"track_index": track})["captions"]}

    def others():
        return sorted((x["track_type"], x["track"], x["start"]) for x in session.items() if x["track"] != track
                      or x["track_type"] != "video")

    found = dispatch.run("list_captions", {"text": "LONG"})["captions"]
    check("list_captions finds a caption by its text",
          [(c["n"], c["text"], len(c["ids"])) for c in found] == [(2, "A long one", long_parts)], found)
    before, rest = listed(), others()
    r = dispatch.run("shift_captions", {"caption": 1, "seconds": 3})
    check("shift preview lists the caption and every later one",
          status(r) == "preview" and [c["n"] for c in r["plan"]["captions"]] == [1, 2, 3], r)
    r = dispatch.run("shift_captions", {"caption": 1, "seconds": 3, "confirm": True, "timeline": name})
    after = listed()
    check("shift moves the caption and every later one, parts together",
          status(r) == "success" and after == {n: (t, f + 90, k) for n, (t, f, k) in before.items()}, (r, after))
    check("shift leaves other tracks alone", others() == rest)
    r = dispatch.run("shift_captions", {"caption": 3, "seconds": 1, "following": False, "confirm": True,
                                        "timeline": name})
    moved = listed()
    check("shift with following=false moves only that caption",
          status(r) == "success" and moved[3][1] == after[3][1] + 30 and moved[2] == after[2], (r, moved))
    r = dispatch.run("shift_captions", {"caption": 2, "seconds": -1})
    check("shift onto another caption is refused, naming it",
          status(r) == "blocked" and "caption 1" in str(r.get("reason")) and listed() == moved, r)


AREAS = ("clips", "transitions", "markers", "captions", "reads")


def clips(clip, start, name):
    """Place, move and trim keep every setting; audio, fades and enabling read back."""
    def guard():
        return B("get_state")["timeline"] == name or sys.exit("wrong timeline, stopping")

    r = dispatch.run("place_clips", {"clips": [{"clip": clip, "start_frame": 30, "end_frame": 90, "record": start},
                                        {"clip": clip, "start_frame": 120, "end_frame": 180,
                                         "record": start + 60}]})
    check("place_clips previews first", status(r) == "preview", r)
    guard()
    r = dispatch.run("place_clips", {"clips": [{"clip": clip, "start_frame": 30, "end_frame": 90, "record": start},
                                        {"clip": clip, "start_frame": 120, "end_frame": 180, "record": start + 60}],
                              "confirm": True, "timeline": name})
    check("place_clips with linked audio", status(r) == "success", r)
    r = dispatch.run("place_clips", {"clips": [{"clip": clip, "start_frame": 0, "end_frame": 10,
                                                "record": start + 5}], "confirm": True, "timeline": name})
    check("place_clips refuses overwrite", status(r) == "blocked", r)

    video = sorted([x for x in session.items() if x["track_type"] == "video"], key=lambda x: x["start"])
    first, second = video[0], video[1]
    B("set_item_properties", item_id=first["id"], properties={"ZoomX": 1.4, "ZoomY": 1.4, "Opacity": 75.0})
    B("set_grade", item_ids=[first["id"]], slope="1.1 1.0 0.9", saturation=1.2)
    B("set_fades", item_id=first["id"], fade_in=6, fade_out=0)
    B("review_item", item_id=first["id"], color="Orange", flag="Blue")
    audio_of_first = [x for x in session.items() if x["track_type"] == "audio" and x["start"] == first["start"]][0]
    r = dispatch.run("set_audio", {"item_ids": [audio_of_first["id"]], "volume_db": -6})
    check("set_audio read-back", status(r) == "success", r)

    r = dispatch.run("move_item", {"item_id": first["id"], "record": start + 200})
    check("move preview lists linked audio", status(r) == "preview" and len(r["plan"]["move"]) == 2, r)
    guard()
    r = dispatch.run("move_item", {"item_id": first["id"], "record": start + 200, "confirm": True,
                                   "timeline": name})
    check("move keeps settings and verifies", status(r) == "success", r)
    moved = [c["new_id"] for c in r.get("_operation", {}).get("changes", {}).get("replaced", [])]
    details = {d["id"]: d for d in B("item_details", item_ids=moved)} if moved else {}
    vid: dict[str, Any] = next((d for d in details.values() if d.get("type") == "video"), {})
    aud: dict[str, Any] = next((d for d in details.values() if d.get("type") == "audio"), {})
    check("moved video kept zoom/opacity/fade/colour",
          (vid.get("properties") or {}).get("ZoomX") == 1.4 and (vid.get("properties") or {}).get("Opacity") == 75
          and int((vid.get("fades") or {}).get("FadeIn", 0)) == 6 and vid.get("color") == "Orange", vid)
    check("moved audio kept volume",
          abs(float((aud.get("properties") or {}).get("AudioVolume", 0)) + 6) < 0.01, aud)
    check("moved clips relinked", set(vid.get("linked") or []) == {aud.get("id")}, vid.get("linked"))
    probe = B("probe_color", item_id=vid["id"]) if vid else {}
    check("moved video still has its grade node", (probe or {}).get("item_nodes", 0) >= 1, probe)
    check("staging tracks removed", B("get_state") and len({x["track"] for x in session.items()
                                                             if x["track_type"] == "video"}) == 1)

    r = dispatch.run("trim_item", {"item_id": vid["id"], "head_frames": 5, "tail_frames": 10, "confirm": True,
                                   "timeline": name})
    trimmed = (r.get("_operation", {}).get("changes", {}).get("replaced") or [{}])[0]
    check("trim preserves and verifies", status(r) == "success" and trimmed.get("to", [None, 0])[1] == 45, r)

    r = dispatch.run("set_fades", {"item_ids": [second["id"]], "fade_in": 0, "fade_out": 8})
    check("set_fades read-back", status(r) == "success", r)
    r = dispatch.run("set_enabled", {"item_ids": [second["id"]], "enabled": False})
    check("disable clip read-back", status(r) == "success", r)
    dispatch.run("set_enabled", {"item_ids": [second["id"]], "enabled": True})


def markers(clip_path, start):
    """Timeline markers by frame and timecode; beat analysis."""
    r = dispatch.run("add_markers", {"markers": [{"at": start + 15, "name": "a"},
                                                 {"at": session.to_tc(start + 30), "name": "b"}]})
    check("markers by frame and timecode", status(r) == "success" and set(B("list_markers")) >= {"15", "30"}, r)
    r = dispatch.run("add_audio_markers", {"path": clip_path, "kind": "beats", "dry_run": True})
    check("beat analysis runs", status(r) == "planned", r)


def reads(start, folder):
    """Summary, range inspection and an OTIO export."""
    r = dispatch.run("timeline_summary", {})
    check("summary counts transitions separately", "transitions" in r and r["overlaps"]["count"] == 0, r)
    r = dispatch.run("inspect_range", {"start": start, "end": start + 400, "details": True})
    check("inspect_range details", r["count"] > 0, r)
    out = os.path.join(folder, f"rce_live_{int(time.time())}.otio")
    r = dispatch.run("export_timeline", {"format": "OTIO", "output": out})
    check("OTIO export", status(r) == "success", r)


def main():
    keep = "--keep" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else list(AREAS)
    if set(only) - set(AREAS):
        sys.exit(f"unknown area(s) {', '.join(sorted(set(only) - set(AREAS)))}; choose from {', '.join(AREAS)}")
    only = [x for x in AREAS if x in only]  # always in this order
    folder = os.path.join(paths.DIR, "validation")
    os.makedirs(folder, exist_ok=True)
    clip_path = os.path.join(folder, "rce_live_clip.mp4")
    if not os.path.exists(clip_path):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=12",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=12", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", clip_path], check=True)
    state = B("get_state")
    original = sys.argv[sys.argv.index("--return-to") + 1] if "--return-to" in sys.argv else state["timeline"]
    B("set_current_timeline", name=original)
    before = (B("list_timeline_items", track_type="video"), B("list_timeline_items", track_type="audio"))
    name = "_RCE_LIVE_" + time.strftime("%H%M%S")  # the run's bin and its scratch timeline

    def test_clips():
        return sum(1 for m in B("list_media") if m["name"] == "rce_live_clip.mp4")
    clips_before, start_bin = test_clips(), state.get("current_bin") or ""
    try:
        B("create_bin", bin=name)
        B("use_bin", bin=name)  # new clips, timelines and backups go here
        clip = B("import_media", paths=[clip_path])[0]["id"]
        B("create_timeline", name=name)
        B("set_scratch_fps", timeline=name, fps=30)  # the generated clip's rate, whatever the project's is
        B("set_current_timeline", name=name)
        session.invalidate()
        start = B("get_state")["timeline_start_frame"]
        for area in only:
            print(f"--- {area}")
            {"clips": lambda: clips(clip, start, name), "transitions": lambda: transitions(clip, start, name),
             "markers": lambda: markers(clip_path, start), "captions": lambda: captions(start, name),
             "reads": lambda: reads(start, folder)}[area]()
    except SystemExit:
        raise
    except Exception as exc:
        check("live run aborted", False, exc)
    finally:
        if original.startswith("_RCE_"):  # never leave the user on a scratch timeline
            original = next((t for t in B("list_timelines") if not t.startswith("_RCE_")), original)
        B("set_current_timeline", name=original)
        session.invalidate()
        after = (B("list_timeline_items", track_type="video"), B("list_timeline_items", track_type="audio"))
        check("your current timeline is unchanged", after == before)
        B("use_bin", bin=start_bin)
        if not keep:
            try:
                print("cleanup", B("delete_bin", bin=name, with_contents=True))
            except RuntimeError as exc:  # not created, or Resolve refusing: reported by the checks below
                print("cleanup failed:", exc)
            left = [t for t in B("list_timelines") if t.startswith(name)]
            check("nothing of the run is left: no bin, timeline or test clip",
                  not left and test_clips() == clips_before and "no bin" in _refusal("delete_bin", bin=name),
                  (left, test_clips(), clips_before))
            for t in left:  # a timeline made outside the run's bin; the check above already failed
                print("cleanup", t, B("delete_scratch", timeline=t))
        now = B("get_state").get("current_bin")  # checked after the cleanup, which could change it
        check("the bin you had selected is current again", now == start_bin, (now, start_bin))
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
