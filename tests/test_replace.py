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
        r = dispatch.run("move_item", {"item_id": "a", "record": "00:00:35:00", "confirm": True})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        moved = [x for x in f.items if x["track"] == 1]
        self.assertEqual([(x["start"], x["source_start"]) for x in moved], [(1050, 5)])
        self.assertEqual(f.settings[moved[0]["id"]]["properties"], {"ZoomX": 1.5})
        self.assertEqual(f.tracks["video"], 1, "staging track removed")

    def test_backup_made_before_edit(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True})
        self.assertTrue(r["snapshot"].startswith("T before edit"))
        self.assertLess(f.calls.index("duplicate_timeline"), f.calls.index("add_track"))

    def test_original_deleted_only_after_replacement_is_ready(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "backup": False})
        self.assertLess(f.calls.index("copy_settings"), f.calls.index("delete_items"))

    def test_staging_failure_leaves_original(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)], fail_on={"copy_settings": 1}))
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "backup": False})
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
        r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True, "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed")
        back = [x for x in f.items if x["track"] == 1]
        self.assertEqual([(x["start"], x["source_start"], x["duration"]) for x in back], [(1000, 5, 10)])
        self.assertEqual(f.settings[back[0]["id"]]["properties"], {"ZoomX": 1.5})

    def test_trim_moves_linked_audio_too(self):
        items = [item("v", 1000, 60, src=10), item("a", 1000, 60, src=10, kind="audio")]
        f = self.use(FakeResolve(items, details={"v": {"linked": ["a"]}, "a": {"linked": ["v"]}}))
        r = dispatch.run("trim_item", {"item_id": "v", "head_frames": 5, "tail_frames": 10, "confirm": True,
                                       "backup": False})
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
            r = dispatch.run("move_item", {"item_id": "a", "record": 1050, "confirm": True})
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
