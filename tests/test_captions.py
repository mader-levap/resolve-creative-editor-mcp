"""Captions and SRT."""
from tests.support import Base, FakeResolve

from resolve_editor import dispatch
from resolve_editor.tools import captions


class Captions(Base):
    def test_split_and_no_overlap(self):
        segs = captions.split_segments(
            [{"start": 0, "end": 4, "text": "one two three four five six seven eight nine ten"},
             {"start": 3.5, "end": 5, "text": "next"}], max_chars=20)
        self.assertTrue(all(len(s["text"]) <= 20 for s in segs))
        for a, b in zip(segs, segs[1:], strict=False):
            self.assertLessEqual(a["end"], b["start"])

    def test_one_card_per_caption(self):
        cards = captions.caption_cards([{"start": 0, "end": 12, "text": "long"}], 60, 1000, "T")
        self.assertEqual([(c["record_frame"], c["frames"]) for c in cards], [(1000, 720)])

    def test_names_are_unique_and_keep_the_number(self):
        segs = [{"start": i, "end": i + 0.5, "text": "x"} for i in range(3)]
        names = [c["name"] for c in captions.caption_cards(segs, 30, 1000, "N" * 150, "1123-120000")]
        self.assertEqual(len(set(names)), 3)
        self.assertTrue(all(len(n) <= 120 for n in names), names)
        self.assertTrue(names[2].endswith(" caption 0003"), names)

    def test_long_caption_and_the_next_are_placed_at_any_rate(self):
        """ISSUES.md I-21: a 12 s caption, then a 1 s one, with Resolve's default 5 s title."""
        segs = [{"start": 0, "end": 12, "text": "a long one"}, {"start": 12.5, "end": 13.5, "text": "next"}]
        for fps in (24, 30, 60):
            with self.subTest(fps=fps):
                f = FakeResolve([], fps=fps)
                f.timeline_fps, f.title_frames = fps, 5 * fps
                self.use(f)
                r = dispatch.run("add_captions", {"segments": segs, "confirm": True, "timeline": "T", "track_index": 2})
                self.assertEqual(r["_operation"]["status"], "success", r)
                self.assertEqual(r["_operation"]["changes"]["captions_added"], 2, r)
                for card, (start, frames) in ((1, (1000, 12 * fps)), (2, (1000 + 25 * fps // 2, fps))):
                    parts = sorted((p for p in f.parts if p.get("card") == card), key=lambda p: p["start"])
                    self.assertEqual(parts[0]["start"], start)
                    self.assertEqual([p["start"] for p in parts[1:]], [p["end"] for p in parts[:-1]], "no gaps")
                    self.assertEqual(sum(p["duration"] for p in parts), frames)
                    self.assertTrue(all(p["duration"] <= f.title_frames for p in parts))

    def test_a_caption_counts_only_when_its_parts_cover_it(self):
        card = [{"record_frame": 100, "frames": 300}]

        def parts(*spans):
            return [{"card": 1, "start": s, "duration": d} for s, d in spans]
        self.assertEqual(captions._complete(card, parts((100, 150), (250, 150))), 1)
        self.assertEqual(captions._complete(card, parts((250, 150), (100, 150))), 1, "order doesn't matter")
        self.assertEqual(captions._complete(card, parts((100, 150), (260, 150))), 0, "a gap, right total")
        self.assertEqual(captions._complete(card, parts((90, 150), (250, 150))), 0, "overlap, right total")
        self.assertEqual(captions._complete(card, parts((100, 150))), 0, "too short")
        self.assertEqual(captions._complete(card, [dict(x, card=2) for x in parts((100, 300))]), 0, "another card")

    def test_bridge_without_caption_parts_is_refused(self):
        f = self.use(FakeResolve([]))
        f.caption_parts = False
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "confirm": True,
                                          "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("bridge", r["reason"])
        self.assertFalse({"add_track", "add_title_cards"} & set(f.calls))

    def test_refused_part_gives_partial(self):
        f = FakeResolve([])
        f.title_frames, f.refuse_part = 150, 2  # the third part of the 12 s caption
        self.use(f)
        segs = [{"start": 0, "end": 12, "text": "a long one"}, {"start": 13, "end": 14, "text": "next"}]
        r = dispatch.run("add_captions", {"segments": segs, "confirm": True, "timeline": "T", "track_index": 2})
        self.assertEqual(r["_operation"]["status"], "partial", r)
        self.assertEqual((r["_operation"]["changes"]["captions_added"], r["_operation"]["changes"]["parts"]), (0, 2))
        self.assertIn("refused", " ".join(r["_operation"]["warnings"]))

    def test_add_captions_preview_then_apply(self):
        f = self.use(FakeResolve([]))
        segs = [{"start": 1, "end": 2.5, "text": "hi"}]
        r = dispatch.run("add_captions", {"segments": segs})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertNotIn("add_title_cards", f.calls)
        r = dispatch.run("add_captions", {"segments": segs, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["verification"], "passed", r)

    def test_srt(self):
        self.assertEqual(captions.to_srt([{"start": 61.5, "end": 62, "text": "hi"}]),
                         "1\n00:01:01,500 --> 00:01:02,000\nhi\n\n")
