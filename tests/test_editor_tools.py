"""Automated tests for edit__ tools against a fake Resolve. They need no Resolve installation.

These prove the logic (planning, refusals, rollback order, frame maths). They cannot prove that Resolve itself
behaves the same way; see tests/live_resolve.py for the checks that need a real Resolve.
"""
import builtins, json, os, pathlib, subprocess, sys, tempfile, unittest
from fractions import Fraction
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["RESOLVE_BRIDGE_DIR"] = tempfile.mkdtemp()
import editor_tools as E
import mcp_server as M


def item(id, start, dur, name="a.mp4", src=0, track=1, kind="video", type=None):
    return {"id": id, "name": name, "start": start, "end": start + dur, "duration": dur, "source_start": src,
            "track": track, "track_type": kind, "type": type or kind}


class FakeResolve:
    """Just enough of the bridge to exercise edit__ logic. fail_on makes one op fail once."""

    def __init__(self, items, fail_on=None, details=None, fps=30):
        self.items, self.fail_on, self.calls, self.n, self.fps = items, dict(fail_on or {}), [], 0, fps
        self.tracks, self.timelines = {"video": 1, "audio": 1}, ["T"]
        self.settings = {x["id"]: {"properties": {"ZoomX": 1.5}, "fades": {"FadeIn": 4, "FadeOut": 0}, "color": "Orange",
                                   "enabled": True, "speed": {"Percentage": 100}, "linked": [], "fusion_comps": 0,
                                   "takes": 0, "media_id": "c1"} for x in items}
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
                {"id": f"tl-{t}", "name": t, "fps": self.fps, "frames": "900", "type": "Timeline"} for t in self.timelines]
        elif op == "get_state":
            r = {"timeline": "T", "timeline_fps": 30, "timeline_start_frame": 1000, "timeline_end_frame": 2000,
                 "timeline_drop_frame": "0"}
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
                self.settings[new["id"]] = {"properties": {"ZoomX": 1}, "fades": {"FadeIn": 0, "FadeOut": 0}, "color": "",
                                            "enabled": True, "speed": {"Percentage": 100}, "linked": [], "media_id": "c1"}
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
        elif op in ("set_speed", "copy_grade", "normalize_audio", "set_enabled", "set_item_properties", "export_timeline"):
            r = {"ok": True}
        elif op == "add_title_cards":
            r = {"placed": [item(f"t{i}", c["record_frame"], c["frames"], name="Text+") for i, c in enumerate(args["cards"])]}
        return {"ok": True, "result": r}


class Base(unittest.TestCase):
    def use(self, fake):
        old = M.call_bridge
        M.call_bridge = fake
        E.invalidate()
        self.addCleanup(setattr, M, "call_bridge", old)
        self.addCleanup(E.invalidate)
        return fake


class Timecode(unittest.TestCase):
    def test_fps(self):
        self.assertEqual(E.parse_fps(30), 30)
        self.assertEqual(E.parse_fps("29.97"), Fraction(30000, 1001))
        self.assertEqual(E.parse_fps("23.976"), Fraction(24000, 1001))

    def test_round_trip(self):
        for fps, drop in ((30, False), (Fraction(30000, 1001), True), (Fraction(24000, 1001), False), (25, False)):
            for frame in (0, 1, 1799, 1800, 17982, 107892, 108000, 215784):
                self.assertEqual(E.tc_to_frame(E.frame_to_tc(frame, fps, drop), fps, drop), frame, (fps, drop, frame))

    def test_drop_frame_known_values(self):
        df = Fraction(30000, 1001)
        self.assertEqual(E.frame_to_tc(1800, df, True), "00:01:00;02")
        self.assertEqual(E.frame_to_tc(17982, df, True), "00:10:00;00")
        self.assertEqual(E.frame_to_tc(108000, 30), "01:00:00:00")

    def test_seconds_to_frames_ntsc(self):
        self.assertEqual(E.seconds_to_frames(1.001, Fraction(30000, 1001)), 30)


