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
        r = dispatch.run("ripple_trim", {"item_ids": ["t1", "t3"], "tail_frames": 30, "confirm": True})
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
        r = dispatch.run("ripple_trim", {"item_ids": ["a"], "tail_frames": 30, "confirm": True})
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertEqual({x["id"]: (x["start"], x["end"]) for x in f.items}, {"a": (1000, 1100), "b": (1200, 1300)})
