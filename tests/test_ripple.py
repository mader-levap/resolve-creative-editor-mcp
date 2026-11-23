"""Ripple trim."""
from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch, session


class Ripple(Base):
    def test_ripple_trim_keeps_gaps_and_titles(self):
        titles = [item("t1", 1000, 100, name="Text+"), item("t2", 1110, 50, name="Text+"),
                  item("t3", 1200, 100, name="Text+"), item("up", 1250, 20, name="Text+", track=2)]
        f = self.use(FakeResolve(titles, details={i: {"fusion_comps": 1, "media_id": None}
                                                  for i in ("t1", "t2", "t3", "up")}))
        r = dispatch.run("ripple_trim", {"item_ids": ["t1", "t3"], "tail_frames": 30})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertNotIn("trim_tail", f.calls)
        self.assertEqual(r["plan"]["trim"][1]["now"], [session.to_tc(1170), session.to_tc(1240)])
        r = dispatch.run("ripple_trim", {"item_ids": ["t1", "t3"], "tail_frames": 30, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        got = {x["id"]: (x["start"], x["end"]) for x in f.items}
        self.assertEqual(got, {"t1": (1000, 1070), "t2": (1080, 1130), "t3": (1170, 1240), "up": (1220, 1240)})
        self.assertNotIn("copy_settings", f.calls)  # nothing was rebuilt
        self.assertLess(f.calls.index("duplicate_timeline"), f.calls.index("trim_tail"))

    def test_ripple_trim_refusals(self):
        self.use(FakeResolve([item("a", 1000, 100), item("b", 1080, 100, track=2)]))
        self.assertIn("overlaps", dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30})["reason"])
        self.use(FakeResolve([item("a", 1000, 100)], details={"a": {"linked": ["x"]}}))
        self.assertIn("linked", dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30})["reason"])
        self.use(FakeResolve([item("a", 1000, 20)]))
        self.assertIn("only 20", dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30})["reason"])
        self.assertIn("positive", dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": -5})["reason"])

    def test_ripple_trim_restores_end_when_ripple_fails(self):
        f = self.use(FakeResolve([item("a", 1000, 100, name="Text+"), item("b", 1200, 100, name="Text+")],
                                 fail_on={"delete_items": 1}))
        r = dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertEqual({x["id"]: (x["start"], x["end"]) for x in f.items}, {"a": (1000, 1100), "b": (1200, 1300)})

    def test_ripple_trim_fails_when_the_timeline_does_not_match_the_plan(self):
        f = FakeResolve([item("a", 1000, 100, name="Text+"), item("b", 1200, 100, name="Text+")])

        def no_ripple(op, args, **kw):  # Resolve deletes the filler but doesn't shift what follows
            return f(op, dict(args, ripple=False) if op == "delete_items" else args, **kw)
        self.use(no_ripple)
        r = dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertIn("doesn't match the plan", r["reason"])
        self.assertEqual(r["_operation"]["changes"], {"trimmed": 0})
        self.assertTrue(any("expected" in w for w in r["_operation"]["warnings"]), r)
        self.assertTrue(r["snapshot"])


def tr(id, start, dur, track=1, kind="video"):
    return item(id, start, dur, name="Cross Dissolve", track=track, kind=kind, type="transition")


class RippleTransitions(Base):
    """A ripple delete shifts every track, so transitions anywhere count (ISSUES.md I-05)."""

    def test_a_transition_over_the_removed_frames_blocks_on_any_track(self):
        for track, kind, label in ((1, "audio", "A1"), (2, "video", "V2"), (1, "video", "V1")):
            with self.subTest(track=label):
                f = self.use(FakeResolve([item("a", 1000, 100), tr("x", 1080, 40, track, kind)]))
                r = dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30})
                self.assertEqual(r["_operation"]["status"], "blocked", r)
                self.assertIn("transition", r["reason"])
                if label != "V1":
                    self.assertIn(label, r["reason"])
                self.assertNotIn("trim_tail", f.calls)

    def test_transitions_clear_of_the_removed_frames_are_checked_after(self):
        f = self.use(FakeResolve([item("a", 1000, 100), item("b", 1200, 100, track=2),
                                  tr("early", 1040, 30, 1, "audio"), tr("late", 1150, 20, 2)]))
        self.assertEqual(dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30})["_operation"]["status"],
                         "preview")
        r = dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True, "timeline": "T"})
        self.assertEqual((r["_operation"]["status"], r["_operation"]["verification"]), ("success", "passed"), r)
        got = {x["id"]: (x["start"], x["end"]) for x in f.items}
        self.assertEqual(got["early"], (1040, 1070))
        self.assertEqual(got["late"], (1120, 1140))

    def test_a_transition_left_behind_is_a_failure(self):
        f = FakeResolve([item("a", 1000, 100), item("b", 1200, 100, track=2), tr("late", 1150, 20, 2)])

        def transitions_stay(op, args, **kw):  # Resolve shifts the clips but not the transition
            kept = {x["id"]: (x["start"], x["end"]) for x in f.items if x["type"] == "transition"}
            r = f(op, args, **kw)
            for x in f.items:
                if x["id"] in kept:
                    x["start"], x["end"] = kept[x["id"]]
            return r
        self.use(transitions_stay)
        r = dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertIn("Cross Dissolve", " ".join(r["_operation"]["warnings"]))