class Inspection(Base):
    def test_summary_ignores_transitions_and_is_compact(self):
        items = [item("a", 1000, 10), item("t", 1005, 10, name="Cross Dissolve", type="transition"), item("b", 1010, 10)]
        items += [item(f"g{i}", 1100 + i * 20, 10, name=f"x{i}") for i in range(30)]
        self.use(FakeResolve(items))
        r = E.run("timeline_summary", {"limit": 3})
        self.assertEqual(r["transitions"], 1)
        self.assertEqual(r["overlaps"]["count"], 0)
        self.assertEqual(len(r["gaps"]["first"]), 3)
        self.assertEqual(r["gaps"]["first"][0]["at"], "00:00:34:00")  # frame 1020 at 30 fps

    def test_reused_clips(self):
        r = E.analyze([item("a", 0, 10), item("b", 20, 10), item("c", 25, 10, name="z")])
        self.assertEqual(r["reused_clips"], {"a.mp4": ["0", "20"]})

    def test_cache_avoids_repeat_reads(self):
        f = self.use(FakeResolve([item("a", 1000, 10)]))
        E.run("timeline_summary", {})
        E.run("timeline_summary", {})
        self.assertEqual(f.calls.count("list_timeline_items"), 2)  # video + audio once, not twice per call


class Replace(Base):
    def test_preview_changes_nothing(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = E.run("move_item", {"item_id": "a", "record": 1050})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertFalse({"delete_items", "append_clips", "add_track"} & set(f.calls))

    def test_move_keeps_settings(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = E.run("move_item", {"item_id": "a", "record": "00:00:35:00", "confirm": True})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        moved = [x for x in f.items if x["track"] == 1]
        self.assertEqual([(x["start"], x["source_start"]) for x in moved], [(1050, 5)])
        self.assertEqual(f.settings[moved[0]["id"]]["properties"], {"ZoomX": 1.5})
        self.assertEqual(f.tracks["video"], 1, "staging track removed")

    def test_backup_made_before_edit(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = E.run("move_item", {"item_id": "a", "record": 1050, "confirm": True})
        self.assertTrue(r["snapshot"].startswith("T before edit"))
        self.assertLess(f.calls.index("duplicate_timeline"), f.calls.index("add_track"))

    def test_original_deleted_only_after_replacement_is_ready(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        E.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "backup": False})
        self.assertLess(f.calls.index("copy_settings"), f.calls.index("delete_items"))

    def test_staging_failure_leaves_original(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)], fail_on={"copy_settings": 1}))
        r = E.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertIn("a", [x["id"] for x in f.items])
        self.assertEqual(f.tracks["video"], 1)

    def test_swap_failure_rebuilds_original_with_settings(self):
        class FailSecondAppend(FakeResolve):
            def __call__(self, op, args, **kw):
                if op == "append_clips":
                    self.appends = getattr(self, "appends", 0) + 1
                    if self.appends == 2:
                        return {"ok": False, "error": "refused"}
                return super().__call__(op, args, **kw)
        f = self.use(FailSecondAppend([item("a", 1000, 10, src=5)]))
        r = E.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed")
        back = [x for x in f.items if x["track"] == 1]
        self.assertEqual([(x["start"], x["source_start"], x["duration"]) for x in back], [(1000, 5, 10)])
        self.assertEqual(f.settings[back[0]["id"]]["properties"], {"ZoomX": 1.5})

    def test_trim_moves_linked_audio_too(self):
        items = [item("v", 1000, 60, src=10), item("a", 1000, 60, src=10, kind="audio")]
        f = self.use(FakeResolve(items, details={"v": {"linked": ["a"]}, "a": {"linked": ["v"]}}))
        r = E.run("trim_item", {"item_id": "v", "head_frames": 5, "tail_frames": 10, "confirm": True, "backup": False})
        self.assertEqual(r["_operation"]["status"], "success", r)
        got = sorted((x["track_type"], x["start"], x["duration"], x["source_start"]) for x in f.items if x["track"] == 1)
        self.assertEqual(got, [("audio", 1005, 45, 15), ("video", 1005, 45, 15)])
        self.assertIn("link_items", f.calls)

    def test_refusals(self):
        cases = [({"speed": {"Percentage": 50}}, "speed"), ({"fusion_comps": 1}, "Fusion"), ({"media_id": None}, "media-pool")]
        for detail, word in cases:
            self.use(FakeResolve([item("a", 1000, 10)], details={"a": detail}))
            r = E.run("move_item", {"item_id": "a", "record": 1050, "confirm": True})
            self.assertEqual(r["_operation"]["status"], "blocked")
            self.assertIn(word, r["reason"])

    def test_ripple_trim_keeps_gaps_and_titles(self):
        titles = [item("t1", 1000, 100, name="Text+"), item("t2", 1110, 50, name="Text+"),
                  item("t3", 1200, 100, name="Text+"), item("up", 1250, 20, name="Text+", track=2)]
        f = self.use(FakeResolve(titles, details={i: {"fusion_comps": 1, "media_id": None} for i in ("t1", "t2", "t3", "up")}))
        r = E.run("ripple_trim", {"item_ids": ["t1", "t3"], "tail_frames": 30})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertNotIn("trim_tail", f.calls)
        self.assertEqual(r["plan"]["trim"][1]["now"], [E._tc(1170), E._tc(1240)])
        r = E.run("ripple_trim", {"item_ids": ["t1", "t3"], "tail_frames": 30, "confirm": True})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        got = {x["id"]: (x["start"], x["end"]) for x in f.items}
        self.assertEqual(got, {"t1": (1000, 1070), "t2": (1080, 1130), "t3": (1170, 1240), "up": (1220, 1240)})
        self.assertNotIn("copy_settings", f.calls)  # nothing was rebuilt
        self.assertLess(f.calls.index("duplicate_timeline"), f.calls.index("trim_tail"))

    def test_ripple_trim_refusals(self):
        self.use(FakeResolve([item("a", 1000, 100), item("b", 1080, 100, track=2)]))
        self.assertIn("overlaps", E.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30})["reason"])
        self.use(FakeResolve([item("a", 1000, 100)], details={"a": {"linked": ["x"]}}))
        self.assertIn("linked", E.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30})["reason"])
        self.use(FakeResolve([item("a", 1000, 20)]))
        self.assertIn("only 20", E.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30})["reason"])
        self.assertIn("positive", E.run("ripple_trim", {"item_ids": ["a"], "tail_frames": -5})["reason"])

    def test_ripple_trim_restores_end_when_ripple_fails(self):
        f = self.use(FakeResolve([item("a", 1000, 100, name="Text+"), item("b", 1200, 100, name="Text+")],
                                 fail_on={"delete_items": 1}))
        r = E.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True})
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertEqual({x["id"]: (x["start"], x["end"]) for x in f.items}, {"a": (1000, 1100), "b": (1200, 1300)})

    def test_mixed_fps_refused(self):
        self.use(FakeResolve([item("a", 1000, 10)], fps=25))
        self.assertIn("frame rate", E.run("move_item", {"item_id": "a", "record": 1050})["reason"])

    def test_collision_and_transition_refused(self):
        self.use(FakeResolve([item("a", 1000, 10), item("b", 1050, 10)]))
        self.assertIn("overwrite", E.run("move_item", {"item_id": "a", "record": 1045})["reason"])
        self.use(FakeResolve([item("a", 1000, 10), item("t", 1005, 10, type="transition")]))
        self.assertIn("transition", E.run("move_item", {"item_id": "a", "record": 1100})["reason"])

    def test_trim_past_source(self):
        self.use(FakeResolve([item("a", 1000, 60, src=0)]))
        self.assertIn("outside", E.run("trim_item", {"item_id": "a", "head_frames": -5})["reason"])


