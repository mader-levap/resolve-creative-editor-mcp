"""add_transition previews first (ISSUES.md I-06) and checks what Resolve made against the request (I-04)."""
from tests.support import READ_OPS, Base, FakeResolve, item

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
        args.setdefault("confirm", True)
        args.setdefault("timeline", "T")
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


class TransitionPreview(Base):
    """Nothing is written without confirm=true, and a confirmed transition is backed up first (ISSUES.md I-06)."""

    def setUp(self):
        self.f = self.use(timeline())
        self.f.media_frames = 2275

    def writes(self):
        return [c for c in self.f.calls if c not in READ_OPS and c != "set_current_timeline"]

    def test_preview_shows_the_cut_span_and_spare_frames_and_writes_nothing(self):
        for args in ({"item_id": "a", "position": "end"}, {"item_id": "b", "position": "start"}):
            with self.subTest(**args):
                r = dispatch.run("add_transition", dict(args, duration=30))
                self.assertEqual(r["_operation"]["status"], "preview", r)
                plan = r["plan"]
                self.assertEqual(plan["cut"], session.to_tc(CUT))
                self.assertEqual(plan["track"], "V1")
                self.assertEqual(plan["span"], [session.to_tc(CUT - 15), session.to_tc(CUT + 15)])
                self.assertEqual(plan["spare_source_frames"], {"after the outgoing clip": 2275 - 480,
                                                               "before the incoming clip": 1500})
                self.assertEqual(r["timeline"], "T")
        self.assertEqual(self.writes(), [])

    def test_without_a_duration_there_is_no_span(self):
        r = dispatch.run("add_transition", {"item_id": "a"})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertNotIn("span", r["plan"])
        self.assertIn("default", str(r["plan"]["frames"]))

    def test_spare_frames_say_when_there_is_no_clip_or_media(self):
        f = self.use(FakeResolve([item("a", 1000, 300, src=180), item("t", 1300, 300, name="Text+")],
                                 details={"t": {"media_id": None}}))
        f.media_frames = 2275
        spare = dispatch.run("add_transition", {"item_id": "a", "duration": 30})["plan"]["spare_source_frames"]
        self.assertEqual(spare["after the outgoing clip"], 1795)
        self.assertIn("unknown", spare["before the incoming clip"])
        spare = dispatch.run("add_transition", {"item_id": "a", "position": "start", "duration": 30})["plan"][
            "spare_source_frames"]
        self.assertIn("no clip", spare["after the outgoing clip"])
        self.assertEqual(spare["before the incoming clip"], 180)

    def test_unknown_item_is_blocked_in_the_preview(self):
        r = dispatch.run("add_transition", {"item_id": "nope"})
        self.assertEqual(r["_operation"]["status"], "blocked")

    def test_confirm_needs_the_previewed_timeline(self):
        r = dispatch.run("add_transition", {"item_id": "a", "duration": 30, "confirm": True})
        self.assertEqual(r["_operation"]["status"], "blocked")
        self.assertEqual(self.writes(), [])

    def test_confirm_backs_up_first_and_returns_the_snapshot(self):
        r = dispatch.run("add_transition", {"item_id": "a", "duration": 30, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertTrue(r["snapshot"])
        self.assertEqual(self.writes()[:2], ["duplicate_timeline", "add_transition"])
