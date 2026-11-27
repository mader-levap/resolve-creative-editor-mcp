"""add_transition previews first (docs/ISSUES.md I-06) and checks what Resolve made against the request (I-04)."""
from tests.support import READ_OPS, Base, FakeResolve, item

from resolve_editor import dispatch, session

CUT = 1300


def timeline():
    """Two clips cut at 1300, video and audio, as in the live T2 setup. The fake doesn't link them, so a video
    transition also crossfades the audio of the same source and range (docs/ISSUES.md I-31)."""
    f = FakeResolve([item("a", 1000, 300, src=180), item("b", CUT, 300, src=1500),
                     item("a2", 1000, 300, src=180, kind="audio"), item("b2", CUT, 300, src=1500, kind="audio")])
    f.media_frames = 2275  # 1795 unused frames after a
    return f


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
    """Nothing is written without confirm=true, and a confirmed transition is backed up first (docs/ISSUES.md I-06)."""

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


LINKS = {"a": {"linked": ["a2"]}, "a2": {"linked": ["a"]}, "b": {"linked": ["b2"]}, "b2": {"linked": ["b"]}}


def linked(a2_end=CUT):
    return _long(FakeResolve([item("a", 1000, 300, src=180), item("b", CUT, 300, src=1500),
                        item("a2", 1000, a2_end - 1000, src=180, kind="audio"),
                        item("b2", a2_end, 1600 - a2_end, src=1500, kind="audio")], details=LINKS))


def _long(f):
    f.media_frames = 2275
    return f