class Fades(Base):
    def test_missing_end_keeps_current_length(self):
        f = self.use(FakeResolve([item("a", 1000, 60)], details={"a": {"fades": {"FadeIn": 30, "FadeOut": 10}}}))
        r = E.run("set_fades", {"item_ids": ["a"], "fade_out": 60})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        self.assertEqual(f.settings["a"]["fades"], {"FadeIn": 30, "FadeOut": 60})
        self.assertIn("lost when Resolve restarts", r["_operation"]["warnings"][0])
        E.run("set_fades", {"item_ids": ["a"], "fade_in": 0})
        self.assertEqual(f.settings["a"]["fades"], {"FadeIn": 0, "FadeOut": 60})

    def test_both_ends_given_skips_read(self):
        f = self.use(FakeResolve([item("a", 1000, 60)]))
        E.run("set_fades", {"item_ids": ["a"], "fade_in": 5, "fade_out": 6})
        self.assertNotIn("item_details", f.calls)
        self.assertEqual(f.settings["a"]["fades"], {"FadeIn": 5, "FadeOut": 6})

    def test_nothing_given_is_refused(self):
        f = self.use(FakeResolve([item("a", 1000, 60)]))
        self.assertEqual(E.run("set_fades", {"item_ids": ["a"]})["_operation"]["status"], "blocked")
        self.assertNotIn("set_fades", f.calls)


