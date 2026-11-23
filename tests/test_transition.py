"""add_transition checks what Resolve made against the request (ISSUES.md I-04)."""
from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch, session

CUT = 1300


def timeline():
    """Two linked clips cut at 1300, as in the live T2 setup."""
    return FakeResolve([item("a", 1000, 300, src=180), item("b", CUT, 300, src=1500),
                        item("a2", 1000, 300, src=180, kind="audio"), item("b2", CUT, 300, src=1500, kind="audio")])


def span(alignment, d):
    """Resolve 21.2, live T2: left ends at the cut, right starts there, center puts an odd frame before it."""
    return {"left": (CUT - d, CUT), "right": (CUT, CUT + d)}.get(alignment, (CUT - (d + 1) // 2, CUT + d // 2))


class TransitionReadBack(Base):
    def add(self, misbehave=None, **args):
        f = self.use(timeline())
        f.misbehave = misbehave or {}
        args.setdefault("item_id", "a")
        r = dispatch.run("add_transition", args)
        return r, f

    def verdict(self, r):
        return r["_operation"]["status"], r["_operation"]["verification"]

    def test_correct_transition_passes_with_its_span(self):
        for position, item_id in (("end", "a"), ("start", "b")):
            for alignment in ("left", "center", "right"):
                for d in (30, 31):
                    with self.subTest(position=position, alignment=alignment, duration=d):
                        r, _ = self.add(item_id=item_id, position=position, alignment=alignment, duration=d)
                        self.assertEqual(self.verdict(r), ("success", "passed"), r)
                        start, end = span(alignment, d)
                        self.assertEqual((r["start"], r["end"], r["cut"]),
                                         (session.to_tc(start), session.to_tc(end), session.to_tc(CUT)))
                        self.assertEqual(r["_operation"]["changes"]["frames"], d)

    def test_audio_transition_on_audio_track_passes(self):
        r, _ = self.add(item_id="a2", type="Cross Fade +3 dB", category="audio", duration=30)
        self.assertEqual(self.verdict(r), ("success", "passed"), r)

    def test_without_duration_the_rest_is_still_checked(self):
        r, _ = self.add()
        self.assertEqual(self.verdict(r), ("success", "passed"), r)
        self.assertEqual(r["_operation"]["changes"]["frames"], 10)  # Resolve's choice, reported
        r, _ = self.add({"shift": 2})
        self.assertEqual(self.verdict(r), ("partial", "contradiction"), r)

    def test_what_differs_is_a_contradiction(self):
        cases = {"type": ({"type": "Wipe"}, "Wipe"), "category": ({"category": "fusion"}, "fusion"),
                 "alignment": ({"alignment": "left"}, "alignment"), "track": ({"track": 2}, "track"),
                 "track type": ({"track_type": "audio"}, "track"), "span": ({"shift": 1}, "span"),
                 "length": ({"duration": 20}, "20"), "clip changed": ({"move_clip": "b"}, "b"),
                 "not on the timeline": ({"lost": True}, "not found")}
        for case, (misbehave, named) in cases.items():
            with self.subTest(case):
                r, _ = self.add(misbehave, duration=30)
                self.assertEqual(self.verdict(r), ("partial", "contradiction"), r)
                self.assertIn(named, " ".join(r["_operation"]["warnings"]))

    def test_unreadable_properties_are_unverified(self):
        r, _ = self.add({"no_props": True}, duration=30)
        self.assertEqual(self.verdict(r), ("success", "unverified"), r)
        self.assertIn("type", " ".join(r["_operation"]["warnings"]))

    def test_unknown_item_is_blocked_before_writing(self):
        r, f = self.add(item_id="nope")
        self.assertEqual(r["_operation"]["status"], "blocked")
        self.assertNotIn("add_transition", f.calls)
