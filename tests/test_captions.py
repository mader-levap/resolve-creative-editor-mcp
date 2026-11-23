"""Captions and SRT."""
from tests.support import Base, FakeResolve

from resolve_editor import dispatch
from resolve_editor.tools import captions


class Captions(Base):
    def test_split_and_no_overlap(self):
        segs = captions.split_segments(
            [{"start": 0, "end": 4, "text": "one two three four five six seven eight nine ten"},
             {"start": 3.5, "end": 5, "text": "next"}], max_chars=20, line_split="sequence")
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
        """docs/ISSUES.md I-21: a 12 s caption, then a 1 s one, with Resolve's default 5 s title."""
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



class Lines(Base):
    """Long lines one under another by default, one after another as an option."""

    SIXTY = "the quick brown fox jumps over the lazy dog and runs far away"  # 61 characters

    def test_default_stacks_lines_in_one_caption_over_the_whole_time(self):
        segs = captions.split_segments([{"start": 1, "end": 4, "text": self.SIXTY}])
        self.assertEqual(len(segs), 1, segs)
        self.assertEqual((segs[0]["start"], segs[0]["end"]), (1, 4))
        lines = segs[0]["text"].split("\n")
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(all(len(x) <= 42 for x in lines), lines)
        self.assertEqual(" ".join(lines), self.SIXTY)

    def test_lines_are_balanced(self):
        segs = captions.split_segments([{"start": 0, "end": 2, "text": "one two three four five six"}], max_chars=20)
        self.assertEqual(segs[0]["text"], "one two three\nfour five six")

    def test_more_lines_than_max_lines_become_screens_one_after_another(self):
        text = " ".join(f"word{i:02d}" for i in range(25))  # 174 characters: 5 lines of 42
        segs = captions.split_segments([{"start": 0, "end": 10, "text": text}], max_lines=2)
        self.assertEqual(len(segs), 3, segs)
        self.assertEqual((segs[0]["start"], segs[-1]["end"]), (0, 10))
        for a, b in zip(segs, segs[1:], strict=False):
            self.assertEqual(a["end"], b["start"])
        self.assertTrue(all(len(s["text"].split("\n")) <= 2 for s in segs), segs)
        self.assertEqual(" ".join(s["text"].replace("\n", " ") for s in segs), text)
        three = captions.split_segments([{"start": 0, "end": 10, "text": text}], max_lines=3)
        self.assertEqual([len(s["text"].split("\n")) for s in three], [3, 2])

    def test_sequence_keeps_one_line_per_caption(self):
        segs = captions.split_segments([{"start": 1, "end": 4, "text": self.SIXTY}], line_split="sequence")
        self.assertEqual(len(segs), 2, segs)
        self.assertTrue(all("\n" not in s["text"] for s in segs))
        self.assertEqual((segs[0]["start"], segs[-1]["end"]), (1, 4))

    def test_a_word_longer_than_max_chars_stays_one_line(self):
        segs = captions.split_segments([{"start": 0, "end": 1, "text": "x" * 50}])
        self.assertEqual(segs[0]["text"], "x" * 50)

    def test_srt_cue_has_both_lines(self):
        srt = captions.to_srt(captions.split_segments([{"start": 0, "end": 2, "text": self.SIXTY}]))
        self.assertEqual(srt.split("\n")[2:5], ["the quick brown fox jumps over", "the lazy dog and runs far away", ""])

    def test_tool_passes_the_options_and_refuses_an_unknown_one(self):
        self.use(FakeResolve([]))
        seg = [{"start": 0, "end": 3, "text": self.SIXTY}]
        r = dispatch.run("add_captions", {"segments": seg})
        self.assertEqual(r["plan"]["count"], 1)
        r = dispatch.run("add_captions", {"segments": seg, "line_split": "sequence"})
        self.assertEqual(r["plan"]["count"], 2)
        long = [{"start": 0, "end": 3, "text": " ".join(["word"] * 20)}]  # 3 lines of up to 42
        self.assertEqual(dispatch.run("add_captions", {"segments": long})["plan"]["count"], 2)
        self.assertEqual(dispatch.run("add_captions", {"segments": long, "max_lines": 3})["plan"]["count"], 1)
        with self.assertRaisesRegex(ValueError, "line_split must be one of stack, sequence"):
            dispatch.run("add_captions", {"segments": seg, "line_split": "sideways"})
        with self.assertRaisesRegex(ValueError, "max_lines must be at least 1"):
            dispatch.run("add_captions", {"segments": seg, "max_lines": 0})

    def test_schema_offers_the_options(self):
        from resolve_editor.schemas import edit as schema
        for name in ("add_captions", "export_srt"):
            props = next(t for t in schema.TOOLS if t["name"] == name)["inputSchema"]["properties"]
            self.assertEqual(props["line_split"]["enum"], ["stack", "sequence"])
            self.assertIn("max_lines", props)


class Anchor(Base):
    """Captions sit on their bottom line, so extra lines grow upward (live 2026-11-23: VerticalTopCenterBottom 1)."""

    def place(self, **extra):
        f = self.use(FakeResolve([]))
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 2, "text": "hi"}], "confirm": True,
                                          "timeline": "T", "track_index": 2, **extra})
        self.assertEqual(r["_operation"]["status"], "success", r)
        return f.title_args

    def test_bottom_by_default_with_the_style(self):
        args = self.place(font="Normograf", size=0.034, y=0.08)
        self.assertEqual(args["inputs"], {"VerticalTopCenterBottom": 1})
        self.assertEqual((args["font"], args["size"], args["y"]), ("Normograf", 0.034, 0.08))

    def test_center_sends_no_anchor(self):
        self.assertNotIn("inputs", self.place(anchor="center"))

    def test_unknown_anchor_is_refused(self):
        self.use(FakeResolve([]))
        with self.assertRaisesRegex(ValueError, "anchor must be bottom or center"):
            dispatch.run("add_captions", {"segments": [{"start": 0, "end": 2, "text": "hi"}], "anchor": "top"})

    def test_schema_offers_anchor(self):
        from resolve_editor.schemas import edit as schema
        props = next(t for t in schema.TOOLS if t["name"] == "add_captions")["inputSchema"]["properties"]
        self.assertEqual(props["anchor"]["enum"], ["bottom", "center"])