class Captions(Base):
    def test_split_and_no_overlap(self):
        segs = E.split_segments([{"start": 0, "end": 4, "text": "one two three four five six seven eight nine ten"},
                                 {"start": 3.5, "end": 5, "text": "next"}], max_chars=20)
        self.assertTrue(all(len(s["text"]) <= 20 for s in segs))
        for a, b in zip(segs, segs[1:]):
            self.assertLessEqual(a["end"], b["start"])

    def test_cards_cap_at_five_seconds(self):
        cards = E.caption_cards([{"start": 0, "end": 7, "text": "long"}], 30, 1000, "T")
        self.assertEqual([(c["record_frame"], c["frames"]) for c in cards], [(1000, 150), (1150, 60)])
        self.assertEqual(len({c["name"] for c in cards}), 2)

    def test_add_captions_preview_then_apply(self):
        f = self.use(FakeResolve([]))
        segs = [{"start": 1, "end": 2.5, "text": "hi"}]
        r = E.run("add_captions", {"segments": segs})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertNotIn("add_title_cards", f.calls)
        r = E.run("add_captions", {"segments": segs, "confirm": True})
        self.assertEqual(r["_operation"]["verification"], "passed", r)

    def test_srt(self):
        self.assertEqual(E.to_srt([{"start": 61.5, "end": 62, "text": "hi"}]), "1\n00:01:01,500 --> 00:01:02,000\nhi\n\n")


