"""Shared timeline steps and the refusals around them: backups, appends that don't land, placing clips."""
import unittest

from tests.support import Base, FakeResolve, item, sample_items

from resolve_editor import dispatch


class Backup(Base):
    def test_a_backup_that_doesnt_return_to_the_timeline_stops_the_edit(self):
        class StaysOnCopy(FakeResolve):  # Resolve keeps the copy current
            def __call__(self, op, args, **kw):
                r = super().__call__(op, args, **kw)
                if op == "get_state" and "duplicate_timeline" in self.calls:
                    r["result"]["timeline"] = self.timelines[-1]
                return r
        f = self.use(StaysOnCopy([item("a", 1000, 10, src=5)]))
        with self.assertRaisesRegex(RuntimeError, "did not return to T; nothing was edited"):
            dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T"})
        self.assertFalse({"add_track", "append_clips", "delete_items"} & set(f.calls))


class Appends(Base):
    def test_an_append_that_doesnt_land_changes_nothing(self):
        class Ignores(FakeResolve):  # Resolve accepts the append but nothing appears
            def __call__(self, op, args, **kw):
                return {"ok": True, "result": []} if op == "append_clips" else super().__call__(op, args, **kw)
        f = self.use(Ignores([item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertIn("did not land", r["reason"])
        self.assertEqual([(x["id"], x["start"]) for x in f.items], [("a", 1000)])
        self.assertEqual(f.tracks["video"], 1)


    @staticmethod
    def ignoring(swaps):
        class IgnoresOnTrack1(FakeResolve):
            """The staging append lands; the first `swaps` appends on the clip's own track (V1) don't."""
            def __call__(self, op, args, **kw):
                if op == "append_clips" and args["clips"][0]["track_index"] == 1:
                    self.ignored = getattr(self, "ignored", 0) + 1
                    if self.ignored <= swaps:
                        return {"ok": True, "result": []}
                return super().__call__(op, args, **kw)
        return IgnoresOnTrack1

    def test_a_clip_of_the_same_length_elsewhere_isnt_taken_for_the_append(self):
        f = self.use(self.ignoring(1)([item("a", 1000, 10, src=5), item("b", 1100, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertEqual([c["to_id"] for c in f.copies if c["to_id"] == "b"], [], "b's settings left alone")
        self.assertEqual(sorted((x["start"], x["duration"]) for x in f.items), [(1000, 10), (1100, 10)])

    @unittest.expectedFailure  # docs/ISSUES.md I-29
    def test_when_the_original_cant_be_rebuilt_either_the_result_says_where_the_copy_is(self):
        f = self.use(self.ignoring(2)([item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})  # raises "append ... did not land" today
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertIn("V2", r["reason"], "the staged copy, with the clip's settings, is all that is left")
        self.assertEqual([(x["track"], x["start"]) for x in f.items], [(2, 1050)])


class PlaceClips(Base):
    def test_an_empty_source_range_is_refused(self):
        f = self.use(FakeResolve(sample_items()))
        r = dispatch.run("place_clips", {"clips": [{"clip": "c1", "start_frame": 20, "end_frame": 20,
                                                    "record": 1200}]})
        self.assertEqual(r["_operation"]["status"], "blocked")
        self.assertIn("end_frame must be greater", r["reason"])
        self.assertNotIn("append_clips", f.calls)

    def test_clips_of_one_call_that_overlap_each_other_are_refused(self):
        # Resolve places the later one shifted and shortened (live 2026-11-24, docs/ISSUES.md I-27)
        f = self.use(FakeResolve(sample_items()))
        r = dispatch.run("place_clips", {"clips": [{"clip": "c1", "start_frame": 0, "end_frame": 30, "record": 1200},
                                                   {"clip": "c1", "start_frame": 0, "end_frame": 30,
                                                    "record": 1220}]})
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("overlap", r["reason"])
        self.assertIn("clip 2", r["reason"])
        self.assertIn("clip 1", r["reason"])
        self.assertNotIn("append_clips", f.calls)

    def test_clips_of_one_call_that_touch_or_differ_in_track_or_kind_pass(self):
        self.use(FakeResolve(sample_items()))
        cases = {"back to back": ({"record": 1200}, {"record": 1230}),
                 "other track": ({"record": 1200}, {"record": 1200, "track_index": 3}),
                 "video and audio only": ({"record": 1200, "media_type": 1}, {"record": 1200, "media_type": 2})}
        for case, specs in cases.items():
            with self.subTest(case):
                clips = [dict(s, clip="c1", start_frame=0, end_frame=30) for s in specs]
                r = dispatch.run("place_clips", {"clips": clips})
                self.assertEqual(r["_operation"]["status"], "preview", r)

    def test_overlapping_clips_with_video_and_audio_are_refused_once_naming_the_video_track(self):
        self.use(FakeResolve(sample_items()))
        r = dispatch.run("place_clips", {"clips": [{"clip": "c1", "end_frame": 30, "record": 1300},
                                                   {"clip": "c1", "end_frame": 30, "record": 1290}]})
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("on V1", r["reason"])
        self.assertNotIn("A1", r["reason"])

    @unittest.expectedFailure  # docs/ISSUES.md I-28
    def test_a_source_range_past_the_clip_is_refused(self):
        f = self.use(FakeResolve(sample_items()))  # the media pool clip is 300 frames
        r = dispatch.run("place_clips", {"clips": [{"clip": "c1", "start_frame": 250, "end_frame": 400,
                                                    "record": 1200}]})
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("outside the clip", r["reason"])
        self.assertNotIn("append_clips", f.calls)


class RippleFiller(Base):
    def test_no_filler_timeline_fails_before_trimming(self):
        f = self.use(FakeResolve([item("a", 1000, 100, name="Text+"), item("b", 1200, 100, name="Text+")]))
        r = dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True, "timeline": "T",
                                         "backup": False})  # only T itself, which can't be its own filler
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertIn("filler", r["reason"])
        self.assertNotIn("trim_tail", f.calls)


class OlderBridge(Base):
    def test_listing_captions_through_an_older_bridge_says_to_restart_it(self):
        class Old(FakeResolve):
            def __call__(self, op, args, **kw):
                if op == "caption_texts":
                    return {"ok": False, "error": "unknown op: caption_texts"}
                return super().__call__(op, args, **kw)
        self.use(Old(sample_items()))
        with self.assertRaisesRegex(RuntimeError, "older than this server"):
            dispatch.run("list_captions", {})
