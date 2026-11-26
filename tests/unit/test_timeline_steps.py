"""Shared timeline steps and the refusals around them: backups, appends that don't land, placing clips."""
from tests.support import Base, FakeResolve, item, sample_items

from resolve_editor import dispatch, session


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


class IgnoresOnTrack1(FakeResolve):
    """The staging append lands; the first `swaps` appends on the clip's own track (track 1) don't."""

    swaps = 0

    def __call__(self, op, args, **kw):
        if op == "append_clips" and args["clips"][0]["track_index"] == 1:
            self.ignored = getattr(self, "ignored", 0) + 1
            if self.ignored <= self.swaps:
                return {"ok": True, "result": []}
        return super().__call__(op, args, **kw)


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
    def ignoring(swaps, items, cls=None):
        f = (cls or IgnoresOnTrack1)(items)
        f.swaps = swaps
        return f

    def test_a_clip_of_the_same_length_elsewhere_isnt_taken_for_the_append(self):
        f = self.use(self.ignoring(1, [item("a", 1000, 10, src=5), item("b", 1100, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertEqual([c["to_id"] for c in f.copies if c["to_id"] == "b"], [], "b's settings left alone")
        self.assertEqual(sorted((x["start"], x["duration"]) for x in f.items), [(1000, 10), (1100, 10)])

    def test_when_the_original_cant_be_rebuilt_either_the_result_says_where_the_copy_is(self):
        f = self.use(self.ignoring(2, [item("a", 1000, 10, src=5)]))  # the swap and the rebuild don't land
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual((r["_operation"]["status"], r["_operation"]["verification"]), ("failed", "contradiction"), r)
        self.assertIn("V2", r["reason"], "the staged copy, with the clip's settings, is all that is left")
        self.assertIn("no backup", r["reason"])
        self.assertEqual([(x["track"], x["start"]) for x in f.items], [(2, 1050)])
        kept = r["_operation"]["changes"]["kept_on_staging"]
        self.assertEqual([(k["track"], k["id"]) for k in kept], [("V2", f.items[0]["id"])])
        self.assertEqual(f.tracks["video"], 2, "the staging track is kept")
        self.assertEqual(f.settings[f.items[0]["id"]]["properties"], {"ZoomX": 1.5})

    def test_the_backup_is_named_when_there_is_one(self):
        self.use(self.ignoring(2, [item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T"})
        self.assertIn(f"backup timeline {r['snapshot']}", r["reason"])

    def test_a_linked_pair_where_only_the_audio_cant_be_rebuilt(self):
        class AudioRebuildFails(FakeResolve):  # the swap's video append and every audio append on A1 don't land
            def __call__(self, op, args, **kw):
                c = args["clips"][0] if op == "append_clips" else {}
                if op == "append_clips" and c["track_index"] == 1:
                    self.v1 = getattr(self, "v1", 0) + (c.get("media_type") == 1)
                    if c.get("media_type") == 2 or self.v1 == 1:
                        return {"ok": True, "result": []}
                return super().__call__(op, args, **kw)
        items = [item("v", 1000, 60, src=10), item("a", 1000, 60, src=10, kind="audio")]
        f = self.use(AudioRebuildFails(items, details={"v": {"linked": ["a"]}, "a": {"linked": ["v"]}}))
        r = dispatch.run("move_item", {"item_id": "v", "record": 1200, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        got = sorted((x["track_type"], x["track"], x["start"]) for x in f.items)
        self.assertEqual(got, [("audio", 2, 1200), ("video", 1, 1000)], "video rebuilt, audio copy kept")
        rebuilt = next(x for x in f.items if x["track_type"] == "video")
        self.assertEqual(f.settings[rebuilt["id"]]["properties"], {"ZoomX": 1.5})
        self.assertIn("A2", r["reason"])
        self.assertNotIn("V2", r["reason"])
        self.assertEqual(f.tracks, {"video": 1, "audio": 2}, "only the track with a kept copy stays")
        self.assertNotIn("link_items", f.calls)

    def test_settings_that_cant_be_copied_to_the_rebuilt_clip_leave_the_copy(self):
        class CopyToV1Fails(IgnoresOnTrack1):  # the swap doesn't land; the rebuild lands but takes no settings
            def __call__(self, op, args, **kw):
                to = next((x for x in self.items if x["id"] == args.get("to_id")), None)
                if op == "copy_settings" and to and to["track"] == 1:
                    return {"ok": False, "error": "copy_settings failed"}
                return super().__call__(op, args, **kw)
        f = self.use(self.ignoring(1, [item("a", 1000, 10, src=5)], CopyToV1Fails))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertEqual([(x["track"], x["start"]) for x in f.items], [(2, 1050)], "the bare rebuilt clip is removed")
        self.assertIn("V2", r["reason"])

    def test_a_placed_clip_that_cant_be_removed_is_named_and_the_rebuild_still_runs(self):
        class SecondDeleteFails(FakeResolve):  # the swap's audio append fails; the delete of the video too
            def __call__(self, op, args, **kw):
                c = args["clips"][0] if op == "append_clips" else {}
                if op == "append_clips" and c["track_index"] == 1 and c.get("media_type") == 2:
                    self.a1 = getattr(self, "a1", 0) + 1
                    if self.a1 == 1:
                        return {"ok": True, "result": []}
                if op == "delete_items":
                    self.deletes = getattr(self, "deletes", 0) + 1
                    if self.deletes == 2:
                        return {"ok": False, "error": "delete_items failed"}
                return super().__call__(op, args, **kw)
        items = [item("v", 1000, 60, src=10), item("a", 1000, 60, src=10, kind="audio")]
        f = self.use(SecondDeleteFails(items, details={"v": {"linked": ["a"]}, "a": {"linked": ["v"]}}))
        r = dispatch.run("move_item", {"item_id": "v", "record": 1200, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        got = sorted((x["track_type"], x["track"], x["start"]) for x in f.items)
        self.assertEqual(got, [("audio", 1, 1000), ("video", 1, 1000), ("video", 1, 1200)])
        self.assertIn("V1", " ".join(r["_operation"]["warnings"]))
        self.assertIn("link_items", f.calls)


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

    def test_a_source_range_past_the_clip_is_refused(self):
        f = self.use(FakeResolve(sample_items()))  # the media pool clip is 300 frames
        r = dispatch.run("place_clips", {"clips": [{"clip": "c1", "start_frame": 250, "end_frame": 400,
                                                    "record": 1200}]})
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("outside the clip", r["reason"])
        self.assertIn("0-300", r["reason"])
        self.assertNotIn("append_clips", f.calls)

    def test_a_range_ending_at_the_clips_last_frame_passes(self):  # end_frame is exclusive
        self.use(FakeResolve(sample_items()))
        r = dispatch.run("place_clips", {"clips": [{"clip": "c1", "start_frame": 200, "end_frame": 300,
                                                    "record": 1200}]})
        self.assertEqual(r["_operation"]["status"], "preview", r)

    def test_a_negative_start_is_refused(self):
        self.use(FakeResolve(sample_items()))
        r = dispatch.run("place_clips", {"clips": [{"clip": "c1", "start_frame": -10, "end_frame": 20,
                                                    "record": 1200}]})
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("outside the clip", r["reason"])

    def test_a_clip_of_unknown_length_is_left_to_the_bridge(self):
        class NoLength(FakeResolve):
            def __call__(self, op, args, **kw):
                r = super().__call__(op, args, **kw)
                if op == "list_media":
                    r["result"][0]["frames"] = ""
                return r
        self.use(NoLength(sample_items()))
        r = dispatch.run("place_clips", {"clips": [{"clip": "c1", "start_frame": 0, "end_frame": 5000,
                                                    "record": 1200}]})
        self.assertEqual(r["_operation"]["status"], "preview", r)


class PlaceClipsAtAnotherRate(Base):
    """A clip whose frame rate differs from the timeline's: Resolve converts its length (docs/ISSUES.md I-30)."""

    def fake(self, items=(), clip_fps=30):
        f = FakeResolve([*sample_items(), *items], fps=clip_fps)
        f.timeline_fps = 60
        return self.use(f)

    def place(self, *clips, **kw):
        return dispatch.run("place_clips", {"clips": [dict(c, clip="c1") for c in clips], **kw})

    def test_the_preview_gives_the_length_in_timeline_frames(self):
        self.fake()
        r = self.place({"start_frame": 0, "end_frame": 60, "record": 1200})
        self.assertEqual(r["_operation"]["status"], "preview", r)
        row = r["plan"][0]
        self.assertEqual((row["frames"], row["source_frames"], row["clip_fps"]), (120, 60, 30))

    def test_an_item_only_the_converted_length_reaches_is_refused(self):
        f = self.fake([item("b", 1300, 10)])
        r = self.place({"start_frame": 0, "end_frame": 60, "record": 1200})  # 1200-1320 on the timeline
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("would overwrite", r["reason"])
        self.assertNotIn("append_clips", f.calls)

    def test_clips_of_one_call_that_overlap_only_when_converted_are_refused(self):
        f = self.fake()
        for case, at in {"the later one after": 1260, "the later one before": 1140}.items():
            with self.subTest(case):
                r = self.place({"start_frame": 0, "end_frame": 60, "record": 1200},
                               {"start_frame": 0, "end_frame": 60, "record": at})
                self.assertEqual(r["_operation"]["status"], "blocked", r)
                self.assertIn("would overlap clip 1", r["reason"])
        self.assertNotIn("append_clips", f.calls)

    def test_clips_back_to_back_at_the_converted_length_are_placed_and_read_back(self):
        self.fake()
        clips = ({"start_frame": 0, "end_frame": 60, "record": 1200}, {"start_frame": 0, "end_frame": 60, "record": 1320})
        self.assertEqual(self.place(*clips)["_operation"]["status"], "preview")
        r = self.place(*clips, confirm=True, timeline="T")
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(r["_operation"]["changes"]["clips_placed"], 2)

    def test_a_clip_placed_at_another_length_is_reported(self):
        f = self.fake()
        f.conform_fps = False  # Resolve placed the source frames unconverted
        r = self.place({"start_frame": 0, "end_frame": 60, "record": 1200}, confirm=True, timeline="T")
        self.assertEqual(r["_operation"]["status"], "partial", r)
        self.assertEqual(r["_operation"]["changes"]["clips_placed"], 0)

    def test_a_length_that_isnt_whole_is_rounded_up_with_a_warning(self):
        f = self.fake([item("b", 1262, 10)], clip_fps=24)
        r = self.place({"start_frame": 0, "end_frame": 25, "record": 1200})  # 62.5 timeline frames
        self.assertEqual(r["_operation"]["status"], "blocked", r)  # 1200-1263 reaches b; rounded down it would not
        f.items.pop()
        session.invalidate()
        r = self.place({"start_frame": 0, "end_frame": 25, "record": 1200})
        self.assertEqual(r["plan"][0]["frames"], 63)
        self.assertTrue(any("round" in w for w in r["_operation"]["warnings"]), r)
        r = self.place({"start_frame": 0, "end_frame": 25, "record": 1200}, confirm=True, timeline="T")
        self.assertEqual(r["_operation"]["status"], "success", r)  # the fake rounds 62.5 to 62: within a frame

    def test_the_same_rate_keeps_the_source_length(self):
        self.fake(clip_fps=60)
        row = self.place({"start_frame": 0, "end_frame": 60, "record": 1200})["plan"][0]
        self.assertEqual(row["frames"], 60)
        self.assertEqual(row["source_frames"], 60)
        self.assertNotIn("clip_fps", row)


class RippleFiller(Base):
    def test_no_filler_timeline_fails_before_trimming(self):
        f = self.use(FakeResolve([item("a", 1000, 100, name="Text+"), item("b", 1200, 100, name="Text+")]))
        r = dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True, "timeline": "T",
                                         "backup": False})  # only T itself, which can't be its own filler
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertIn("filler", r["reason"])
        self.assertNotIn("trim_tail", f.calls)

    # A filler at another rate is placed converted, so it isn't n timeline frames (docs/ISSUES.md I-33)
    def fake(self, *timelines, rates=None, listed=None):
        f = self.use(FakeResolve([item("a", 1000, 100, name="Text+"), item("b", 1200, 100, name="Text+")]))
        f.timelines += list(timelines)
        f.timeline_rates.update(rates or {})
        f.listed_rates.update(listed or {})
        return f

    def trim(self):
        return dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True, "timeline": "T",
                                            "backup": False})  # as in a batch: no backup to prefer as the filler

    def spans(self, f):
        return {x["id"]: (x["start"], x["end"]) for x in f.items}

    def test_a_timeline_at_another_rate_isnt_used_as_the_filler(self):
        f = self.fake("Other", rates={"Other": 60})
        r = self.trim()
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertIn("filler", r["reason"])
        self.assertNotIn("trim_tail", f.calls)

    def test_the_filler_at_the_timelines_rate_is_picked_over_one_listed_first(self):
        f = self.fake("Other", "Same", rates={"Other": 60})
        r = self.trim()
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(self.spans(f), {"a": (1000, 1070), "b": (1170, 1270)})

    def test_a_filler_that_lands_at_another_length_is_removed_and_the_end_restored(self):
        f = self.fake("Other", rates={"Other": 60}, listed={"Other": 30})  # the pool says 30, it places as 60
        r = self.trim()
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertEqual(self.spans(f), {"a": (1000, 1100), "b": (1200, 1300)})  # no stray filler, end back


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