class Analysis(Base):
    def test_onsets(self):
        rate, s = 11025, []
        for _ in range(4):
            s += [0.8] * 1000 + [0.0] * (rate // 2 - 1000)
        self.assertGreaterEqual(len(E.onsets(s, rate)), 3)

    def test_qc_parse(self):
        log = ("[blackdetect] black_start:0 black_end:0.8\n[freezedetect] freeze_start: 3.2\n"
               "  Integrated loudness:\n    I:         -14.2 LUFS\n  Loudness range:\n    LRA:         5.1 LU\n"
               "  True peak:\n    Peak:       -0.5 dBFS\n")
        r = E.parse_qc(log)
        self.assertEqual((r["integrated_lufs"], r["true_peak_dbfs"], r["black_segments"]), (-14.2, -0.5, [[0.0, 0.8]]))

    def test_batch_previews_without_writing(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = E.run("batch", {"operations": [{"tool": "move_item", "args": {"item_id": "a", "record": 1050}}]})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertNotIn("delete_items", f.calls)


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


class PreviewSafety(Base):
    """Without confirm=true (the boolean, at the top level) nothing may be changed (ISSUES.md I-01)."""

    def setUp(self):
        self.effects, real_open = [], builtins.open

        def guarded_open(file, mode="r", *args, **kw):
            if set(mode) & set("wax+"):
                self.effects.append(("file write", str(file)))
                return real_open(os.devnull, mode, *args, **kw)
            return real_open(file, mode, *args, **kw)

        def forbid(what):
            def call(*args, **kw):
                self.effects.append((what, args[:1]))
                raise RuntimeError(f"{what} during a preview")
            return call

        for target, name, fake in ((builtins, "open", guarded_open),
                                   (E, "log_audit", lambda *args: self.effects.append(("audit", args[0]))),
                                   (M, "run_media_tool", forbid("media tool")),
                                   (subprocess, "run", forbid("subprocess"))):
            patch = mock.patch.object(target, name, fake)
            patch.start()
            self.addCleanup(patch.stop)

    def attempt(self, tool, args):
        """Run on a fresh fake; return the result and everything that had a side effect."""
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        self.effects.clear()
        try:
            r = E.run(tool, args)
        except Exception as exc:
            r = {"error": repr(exc)}
        return r, [op for op in f.calls if op not in READ_OPS] + self.effects

    def test_every_handler_has_sample_args(self):
        self.assertEqual(set(SAMPLE_ARGS), set(E.HANDLERS))

    def test_previewable_matches_schemas(self):
        with_confirm = {t["name"] for t in E.TOOLS if "confirm" in t["inputSchema"]["properties"]}
        self.assertEqual(E.PREVIEWABLE, with_confirm - {"batch"})

    def test_batch_preview_changes_nothing_for_any_tool(self):
        for tool in sorted(set(E.HANDLERS) - {"batch"}):
            for inner in ({}, {"confirm": True}):
                with self.subTest(tool=tool, inner=inner):
                    r, effects = self.attempt("batch", {"operations": [{"tool": tool,
                                                                        "args": {**SAMPLE_ARGS[tool], **inner}}]})
                    self.assertEqual(effects, [])
                    self.assertEqual(r.get("_operation", {}).get("status"), "preview", r)
                    step = r["plan"][0]
                    if tool in E.PREVIEWABLE:
                        self.assertEqual(step["preview"]["_operation"]["status"], "preview", step)
                    else:
                        self.assertIn("not_run", step)
                        self.assertNotIn("confirm", step["args"])
                        self.assertTrue(r["_operation"]["warnings"])

    def test_unknown_new_handler_is_never_called(self):
        new = mock.Mock(return_value={})
        with mock.patch.dict(E.HANDLERS, {"brand_new_tool": new}):
            r, effects = self.attempt("batch", {"operations": [{"tool": "brand_new_tool"}]})
        new.assert_not_called()
        self.assertEqual(effects, [])
        self.assertIn("not_run", r["plan"][0])

    def test_only_boolean_true_confirms(self):
        cases = {t["name"]: SAMPLE_ARGS[t["name"]] for t in E.TOOLS if "confirm" in t["inputSchema"]["properties"]}
        cases["batch"] = {"operations": [{"tool": "add_transition", "args": {"item_id": "a"}}]}
        for tool, args in cases.items():
            for value in ("false", "true", "no", 1, [1], False, None):
                with self.subTest(tool=tool, confirm=value):
                    r, effects = self.attempt(tool, {**args, "confirm": value})
                    self.assertEqual(effects, [])
                    self.assertEqual(r.get("_operation", {}).get("status"), "preview", r)

    def test_captions_from_path_are_not_transcribed(self):
        for segments in ({}, {"segments": []}):
            with self.subTest(segments=segments):
                r, effects = self.attempt("batch", {"operations": [{"tool": "add_captions",
                                                                    "args": {"path": "a.mp4", **segments}}]})
                self.assertEqual(effects, [])
                self.assertIn("not_run", r["plan"][0])

    def test_preview_then_confirm_runs_each_step_once(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        ops = [{"tool": "add_transition", "args": {"item_id": "a"}},
               {"tool": "set_speed", "args": {"item_id": "a", "percentage": 50, "confirm": False}}]
        E.run("batch", {"operations": ops})
        E.run("batch", {"operations": ops, "confirm": True})
        writes = [c for c in f.calls if c not in READ_OPS and c != "set_current_timeline"]
        self.assertEqual(writes, ["duplicate_timeline", "add_transition", "set_speed"])


class GatewayResilience(unittest.TestCase):
    def rpc(self, env):
        p = subprocess.Popen([sys.executable, str(ROOT / "unified_server.py")], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env)
        self.addCleanup(lambda: (p.terminate(), p.wait(5), p.stdin.close(), p.stdout.close()))

        def call(i, m, params=None):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": m, "params": params or {}}) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())
        return call

    def test_runs_without_upstream_and_guards(self):
        env = dict(os.environ, RESOLVE_MCP_REPO=tempfile.mkdtemp(), RESOLVE_MCP_SERVER="missing.py",
                   RESOLVE_MCP_PYTHON="missing.exe")
        env.pop("RESOLVE_MCP_COMMAND", None)
        call = self.rpc(env)
        self.assertIn("instructions", call(1, "initialize", {"protocolVersion": "2025-03-26"})["result"])
        tools = call(2, "tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertTrue({"edit__move_item", "edit__timeline_summary", "legacy__get_state"} <= names)
        self.assertFalse([n for n in names if n.startswith("resolve__")])
        self.assertLess(len(json.dumps(tools)), 60000, "tool list stays small enough for context")
        r = call(3, "tools/call", {"name": "legacy__start_render", "arguments": {}})["result"]
        self.assertTrue(r["isError"])
        self.assertIn("confirm", r["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