class LinkedAudio(Base):
    """A transition on a video clip also crossfades its linked audio, unless asked not to (docs/ISSUES.md I-07)."""

    def run_on(self, f, **args):
        self.use(f)
        sent: list[dict] = []
        real = f.transition

        def record(item_id, o):
            sent.append(dict(o, item_id=item_id))
            return real(item_id, o)
        f.transition = record
        args = {"item_id": "a", "confirm": True, "timeline": "T", **args}
        return dispatch.run("add_transition", args), sent

    def test_linked_audio_gets_a_matching_crossfade(self):
        r, sent = self.run_on(linked(), duration=30, alignment="left")
        self.assertEqual((r["_operation"]["status"], r["_operation"]["verification"]), ("success", "passed"), r)
        self.assertEqual([s["item_id"] for s in sent], ["a", "a2"])
        self.assertEqual({k: sent[1][k] for k in ("type", "category", "alignment", "duration", "position")},
                         {"type": "Cross Fade +3 dB", "category": "audio", "alignment": "left", "duration": 30,
                          "position": "end"})
        row = r["linked"][0]
        self.assertEqual((row["track"], row["start"], row["end"]), ("A1", session.to_tc(CUT - 30), session.to_tc(CUT)))
        self.assertTrue(row["transition_id"])

    def test_without_a_duration_the_audio_takes_the_video_length(self):
        r, sent = self.run_on(linked())
        self.assertEqual(sent[1]["duration"], 10)  # what the fake Resolve gave the video one
        self.assertEqual(r["_operation"]["status"], "success", r)

    def test_audio_type_can_be_chosen(self):
        _, sent = self.run_on(linked(), duration=30, audio_type="Cross Fade 0 dB")
        self.assertEqual(sent[1]["type"], "Cross Fade 0 dB")

    def test_include_linked_false_warns_about_the_hard_cut(self):
        r, sent = self.run_on(linked(), duration=30, include_linked=False)
        self.assertEqual(len(sent), 1)
        self.assertIn("A1 keeps a hard cut", " ".join(r["_operation"]["warnings"]))

    def test_refused_audio_is_partial_and_keeps_the_video_transition(self):
        f = linked()
        calls = {"n": 0}

        def refuse_second(op, args, **kw):
            if op == "add_transition":
                calls["n"] += 1
                if calls["n"] == 2:
                    f.calls.append(op)
                    return {"ok": False, "error": "Resolve refused the transition"}
            return f(op, args, **kw)
        self.use(refuse_second)
        r = dispatch.run("add_transition", {"item_id": "a", "duration": 30, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "partial", r)
        self.assertTrue(r["transition_id"])
        text = " ".join(r["_operation"]["warnings"])
        self.assertIn("A1", text)
        self.assertIn(r["transition_id"], text)

    def test_split_edit_gets_no_crossfade_and_a_warning(self):
        r, sent = self.run_on(linked(a2_end=CUT + 10), duration=30)
        self.assertEqual(len(sent), 1)
        self.assertIn("not at the cut", " ".join(r["_operation"]["warnings"]))

    def test_preview_lists_the_crossfade_and_writes_nothing(self):
        f = self.use(linked())
        r = dispatch.run("add_transition", {"item_id": "a", "duration": 30})
        self.assertEqual(r["plan"]["linked"][0]["track"], "A1")
        self.assertEqual(r["plan"]["linked"][0]["type"], "Cross Fade +3 dB")
        self.assertEqual([c for c in f.calls if c not in READ_OPS], [])
        r = dispatch.run("add_transition", {"item_id": "a", "duration": 30, "include_linked": False})
        self.assertIn("A1 keeps a hard cut", " ".join(r["_operation"]["warnings"]))

    def test_an_audio_target_adds_nothing_extra(self):  # unlinked video: UnlinkedAudio (I-31)
        r, sent = self.run_on(linked(), item_id="a2", type="Cross Fade +3 dB", category="audio", duration=30)
        self.assertEqual([s["item_id"] for s in sent], ["a2"])


def unlinked(a2=None, b2=None, media=None):
    """Video and audio of the same source and range on V1 and A1, not linked: Resolve lists no linked items
    (live 2026-11-26, docs/ISSUES.md I-31). a2/b2 override the audio items' fields; media their media ids."""
    f = FakeResolve([item("a", 1000, 300, src=180), item("b", CUT, 300, src=1500),
                     dict(item("a2", 1000, 300, src=180, kind="audio"), **(a2 or {})),
                     dict(item("b2", CUT, 300, src=1500, kind="audio"), **(b2 or {}))])
    for i, m in (media or {}).items():
        f.settings[i]["media_id"] = m
    return _long(f)


class UnlinkedAudio(Base):
    """Audio of the same source and range that isn't linked is crossfaded too; other audio at the cut is named in a
    warning (docs/ISSUES.md I-31)."""

    run_on = LinkedAudio.run_on

    def warnings(self, r):
        return " ".join(r["_operation"]["warnings"])

    def test_same_source_audio_at_the_cut_is_crossfaded_and_said(self):
        for position, video, audio in (("end", "a", "a2"), ("start", "b", "b2")):
            with self.subTest(position):
                r, sent = self.run_on(unlinked(), item_id=video, position=position, duration=30)
                self.assertEqual(r["_operation"]["status"], "success", r)
                self.assertEqual([(s["item_id"], s["category"]) for s in sent], [(video, "simple"), (audio, "audio")])
                self.assertEqual(r["linked"][0]["track"], "A1")
                self.assertIn("isn't linked", self.warnings(r))

    def test_the_preview_lists_it_and_writes_nothing(self):
        f = self.use(unlinked())
        r = dispatch.run("add_transition", {"item_id": "a", "duration": 30})
        self.assertEqual(r["plan"]["linked"][0]["track"], "A1")
        self.assertIn("isn't linked", self.warnings(r))
        self.assertEqual([c for c in f.calls if c not in READ_OPS], [])

    def test_include_linked_false_keeps_a_hard_cut_and_says_so(self):
        r, sent = self.run_on(unlinked(), duration=30, include_linked=False)
        self.assertEqual(len(sent), 1)
        self.assertIn("A1 keeps a hard cut", self.warnings(r))

    def test_other_audio_at_the_cut_is_named_and_left_alone(self):
        cases = {"another clip": {"a2": {"name": "music.wav"}}, "another range": {"a2": {"source_start": 0}},
                 "starts elsewhere": {"a2": {"start": 1100, "duration": 200}},
                 "another media": {"media": {"a2": "c9"}}}
        for case, kw in cases.items():
            with self.subTest(case):
                r, sent = self.run_on(unlinked(**kw), duration=30)
                self.assertEqual(r["_operation"]["status"], "success", r)
                self.assertEqual(len(sent), 1)
                self.assertNotIn("linked", r)
                self.assertIn("a2", self.warnings(r))
                self.assertIn("no crossfade", self.warnings(r))

    def test_audio_away_from_the_cut_adds_nothing(self):
        r, sent = self.run_on(unlinked(a2={"end": CUT - 10, "duration": 290}), duration=30)
        self.assertEqual(len(sent), 1)
        self.assertFalse([w for w in r["_operation"]["warnings"] if "a2" in w or "A1" in w], r)


class Duration(Base):
    """A duration is a whole number of frames above 0, or left out for Resolve's default (docs/ISSUES.md I-08)."""

    def test_bad_durations_are_blocked_before_anything_is_written(self):
        for bad in (0, -5, 2.5, "30", True):
            for confirm in ({}, {"confirm": True, "timeline": "T"}):
                with self.subTest(duration=bad, confirm=bool(confirm)):
                    f = self.use(timeline())
                    r = dispatch.run("add_transition", {"item_id": "a", "duration": bad, **confirm})
                    self.assertEqual(r["_operation"]["status"], "blocked", r)
                    self.assertIn(repr(bad), r["reason"])
                    self.assertFalse({"add_transition", "duplicate_timeline"} & set(f.calls))

    def test_none_means_resolves_default_and_one_frame_is_fine(self):
        self.use(timeline())
        r = dispatch.run("add_transition", {"item_id": "a", "duration": None})
        self.assertIn("default", str(r["plan"]["frames"]))
        r = dispatch.run("add_transition", {"item_id": "a", "duration": 1, "confirm": True, "timeline": "T"})
        self.assertEqual(r["_operation"]["status"], "success", r)

    def test_a_batch_stops_at_a_bad_duration(self):
        f = self.use(timeline())
        r = dispatch.run("batch", {"confirm": True, "timeline": "T", "operations": [
            {"tool": "add_transition", "args": {"item_id": "a", "duration": 0}},
            {"tool": "add_markers", "args": {"markers": [{"at": 1001, "name": "m"}]}}]})
        self.assertEqual(r["results"][0]["status"], "blocked")
        self.assertEqual(r["not_run"], ["add_markers"])
        self.assertNotIn("add_transition", f.calls)


class Refusal(Base):
    """A refusal is a failed result naming the likely cause from checked spare frames
    (docs/ISSUES.md I-09, live T3/T4)."""

    def refuse(self, media_frames=2275, **args):
        f = self.use(timeline())
        f.media_frames, f.misbehave = media_frames, {"refuse": True}
        args = {"item_id": "a", "duration": 30, "confirm": True, "timeline": "T", **args}
        return dispatch.run("add_transition", args)

    def test_a_refusal_is_failed_with_the_backup_and_spare_frames(self):
        r = self.refuse()
        self.assertEqual(r["_operation"]["status"], "failed", r)
        self.assertTrue(r["snapshot"])
        self.assertEqual(r["spare_source_frames"], {"after the outgoing clip": 1795, "before the incoming clip": 1500})
        self.assertIn("Resolve refused the transition", r["reason"])
        self.assertIn("aren't the cause", r["reason"])
        self.assertIn("type", r["reason"])

    def test_a_side_without_spare_frames_is_named_when_the_alignment_needs_it(self):
        r = self.refuse(media_frames=480)  # a's source ends at the media's last frame: 0 after the cut
        self.assertIn("no unused source frames after the outgoing clip", r["reason"])
        r = self.refuse(media_frames=480, alignment="left")  # left needs none there (live T3)
        self.assertNotIn("no unused source frames", r["reason"])
        self.assertIn("type", r["reason"])

    def test_other_bridge_errors_still_raise(self):
        self.use(FakeResolve([item("a", 1000, 300, src=180)], fail_on={"add_transition": 1}))
        with self.assertRaises(RuntimeError):
            dispatch.run("add_transition", {"item_id": "a", "duration": 30, "confirm": True, "timeline": "T"})


def clips(after=1795, before=1500):
    """a cut into b at 1300 with `after` unused frames after a and `before` before b (media of 480 + after frames)."""
    f = FakeResolve([item("a", 1000, 300, src=180), item("b", CUT, 300, src=before)])
    f.media_frames = 480 + after
    return f


class CallOn(Base):
    """Resolve 21.2 caps a scripted transition at the unused frames of the clip it isn't called on, and with none
    makes a left or right one full length with one side black (live 2026-11-27, docs/ISSUES.md I-39). So left is
    added at the outgoing clip's end, right at the incoming clip's start, and none on the side needed is refused."""

    def run_on(self, f, **args):
        self.use(f)
        sent: list[dict] = []
        real = f.transition

        def record(item_id, o):
            sent.append(dict(o, item_id=item_id))
            return real(item_id, o)
        f.transition = record
        return dispatch.run("add_transition", {"duration": 60, "confirm": True, "timeline": "T", **args}), sent

    def test_each_alignment_is_added_from_the_clip_whose_side_it_needs(self):
        cases = {("a", "end", "right"): ("b", "start"), ("b", "start", "right"): ("b", "start"),
                 ("b", "start", "left"): ("a", "end"), ("a", "end", "left"): ("a", "end"),
                 ("a", "end", "center"): ("a", "end"), ("b", "start", "center"): ("b", "start")}
        for (given, position, alignment), want in cases.items():
            with self.subTest(given=given, position=position, alignment=alignment):
                r, sent = self.run_on(clips(), item_id=given, position=position, alignment=alignment)
                self.assertEqual(r["_operation"]["status"], "success", r)
                self.assertEqual([(s["item_id"], s["position"]) for s in sent], [want])
                start, end = span(alignment, 60)
                self.assertEqual((r["start"], r["end"]), (session.to_tc(start), session.to_tc(end)))
                moved = [w for w in r["_operation"]["warnings"] if "I-39" in w]
                self.assertEqual(bool(moved), want[0] != given, r)

    def test_the_preview_names_the_clip_it_will_be_added_on(self):
        f = self.use(clips(before=0))
        r = dispatch.run("add_transition", {"item_id": "a", "alignment": "right", "duration": 60})
        self.assertEqual(r["_operation"]["status"], "preview", r)
        self.assertEqual((r["plan"]["position"], r["plan"]["span"]),
                         ("start", [session.to_tc(CUT), session.to_tc(CUT + 60)]))
        self.assertIn("incoming clip", " ".join(r["_operation"]["warnings"]))
        self.assertEqual([c for c in f.calls if c not in READ_OPS], [])

    def test_no_spare_frames_on_the_needed_side_is_refused_before_writing(self):
        for alignment, kw, side in (("right", {"after": 0}, "after the outgoing clip"),
                                    ("left", {"before": 0}, "before the incoming clip")):
            for confirm in (True, False):
                with self.subTest(alignment=alignment, confirm=confirm):
                    f = clips(**kw)
                    r, sent = self.run_on(f, item_id="a", alignment=alignment, confirm=confirm)
                    self.assertEqual(r["_operation"]["status"], "blocked", r)
                    self.assertIn(side, r["reason"])
                    self.assertIn("black", r["reason"])
                    self.assertEqual(sent, [])
                    self.assertNotIn("duplicate_timeline", f.calls)

    def test_no_spare_frames_on_the_other_side_is_fine(self):
        for alignment, kw in (("right", {"before": 0}), ("left", {"after": 0})):
            with self.subTest(alignment=alignment):
                r, _ = self.run_on(clips(**kw), item_id="a", alignment=alignment)
                self.assertEqual(r["_operation"]["status"], "success", r)

    def test_fewer_spare_frames_than_the_duration_say_it_will_be_shorter(self):
        self.use(clips(after=30))
        r = dispatch.run("add_transition", {"item_id": "a", "alignment": "right", "duration": 60})
        self.assertIn("shorten the transition to 30 frames", " ".join(r["_operation"]["warnings"]))

    def test_with_no_clip_on_the_other_side_the_given_clip_is_kept(self):
        f = FakeResolve([item("a", 1000, 300, src=180)])
        f.media_frames = 2275
        r, sent = self.run_on(f, item_id="a", alignment="right")
        self.assertEqual([(s["item_id"], s["position"]) for s in sent], [("a", "end")])
        self.assertEqual(r["_operation"]["status"], "success", r)

    def test_linked_audio_follows_the_clip_it_is_added_on(self):
        r, sent = self.run_on(linked(), item_id="a", alignment="right", duration=30)
        self.assertEqual(r["_operation"]["status"], "success", r)
        self.assertEqual([(s["item_id"], s["position"]) for s in sent], [("b", "start"), ("b2", "start")])
