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

    def test_cards_cap_at_five_seconds(self):
        cards = captions.caption_cards([{"start": 0, "end": 7, "text": "long"}], 30, 1000, "T")
        self.assertEqual([(c["record_frame"], c["frames"]) for c in cards], [(1000, 150), (1150, 60)])
        self.assertEqual(len({c["name"] for c in cards}), 2)

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
