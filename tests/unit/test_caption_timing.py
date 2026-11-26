"""A title's GlobalIn/GlobalOut (when its Text+ runs) must not reach a caption, and read_titles warns about a caption
placed past them (docs/ISSUES.md I-38): Resolve shows "No frame available for MediaOut1" there."""
from tests.support import Base, FakeResolve, item
from tests.unit.test_titles import HELLO, style_only, timeline

from resolve_editor import dispatch
from resolve_editor.tools import titles

TIMED = dict(HELLO, GlobalIn=0, GlobalOut=59)  # a 60-frame title, as Resolve reports it


def timed():
    f = timeline()
    f.title_inputs["hello"] = dict(TIMED)
    return f


class TimingIsNotCopied(Base):
    def test_text_style_leaves_out_global_in_and_out(self):
        self.assertEqual(titles.text_style(TIMED), style_only(HELLO))

    def test_titles_to_captions_doesnt_send_the_titles_global_out(self):
        f = self.use(timed())
        r = dispatch.run("titles_to_captions", {"item_ids": ["hello"], "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)
        card = f.title_calls[0]["cards"][0]
        self.assertEqual(card["inputs"], style_only(HELLO))

    def test_add_captions_match_doesnt_send_it(self):
        f = self.use(timed())
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}], "match": "hello",
                                          "track_index": 4, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertFalse({"GlobalIn", "GlobalOut"} & set(f.title_args["inputs"]), f.title_args["inputs"])

    def test_explicit_global_in_or_out_is_refused(self):
        for key in ("GlobalIn", "GlobalOut"):
            with self.subTest(key):
                f = self.use(timed())
                with self.assertRaisesRegex(ValueError, key):
                    dispatch.run("add_captions", {"segments": [{"start": 0, "end": 1, "text": "hi"}],
                                                  "inputs": {key: 10}, "confirm": True, "timeline": "T"})
                self.assertNotIn("add_title_cards", f.calls)


class StretchedCaptionWarning(Base):
    """A 30 fps timeline from frame 1000; the caption's own timeline is 900 frames with its Text+ running 0-179."""

    def row(self, frames, src=0, kind="caption", global_in=0, global_out=179):
        name = "T 1126-120000 caption 0001" if kind == "caption" else "Text+"
        f = FakeResolve([item("c", 1000, frames, src=src, name=name, track=2)])
        inputs = {"StyledText": "x", "GlobalIn": global_in, "GlobalOut": global_out}
        if kind == "caption":
            f.caption_text = {name: "x"}
            f.caption_inputs = {name: inputs}
        else:
            f.title_inputs = {"c": inputs}
        self.use(f)
        return dispatch.run("read_titles", {})["titles"][0]

    def test_a_caption_placed_past_global_out_is_warned_about(self):
        warning = self.row(205)["warning"]
        self.assertIn("00:00:39:10", warning)  # frame 1000 + 180 at 30 fps
        self.assertIn("GlobalOut 179", warning)
        self.assertIn("25 frames", warning)
        self.assertIn("MediaOut1", warning)

    def test_a_caption_that_ends_with_its_text_isnt(self):
        self.assertNotIn("warning", self.row(180))

    def test_the_placements_offset_into_its_own_timeline_counts(self):
        self.assertNotIn("warning", self.row(150, src=30))
        self.assertIn("1 frames", self.row(151, src=30)["warning"])

    def test_a_caption_that_starts_before_global_in_is_warned_about(self):
        warning = self.row(60, global_in=10)["warning"]
        self.assertIn("GlobalIn 10", warning)
        self.assertIn("10 frames", warning)

    def test_a_title_isnt_checked(self):
        self.assertNotIn("warning", self.row(205, kind="title"))
