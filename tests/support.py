"""Fakes and sample data for the tests, which need no Resolve installation.

Every test file imports this module before resolve_editor: it points the bridge folder at a temporary one, so no
test can reach Resolve or write to the user's folder (ISSUES.md I-14).
These prove the logic (planning, refusals, rollback order, frame maths). They cannot prove that Resolve itself
behaves the same way; see tests/live_resolve.py for the checks that need a real Resolve.
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["RESOLVE_BRIDGE_DIR"] = tempfile.mkdtemp()
from resolve_editor import bridge, session  # noqa: E402  (only after the line above)


def item(id, start, dur, name="a.mp4", src=0, track=1, kind="video", type=None):
    return {"id": id, "name": name, "start": start, "end": start + dur, "duration": dur, "source_start": src,
            "track": track, "track_type": kind, "type": type or kind}


class FakeResolve:
    """Just enough of the bridge to exercise edit__ logic. fail_on makes one op fail once."""

    def __init__(self, items, fail_on=None, details=None, fps=30):
        self.items, self.fail_on, self.calls, self.n, self.fps = items, dict(fail_on or {}), [], 0, fps
        self.tracks, self.timelines = {"video": 1, "audio": 1}, ["T"]
        self.settings = {x["id"]: {"properties": {"ZoomX": 1.5}, "fades": {"FadeIn": 4, "FadeOut": 0},
                                   "color": "Orange", "enabled": True, "speed": {"Percentage": 100}, "linked": [],
                                   "fusion_comps": 0, "takes": 0, "media_id": "c1"} for x in items}
        for k, v in (details or {}).items():
            self.settings[k].update(v)

    def __call__(self, op, args, **kw):
        self.calls.append(op)
        if self.fail_on.get(op):
            self.fail_on[op] -= 1
            return {"ok": False, "error": f"{op} failed"}
        r = None
        if op == "list_timeline_items":
            r = [x for x in self.items if x["track_type"] == args["track_type"]]
        elif op == "list_media":
            r = [{"id": "c1", "name": "a.mp4", "fps": self.fps, "frames": "300"}] + [
                {"id": f"tl-{t}", "name": t, "fps": self.fps, "frames": "900", "type": "Timeline"}
                for t in self.timelines]
        elif op == "get_state":
            r = {"timeline": "T", "project": "P", "pins": True, "timeline_fps": 30, "timeline_start_frame": 1000,
                 "timeline_end_frame": 2000, "timeline_drop_frame": "0"}
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
            r = {}
        elif op == "append_clips":
            for c in args["clips"]:
                self.n += 1
                kind = "audio" if c.get("media_type") == 2 else "video"
                new = item(f"n{self.n}", c["record_frame"], c["end_frame"] - c["start_frame"], src=c["start_frame"],
                           track=c["track_index"], kind=kind)
                self.items.append(new)
                self.settings[new["id"]] = {"properties": {"ZoomX": 1}, "fades": {"FadeIn": 0, "FadeOut": 0},
                                            "color": "", "enabled": True, "speed": {"Percentage": 100},
                                            "linked": [], "media_id": "c1"}
            r = []
        elif op == "copy_settings":
            src, dst = self.settings[args["from_id"]], self.settings[args["to_id"]]
            for k in ("properties", "fades", "color", "enabled"):
                dst[k] = json.loads(json.dumps(src[k]))
            r = {"copied": ["grade"], "failed": []}
        elif op == "duplicate_timeline":
            self.timelines.append(args["name"])
            r = {"name": args["name"]}
        elif op in ("link_items", "set_current_timeline"):
            r = {"ok": True}
        elif op == "list_timelines":
            r = list(self.timelines)
        elif op == "add_markers":
            r = {"added": len(args["markers"])}
        elif op == "audio_modes":
            r = {"1": "EBU R128"}
        elif op == "add_transition":
            o = args["options"]
            r = {"id": "tr", "name": o["type"], "start": 1005, "end": 1015, "duration": o.get("duration", 10)}
        elif op in ("set_speed", "copy_grade", "normalize_audio", "set_enabled", "set_item_properties",
                    "export_timeline"):
            r = {"ok": True}
        elif op == "add_title_cards":
            r = {"placed": [item(f"t{i}", c["record_frame"], c["frames"], name="Text+")
                            for i, c in enumerate(args["cards"])]}
        return {"ok": True, "result": r}


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
SAMPLE_ARGS = {
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
    "add_markers": {"markers": [{"at": 1001}]},
    "add_audio_markers": {"path": "a.mp4", "kind": "silence"},
    "add_captions": {"segments": [{"start": 0, "end": 1, "text": "Hi"}]},
    "export_srt": {"segments": [{"start": 0, "end": 1, "text": "Hi"}]},
    "export_timeline": {"format": "OTIO"},
    "batch": {"operations": []},
}
