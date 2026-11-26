"""Clips at another frame rate than the timeline (live probe 2026-11-26, docs/ISSUES.md I-34, I-35, I-36): the listed
left offset and the duration are timeline frames, GetSourceStartFrame/GetSourceEndFrame are the clip's own frames."""
from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch


def at_30_on_60(*more, speed=None):
    """Clip "a" (30 fps media, 300 frames) placed from source frame 6 to 66 on a 60 fps timeline: 120 frames long,
    listed with a left offset of 12. "b" follows it from source frame 10 (listed 20)."""
    f = FakeResolve([item("a", 1000, 120, src=12), item("b", 1120, 120, src=20), *more], fps=30)
    f.timeline_fps = 60
    if speed:
        f.settings["a"]["speed"] = {"Percentage": speed}
    return f


class InspectRange(Base):
    """I-36: source_start is the clip's own frame, with its rate when that differs from the timeline's."""

    def row(self, f, item_id="a"):
        self.use(f)
        r = dispatch.run("inspect_range", {"start": 1000, "end": 1300})
        return next(x for x in r["items"] if x["id"] == item_id)

    def test_a_clip_at_another_rate_shows_its_own_frames_and_rate(self):
        row = self.row(at_30_on_60())
        self.assertEqual((row["source_start"], row["clip_fps"]), (6, 30))
        self.assertEqual(row["frames"], 120)  # timeline frames, as before

    def test_a_clip_at_the_timelines_rate_is_unchanged(self):
        f = FakeResolve([item("a", 1000, 120, src=12)], fps=60)
        f.timeline_fps = 60
        row = self.row(f)
        self.assertEqual(row["source_start"], 12)
        self.assertNotIn("clip_fps", row)


class SpareFrames(Base):
    """I-35: spare frames of a clip at another rate, in timeline frames, the unit a transition needs."""

    def spare(self, f):
        self.use(f)
        r = dispatch.run("add_transition", {"item_id": "a", "position": "end", "duration": 12})
        return r["plan"]["spare_source_frames"]

    def test_both_sides_are_given_in_timeline_frames(self):
        spare = self.spare(at_30_on_60())
        # after "a": (300 - 66) source frames = 468 timeline frames; before "b": its left offset, 20
        self.assertEqual(spare, {"after the outgoing clip": 468, "before the incoming clip": 20})

    def test_a_speed_change_is_still_unknown(self):
        spare = self.spare(at_30_on_60(speed=50))
        self.assertIn("unknown", spare["after the outgoing clip"])


class Rebuild(Base):
    """I-34: move_item and trim_item work on a clip at another rate when the new range is whole source frames."""

    def run_tool(self, tool, **args):
        self.f = self.use(at_30_on_60())
        preview = dispatch.run(tool, {"item_id": "a", **args})
        if preview["_operation"]["status"] != "preview":
            return preview, None
        return preview, dispatch.run(tool, {"item_id": "a", **args, "confirm": True, "timeline": "T"})

    def new_item(self, result):
        new_id = result["_operation"]["changes"]["replaced"][0]["new_id"]
        x = next(x for x in self.f.items if x["id"] == new_id)
        d = self.f._source_frames(new_id)
        return x["start"], x["duration"], d["source_start"], d["source_end"]

    def test_a_move_keeps_the_source_range(self):
        preview, r = self.run_tool("move_item", record=1300)
        self.assertEqual(preview["plan"]["move"][0]["to"][1], 120, preview)  # timeline frames
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(self.new_item(r), (1300, 120, 6, 66))

    def test_a_trim_by_whole_source_frames_works(self):
        _, r = self.run_tool("trim_item", head_frames=4, tail_frames=2)  # 2 and 1 source frames
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(self.new_item(r), (1004, 114, 8, 65))

    def test_a_trim_that_would_split_a_source_frame_is_refused(self):
        preview, r = self.run_tool("trim_item", head_frames=3)
        self.assertEqual(preview["_operation"]["status"], "blocked", preview)
        self.assertIn("whole source frames", preview["reason"])
        self.assertIsNone(r)

    def test_the_range_is_anchored_at_the_source_start_frame_not_the_rounded_offset(self):
        # a 25 fps clip from source frame 7 on a 30 fps timeline: 7 x 30/25 = 8.4, listed rounded as 8
        f = FakeResolve([item("a", 1000, 12, src=8)], fps=25)
        f.timeline_fps = 30
        f.settings["a"].update(source_start=7, source_end=17)
        self.f = self.use(f)
        args = {"item_id": "a", "record": 1300}
        dispatch.run("move_item", args)
        r = dispatch.run("move_item", {**args, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual(self.new_item(r), (1300, 12, 7, 17))
