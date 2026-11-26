"""place_clips links a clip's video and audio placed as separate parts of one call (docs/ISSUES.md I-37): Resolve
links the parts of one clipInfo only, and one clipInfo puts both on the same track number."""
from tests.support import Base, FakeResolve, sample_items

from resolve_editor import dispatch

SPLIT = [{"clip": "c1", "start_frame": 0, "end_frame": 30, "record": 1200, "track_index": 3, "media_type": 1},
         {"clip": "c1", "start_frame": 0, "end_frame": 30, "record": 1200, "track_index": 1, "media_type": 2}]


class LinkSplitParts(Base):
    def place(self, clips, **more):
        self.f = self.use(FakeResolve(sample_items()))
        preview = dispatch.run("place_clips", {"clips": clips, **more})
        return preview, dispatch.run("place_clips", {"clips": clips, **more, "confirm": True, "timeline": "T"})

    def placed(self):
        return {(x["track_type"], x["track"]): x["id"] for x in self.f.items if x["start"] == 1200}

    def linked(self, item_id):
        return self.f.settings[item_id]["linked"]

    def test_video_and_audio_of_one_clip_and_range_are_linked(self):
        preview, r = self.place(SPLIT)
        self.assertEqual(r["_operation"]["status"], "success", r)
        ids = self.placed()
        self.assertEqual(self.linked(ids[("video", 3)]), [ids[("audio", 1)]])
        self.assertEqual(self.linked(ids[("audio", 1)]), [ids[("video", 3)]])
        self.assertEqual(r["_operation"]["changes"]["linked"], 1)
        self.assertFalse(any("will be linked" in w for w in r["_operation"]["warnings"]), r)
        self.assertTrue(any("V3" in w and "A1" in w and "linked" in w for w in preview["_operation"]["warnings"]),
                        preview)

    def test_parts_of_other_ranges_or_places_are_not_linked(self):
        for change in ({"end_frame": 40}, {"start_frame": 5, "end_frame": 35}, {"record": 1260}):
            with self.subTest(change):
                _, r = self.place([SPLIT[0], {**SPLIT[1], **change}])
                self.assertIn(r["_operation"]["status"], ("success", "partial"), r)
                self.assertTrue(all(not s.get("linked") for s in self.f.settings.values()), change)
                self.assertNotIn("link_items", self.f.calls)

    def test_link_false_keeps_them_apart_and_says_so(self):
        preview, r = self.place(SPLIT, link=False)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertNotIn("link_items", self.f.calls)
        self.assertTrue(any("stay unlinked" in w for w in preview["_operation"]["warnings"]), preview)

    def test_a_link_that_doesnt_read_back_is_partial_and_names_both(self):
        self.f = self.use(FakeResolve(sample_items()))
        self.f.refuse_link = True
        r = dispatch.run("place_clips", {"clips": SPLIT, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "partial", r)
        ids = self.placed()
        warning = next(w for w in r["_operation"]["warnings"] if "not linked" in w)
        self.assertIn(ids[("video", 3)], warning)
        self.assertIn(ids[("audio", 1)], warning)
        self.assertEqual(r["_operation"]["changes"]["clips_placed"], 2)

    def test_a_whole_clip_is_left_to_resolve(self):
        _, r = self.place([{"clip": "c1", "start_frame": 0, "end_frame": 30, "record": 1200}])
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertNotIn("link_items", self.f.calls)

    def test_one_audio_part_links_only_one_video_part(self):
        _, r = self.place([SPLIT[0], {**SPLIT[0], "track_index": 2}, SPLIT[1]])
        self.assertEqual(r["_operation"]["changes"]["linked"], 1, r)
        ids = self.placed()
        self.assertEqual(self.linked(ids[("audio", 1)]), [ids[("video", 3)]])
        self.assertEqual(self.linked(ids[("video", 2)]), [])
