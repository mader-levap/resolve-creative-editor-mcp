"""Fakes and sample data for the tests, which need no Resolve installation.

Every test file imports this module before resolve_editor: it points the bridge folder at a temporary one, so no
test can reach Resolve or write to the user's folder (docs/ISSUES.md I-14).
These prove the logic (planning, refusals, rollback order, frame maths). They cannot prove that Resolve itself
behaves the same way; see tests/live_resolve.py for the checks that need a real Resolve.
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["RESOLVE_BRIDGE_DIR"] = tempfile.mkdtemp()
# Resolve's saved preferences: never the user's own file, so tests don't depend on their settings
os.environ["RESOLVE_USER_PREFS"] = os.path.join(os.environ["RESOLVE_BRIDGE_DIR"], "config.user.xml")
from resolve_editor import bridge, session  # noqa: E402  (only after the line above)


def item(id, start, dur, name="a.mp4", src=0, track=1, kind="video", type=None):
    return {"id": id, "name": name, "start": start, "end": start + dur, "duration": dur, "source_start": src,
            "track": track, "track_type": kind, "type": type or kind}


class FakeResolve:
    """Just enough of the bridge to exercise edit__ logic. fail_on makes one op fail once."""

    def __init__(self, items, fail_on=None, details=None, fps=30):
        self.items, self.fail_on, self.calls, self.n, self.fps = items, dict(fail_on or {}), [], 0, fps
        self.tracks, self.timelines = {"video": 1, "audio": 1}, ["T"]
        self.renamed_markers = 0  # unnamed clip markers copy_settings had to name (Resolve 21.2)
        self.drop_marker: str | None = None  # a clip marker copy_settings loses without saying so (the I-23 bug)
        self.copies: list[dict[str, Any]] = []  # copy_settings arguments, in order
        self.clip_markers_by_source = True  # the bridge copies clip markers at their source frames (I-23)
        self.track_counts = True  # get_state reports how many tracks there are (I-11)
        self.markers: dict[int, dict[str, Any]] = {}  # timeline markers by frame from the start, as Resolve keys them
        # captions: the inserted Text+ length, whether the bridge places long captions in parts, a part it refuses
        self.title_frames, self.caption_parts, self.refuse_part = 300, True, None
        self.timeline_fps = 30  # fps above is the clips' rate
        self.media_frames = 300  # length of the one media pool clip
        self.parts: list[dict[str, Any]] = []
        self.settings: dict[str, dict[str, Any]] = {
            x["id"]: {"properties": {"ZoomX": 1.5}, "fades": {"FadeIn": 4, "FadeOut": 0},
                      "color": "Orange", "enabled": True, "speed": {"Percentage": 100}, "linked": [],
                      "fusion_comps": 0, "takes": 0, "media_id": "c1", "markers": {}} for x in items}
        for k, v in (details or {}).items():
            self.settings[k].update(v)

    def __call__(self, op, args, **kw):
        self.calls.append(op)
        if self.fail_on.get(op):
            self.fail_on[op] -= 1
            return {"ok": False, "error": f"{op} failed"}
        r: Any = None
        if op == "list_timeline_items":
            r = [x for x in self.items if x["track_type"] == args["track_type"]]
        elif op == "list_media":
            r = [{"id": "c1", "name": "a.mp4", "fps": self.fps, "frames": str(self.media_frames)}] + [
                {"id": f"tl-{t}", "name": t, "fps": self.fps, "frames": "900", "type": "Timeline"}
                for t in self.timelines]
        elif op == "get_state":
            r = {"timeline": "T", "project": "P", "pins": True, "timeline_fps": self.timeline_fps,
                 "timeline_start_frame": 1000,
                 "timeline_end_frame": 2000, "timeline_drop_frame": "0"}
            if self.caption_parts:
                r["caption_parts"] = True
            if self.clip_markers_by_source:
                r["clip_markers_by_source"] = True
            if self.track_counts:
                r["track_counts"] = dict(self.tracks)
        elif op == "item_details":
            r = [dict(self.settings[i], id=i) for i in args["item_ids"]]
        elif op == "set_fades":
            self.settings[args["item_id"]]["fades"] = {"FadeIn": args["fade_in"], "FadeOut": args["fade_out"]}
            r = {"ok": True, "fades": dict(self.settings[args["item_id"]]["fades"])}
        elif op == "add_track":
            self.tracks[args["track_type"]] += 1
            r = {"count": self.tracks[args["track_type"]], "ok": True}
        elif op == "delete_empty_track":
            self.tracks[args["track_type"]] -= 1
            r = {"ok": True}
        elif op == "delete_items":
            gone = [x for x in self.items if x["id"] in args["item_ids"]]
            self.items[:] = [x for x in self.items if x["id"] not in args["item_ids"]]
            for g in gone if args.get("ripple") else ():  # Resolve shifts later items on every track
                for x in self.items:
                    if x["start"] >= g["end"]:
                        x["start"] -= g["duration"]
                        x["end"] -= g["duration"]
            r = {"ok": True}
        elif op == "trim_tail":
            x = next(x for x in self.items if x["id"] == args["item_id"])
            x["end"] -= args["frames"]
            x["duration"] -= args["frames"]
            r = {"start": x["start"], "end": x["end"]}
        elif op == "list_markers":
            r = {str(k): dict(v) for k, v in self.markers.items()}  # JSON keys are strings
        elif op == "append_clips":
            for c in args["clips"]:
                self.n += 1
                kind = "audio" if c.get("media_type") == 2 else "video"
                new = item(f"n{self.n}", c["record_frame"], c["end_frame"] - c["start_frame"], src=c["start_frame"],
                           track=c["track_index"], kind=kind)
                self.items.append(new)
                self.settings[new["id"]] = {"properties": {"ZoomX": 1}, "fades": {"FadeIn": 0, "FadeOut": 0},
                                            "color": "", "enabled": True, "speed": {"Percentage": 100},
                                            "linked": [], "media_id": "c1", "markers": {}}
            r = []
        elif op == "copy_settings":
            src, dst = self.settings[args["from_id"]], self.settings[args["to_id"]]
            self.copies.append(dict(args))
            for k in ("properties", "fades", "color", "enabled"):
                dst[k] = json.loads(json.dumps(src[k]))
            # clip markers count from the source start, so they keep their frame (live 2026-11-23, docs/ISSUES.md I-23)
            dst["markers"] = {k: dict(v) for k, v in src.get("markers", {}).items() if k != self.drop_marker}
            r = {"copied": ["grade"], "failed": [], "renamed_markers": self.renamed_markers}
            self.renamed_markers = 0  # named now, so later copies keep the name
        elif op == "duplicate_timeline":
            self.timelines.append(args["name"])
            r = {"name": args["name"]}
        elif op in ("link_items", "set_current_timeline"):
            r = {"ok": True}
        elif op == "list_timelines":
            r = list(self.timelines)
        elif op == "add_markers":
            r = {"added": self.add_markers(args["markers"])}
        elif op == "audio_modes":
            r = {"1": "EBU R128"}
        elif op == "add_transition":
            r = self.transition(args["item_id"], args["options"])
            if r is None:  # refused, worded like resolve_bridge.lua
                return {"ok": False, "error": "Resolve refused the transition and gave no reason (...)"}
        elif op in ("set_speed", "copy_grade", "normalize_audio", "set_enabled", "set_item_properties",
                    "export_timeline"):
            r = {"ok": True}
        elif op == "add_title_cards":
            self.title_args = dict(args)  # what add_captions sent, style included
            r = self.title_cards(args)
        return {"ok": True, "result": r}


    def add_markers(self, markers):
        """Like Resolve 21.2: refuses a marker without a name, or on a frame that already has one."""
        added = 0
        for m in markers:
            if m.get("name") and m["frame"] not in self.markers:
                self.markers[m["frame"]] = {"name": m["name"], "color": m.get("color"), "note": m.get("note") or "",
                                            "duration": m.get("duration") or 1}
                added += 1
        return added

    def transition(self, item_id, o):
        """Like Resolve 21.2 (live T2): left ends at the cut, right starts there, center puts an odd frame before it.
        self.misbehave changes what Resolve makes: type, category, alignment, duration, track, track_type, shift
        (frames), move_clip (id), no_props, lost (not on the timeline), refuse (AddTransition gives nil)."""
        bad = getattr(self, "misbehave", {})
        if bad.get("refuse"):
            return None
        target = next(x for x in self.items if x["id"] == item_id)
        cut = target["end"] if o.get("position", "end") == "end" else target["start"]
        d = bad.get("duration", o.get("duration") or 10)
        start = {"left": cut - d, "right": cut}.get(o.get("alignment", "center"), cut - (d + 1) // 2)
        start += bad.get("shift", 0)
        self.n += 1
        tr = item(f"tr{self.n}", start, d, name=bad.get("type", o["type"]), track=bad.get("track", target["track"]),
                  kind=bad.get("track_type", target["track_type"]), type="transition")
        if not bad.get("lost"):
            self.items.append(tr)
        props = {"TransitionType": bad.get("type", o["type"]), "TransitionCategory": bad.get("category", o["category"]),
                 "TransitionAlignment": bad.get("alignment", o["alignment"]), "TransitionDuration": d}
        self.settings[tr["id"]] = {"properties": {} if bad.get("no_props") else props}
        if bad.get("move_clip"):
            moved = next(x for x in self.items if x["id"] == bad["move_clip"])
            moved["start"] += 1
            moved["end"] += 1
        return {"id": tr["id"], "name": tr["name"], "start": tr["start"], "end": tr["end"], "duration": d}

    def title_cards(self, args):
        """Like resolve_bridge.lua: one timeline per card, placed in parts no longer than the inserted title."""
        for i, c in enumerate(args["cards"], 1):
            if c["name"] in self.timelines:  # Resolve refuses a duplicate name, and the op stops there
                return {"placed": list(self.parts), "error": f"could not create timeline {c['name']}"}
            self.timelines.append(c["name"])
            done = 0
            while done < c["frames"]:
                if self.refuse_part == len(self.parts):
                    return {"placed": list(self.parts), "error": f"Resolve refused to place card {i}"}
                part = min(c["frames"] - done, self.title_frames)
                x = item(f"t{len(self.parts)}", c["record_frame"] + done, part, name=c["name"],
                         track=args["track_index"])
                self.parts.append(dict(x, card=i))
                done += part
        return {"placed": list(self.parts)}


class Base(unittest.TestCase):
    def use(self, fake):
        old = bridge.call_bridge
        bridge.call_bridge = fake
        session.invalidate()
        self.addCleanup(setattr, bridge, "call_bridge", old)
        self.addCleanup(session.invalidate)
        return fake


# Bridge ops that change nothing. A preview may use these and no others.
READ_OPS = {"get_state", "list_timeline_items", "list_media", "item_details", "list_markers", "list_timelines",
            "audio_modes"}
# Valid args for every handler: a new tool has to be added here before the suite passes.
SAMPLE_ARGS: dict[str, dict[str, Any]] = {
    "doctor": {}, "timeline_summary": {}, "inspect_range": {"start": 1000, "end": 1010}, "find_media": {},
    "audit_log": {}, "qc_file": {"path": "a.mp4"}, "snapshot_timeline": {},
    "place_clips": {"clips": [{"clip": "c1", "end_frame": 10, "record": 1200}]},
    "move_item": {"item_id": "a", "record": 1100},
    "trim_item": {"item_id": "a", "head_frames": 1},
    "ripple_trim": {"item_ids": ["a"], "tail_frames": 2},
    "set_enabled": {"item_ids": ["a"], "enabled": False},
    "set_fades": {"item_ids": ["a"], "fade_in": 1, "fade_out": 1},
    "add_transition": {"item_id": "a"},
    "set_audio": {"item_ids": ["a"], "volume_db": -3},
    "normalize_audio": {"item_ids": ["a"]},
    "set_speed": {"item_id": "a", "percentage": 50},
    "copy_grade": {"from_id": "a", "to_ids": ["a"]},
    "add_markers": {"markers": [{"at": 1001, "name": "m"}]},
    "add_audio_markers": {"path": "a.mp4", "kind": "silence"},
    "add_captions": {"segments": [{"start": 0, "end": 1, "text": "Hi"}]},
    "export_srt": {"segments": [{"start": 0, "end": 1, "text": "Hi"}]},
    "export_timeline": {"format": "OTIO"},
    "batch": {"operations": []},
}
