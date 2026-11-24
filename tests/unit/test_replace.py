"""Moving and trimming by replacement."""
from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch


class Replace(Base):
    def test_preview_changes_nothing(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertFalse({"delete_items", "append_clips", "add_track"} & set(f.calls))

    def test_move_keeps_settings(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": "00:00:35:00", "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        moved = [x for x in f.items if x["track"] == 1]
        self.assertEqual([(x["start"], x["source_start"]) for x in moved], [(1050, 5)])
        self.assertEqual(f.settings[moved[0]["id"]]["properties"], {"ZoomX": 1.5})
        self.assertEqual(f.tracks["video"], 1, "staging track removed")

    def test_unnamed_clip_markers_are_kept_with_a_name_and_a_warning(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        f.renamed_markers = 2  # Resolve 21.2 refuses unnamed markers; the bridge copies them as "Marker" (I-19)
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertIn("2 unnamed clip marker(s)", " ".join(r["_operation"]["warnings"]))
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T"})
        self.assertNotIn("unnamed", " ".join(r["_operation"]["warnings"]))

    def test_backup_made_before_edit(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T"})
        self.assertTrue(r["snapshot"].startswith("T before edit"))
        self.assertLess(f.calls.index("duplicate_timeline"), f.calls.index("add_track"))

    def test_original_deleted_only_after_replacement_is_ready(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T", "backup": False})
        self.assertLess(f.calls.index("copy_settings"), f.calls.index("delete_items"))

    def test_staging_failure_leaves_original(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)], fail_on={"copy_settings": 1}))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})
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
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed")
        back = [x for x in f.items if x["track"] == 1]
        self.assertEqual([(x["start"], x["source_start"], x["duration"]) for x in back], [(1000, 5, 10)])
        self.assertEqual(f.settings[back[0]["id"]]["properties"], {"ZoomX": 1.5})

    def test_a_setting_reported_as_not_copied_leaves_the_original(self):
        class GradeNotCopied(FakeResolve):
            def __call__(self, op, args, **kw):
                r = super().__call__(op, args, **kw)
                if op == "copy_settings":
                    r["result"]["failed"] = ["grade"]
                return r
        f = self.use(GradeNotCopied([item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertIn("grade", r["reason"])
        self.assertEqual([(x["id"], x["start"]) for x in f.items], [("a", 1000)], "staged copy removed")
        self.assertEqual(f.tracks["video"], 1, "staging track removed")

    def test_swap_failure_after_one_linked_item_rebuilds_both_and_links_them(self):
        class FailFourthAppend(FakeResolve):  # 2 staged, then the swap: video lands, audio is refused
            def __call__(self, op, args, **kw):
                if op == "append_clips":
                    self.appends = getattr(self, "appends", 0) + 1
                    if self.appends == 4:
                        return {"ok": False, "error": "refused"}
                if op == "link_items":
                    self.linked = list(args["item_ids"])
                return super().__call__(op, args, **kw)
        items = [item("v", 1000, 60, src=10), item("a", 1000, 60, src=10, kind="audio")]
        f = self.use(FailFourthAppend(items, details={"v": {"linked": ["a"]}, "a": {"linked": ["v"]}}))
        r = dispatch.run("move_item", {"item_id": "v", "record": 1200, "confirm": True, "timeline": "T",
                                       "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        got = sorted((x["track_type"], x["track"], x["start"], x["source_start"], x["duration"]) for x in f.items)
        self.assertEqual(got, [("audio", 1, 1000, 10, 60), ("video", 1, 1000, 10, 60)],
                         "the moved video is removed and both originals are back where they were")
        self.assertEqual(sorted(f.linked), sorted(x["id"] for x in f.items), "the rebuilt pair is linked")
        self.assertEqual(f.tracks, {"video": 1, "audio": 1}, "staging tracks removed")

    def test_trim_moves_linked_audio_too(self):
        items = [item("v", 1000, 60, src=10), item("a", 1000, 60, src=10, kind="audio")]
        f = self.use(FakeResolve(items, details={"v": {"linked": ["a"]}, "a": {"linked": ["v"]}}))
        r = dispatch.run("trim_item", {"item_id": "v", "head_frames": 5, "tail_frames": 10, "confirm": True,
                                       "timeline": "T", "backup": False})
        self.assertEqual(r["_operation"]["status"], "success", r)
        got = sorted((x["track_type"], x["start"], x["duration"], x["source_start"])
                     for x in f.items if x["track"] == 1)
        self.assertEqual(got, [("audio", 1005, 45, 15), ("video", 1005, 45, 15)])
        self.assertIn("link_items", f.calls)

    def test_refusals(self):
        cases = [({"speed": {"Percentage": 50}}, "speed"), ({"fusion_comps": 1}, "Fusion"),
                 ({"media_id": None}, "media-pool")]
        for detail, word in cases:
            self.use(FakeResolve([item("a", 1000, 10)], details={"a": detail}))
            r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "timeline": "T"})
            self.assertEqual(r["_operation"]["status"], "blocked")
            self.assertIn(word, r["reason"])

    def test_mixed_fps_refused(self):
        self.use(FakeResolve([item("a", 1000, 10)], fps=25))
        self.assertIn("frame rate", dispatch.run("move_item", {"item_id": "a", "record": 1050})["reason"])

    def test_collision_and_transition_refused(self):
        self.use(FakeResolve([item("a", 1000, 10), item("b", 1050, 10)]))
        self.assertIn("overwrite", dispatch.run("move_item", {"item_id": "a", "record": 1045})["reason"])
        self.use(FakeResolve([item("a", 1000, 10), item("t", 1005, 10, type="transition")]))
        self.assertIn("transition", dispatch.run("move_item", {"item_id": "a", "record": 1100})["reason"])

    def test_trim_past_source(self):
        self.use(FakeResolve([item("a", 1000, 60, src=0)]))
        self.assertIn("outside", dispatch.run("trim_item", {"item_id": "a", "head_frames": -5})["reason"])


class ClipMarkers(Base):
    """Clip markers count from the source start and must survive a rebuild at the same frame (docs/ISSUES.md I-23)."""

    # A clip from source 180-480: one in the middle, one near each end, one hidden past the out-point.
    MARKERS = {"348": {"name": "Marker 1", "color": "Blue"}, "190": {"name": "near in", "color": "Red"},
               "470": {"name": "near out", "color": "Green"}, "600": {"name": "hidden", "color": "Blue"}}

    def fake(self, **kw):
        f = self.use(FakeResolve([item("a", 1000, 300, src=180)], details={"a": {"markers": dict(self.MARKERS)}}))
        f.media_frames = 2275  # the live test recording
        for k, v in kw.items():
            setattr(f, k, v)
        return f

    def markers_now(self, f):
        clip = next(x for x in f.items if x["track"] == 1)
        return f.settings[clip["id"]]["markers"]

    def test_move_keeps_markers_at_their_source_frames(self):
        f = self.fake()
        r = dispatch.run("move_item", {"item_id": "a", "record": 1400, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        self.assertEqual(self.markers_now(f), self.MARKERS)
        self.assertTrue(all(not c.get("marker_shift") for c in f.copies), f.copies)

    def test_trim_keeps_markers_including_trimmed_away_ones(self):
        f = self.fake()
        r = dispatch.run("trim_item", {"item_id": "a", "head_frames": 50, "tail_frames": 20, "confirm": True,
                                       "timeline": "T"})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        self.assertEqual(self.markers_now(f), self.MARKERS)  # 190 and 470 are now hidden, as Resolve keeps them
        self.assertTrue(all(not c.get("marker_shift") for c in f.copies), f.copies)

    def test_a_lost_marker_is_a_contradiction(self):
        self.fake(drop_marker="348")
        r = dispatch.run("move_item", {"item_id": "a", "record": 1400, "confirm": True, "timeline": "T"})
        self.assertEqual((r["_operation"]["status"], r["_operation"]["verification"]), ("partial", "contradiction"))
        self.assertIn("Marker 1", " ".join(r["_operation"]["warnings"]))

    def test_older_bridge_is_refused_before_writing(self):
        f = self.fake(clip_markers_by_source=False)
        r = dispatch.run("move_item", {"item_id": "a", "record": 1400, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "blocked")
        self.assertIn("bridge", r["reason"])
        self.assertFalse({"duplicate_timeline", "append_clips", "delete_items"} & set(f.calls))
