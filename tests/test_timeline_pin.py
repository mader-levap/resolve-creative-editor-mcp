"""The timeline pin."""
import os
import tempfile
from unittest import mock

from tests.support import READ_OPS, SAMPLE_ARGS, Base, FakeResolve, item

from resolve_editor import dispatch, media, session


class TimelineFake(FakeResolve):
    """Resolve with several timelines. click(fake, op, n) runs before call n, like the user or Resolve switching.
    Honours a request's pin the way resolve_bridge.lua does (tested on the real Lua in tests/smoke_bridge.py)."""

    def __init__(self, click=None, **kw):
        super().__init__([item("a", 1000, 10, src=5)], **kw)
        self.cur, self.click, self.landed, self.backup_of = "T", click, [], {}
        self.refuse_switch, self.unreachable, self.pins = 0, False, True
        self.timelines.append("OTHER")

    def __call__(self, op, args, timeline=None, **kw):
        if self.click:
            self.click(self, op, len(self.calls))
        switched = None
        if timeline and self.cur != timeline["name"]:
            if self.unreachable:
                self.calls.append(op)
                return {"ok": False, "error": "timeline not found; op not run"}
            switched, self.cur = self.cur, timeline["name"]
        if op == "set_current_timeline" and self.refuse_switch:
            self.refuse_switch -= 1
            self.calls.append(op)
            return {"ok": False, "error": "Resolve did not stay on the timeline"}
        if op not in ("get_state", "set_current_timeline", "list_timelines"):
            self.landed.append((op, self.cur))
        r = super().__call__(op, args, **kw)
        if op == "get_state":
            r["result"].update(timeline=self.cur, pins=self.pins)
        elif op == "duplicate_timeline" and r["ok"]:
            self.backup_of[args["name"]], self.cur = self.cur, args["name"]
        elif op == "set_current_timeline" and r["ok"]:
            self.cur = args["name"]
        return dict(r, switched_from=switched) if switched else r

    def astray(self):
        return [(op, at) for op, at in self.landed if at != "T"]

    def writes(self):
        return [(op, at) for op, at in self.landed if op not in READ_OPS]


class TimelinePin(Base):
    """A writing call stays on the timeline it started on, whoever switches meanwhile (ISSUES.md I-16)."""

    PLACE = {"tool": "place_clips", "args": SAMPLE_ARGS["place_clips"]}
    MARK = {"tool": "add_markers", "args": SAMPLE_ARGS["add_markers"]}

    def setUp(self):
        def fake_media(name, args):
            return ({"silence_intervals": [{"start": 1, "end": 2}]} if name == "detect_silence"
                    else {"duration": 5})
        patch = mock.patch.object(media, "run_media_tool", fake_media)
        patch.start()
        self.addCleanup(patch.stop)

    def batch(self, fake):
        self.use(fake)
        return dispatch.run("batch", {"confirm": True, "operations": [self.PLACE, self.MARK]})

    @staticmethod
    def once(when, to="OTHER"):
        done: list[int] = []

        def click(fake, op, n):
            if not done and when(fake, op, n):
                done.append(1)
                fake.cur = to(fake) if callable(to) else to
        return click

    def test_switch_back_to_backup_after_it_was_checked(self):
        f = TimelineFake(self.once(lambda f, op, n: op == "append_clips", lambda f: next(iter(f.backup_of))))
        r = self.batch(f)
        self.assertEqual((f.astray(), f.cur), ([], "T"))
        self.assertIn("switched", " ".join(r["_operation"]["warnings"]))

    def test_user_switch_between_batch_steps(self):
        f = TimelineFake(self.once(lambda f, op, n: op == "add_markers"))
        r = self.batch(f)
        self.assertEqual((f.astray(), f.cur), ([], "T"))
        self.assertIn("OTHER", " ".join(r["_operation"]["warnings"]))

    def test_switch_just_before_call_is_not_hidden_by_cache(self):
        for tool in ("batch", "snapshot_timeline"):
            with self.subTest(tool=tool):
                f = self.use(TimelineFake())
                dispatch.run("timeline_summary", {})
                f.cur = "OTHER"  # the user switched less than 3 s after that read
                f.landed.clear()
                dispatch.run(tool, {"confirm": True, "operations": [self.PLACE]} if tool == "batch" else {})
                self.assertEqual(list(f.backup_of.values()), ["OTHER"])
                self.assertTrue(next(iter(f.backup_of)).startswith("OTHER "), "the backup is named after its source")
                self.assertEqual({at for _, at in f.writes()}, {"OTHER"})
                self.assertEqual(f.cur, "OTHER")

    def test_failed_switch_back_does_not_leave_user_on_backup(self):
        f = self.use(TimelineFake())
        f.refuse_switch = 1
        with self.assertRaises(RuntimeError):
            dispatch.run("snapshot_timeline", {})
        self.assertEqual(f.cur, "T")

    def test_move_rollback_stays_on_timeline(self):
        class SwapFails(TimelineFake):
            appends = 0

            def __call__(self, op, args, **kw):  # type: ignore[override]  # timeline= goes through **kw
                if op == "append_clips":
                    self.appends += 1
                    if self.appends == 2:
                        self.cur = "OTHER"
                        self.fail_on[op] = 1
                return super().__call__(op, args, **kw)

        f = self.use(SwapFails())
        r = dispatch.run("move_item", {"item_id": "a", "record": 1100, "confirm": True, "backup": False})
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertEqual((f.astray(), f.cur), ([], "T"))

    def test_switch_before_any_call_of_any_writing_tool(self):
        for tool in sorted(set(dispatch.HANDLERS) - dispatch.READ_ONLY - {"export_srt"}):
            args = dict(SAMPLE_ARGS[tool], confirm=True)
            if tool == "batch":
                args["operations"] = [self.PLACE, self.MARK]
            clean = self.use(TimelineFake())
            dispatch.run(tool, dict(args))
            for at in range(1, len(clean.calls)):  # a switch before call 0 is simply the timeline to edit
                with self.subTest(tool=tool, before_call=at, op=clean.calls[at]):
                    f = self.use(TimelineFake(self.once(lambda f, op, n, at=at: n == at)))
                    dispatch.run(tool, dict(args))
                    self.assertEqual((f.astray(), f.cur), ([], "T"))

    def test_unreachable_timeline_gets_no_write(self):
        def vanish(fake, op, n):
            if op == "append_clips":
                fake.cur, fake.unreachable = "OTHER", True

        f = self.use(TimelineFake(vanish))
        try:
            dispatch.run("place_clips", dict(SAMPLE_ARGS["place_clips"], confirm=True))
        except RuntimeError:
            pass
        self.assertEqual(f.writes(), [])
        self.assertIsNone(session.pin)

    def test_bridge_without_pins_is_refused(self):
        f = self.use(TimelineFake())
        f.pins = False
        r = dispatch.run("add_markers", SAMPLE_ARGS["add_markers"])
        self.assertEqual((r["_operation"]["status"], f.writes()), ("blocked", []))
        self.assertIn("bridge", r["reason"])

    def test_pin_is_cleared(self):
        self.use(TimelineFake())
        dispatch.run("add_markers", SAMPLE_ARGS["add_markers"])
        self.assertIsNone(session.pin)
        self.use(TimelineFake(fail_on={"add_markers": 1}))
        with self.assertRaises(RuntimeError):
            dispatch.run("add_markers", SAMPLE_ARGS["add_markers"])
        self.assertIsNone(session.pin)

    def test_previews_and_reads_never_switch(self):
        calls = [(t, SAMPLE_ARGS[t]) for t in sorted(dispatch.PREVIEWABLE)]
        calls += [("timeline_summary", {}), ("inspect_range", SAMPLE_ARGS["inspect_range"]),
                  ("batch", {"operations": [self.PLACE, self.MARK]}),
                  ("add_captions", dict(SAMPLE_ARGS["add_captions"], dry_run=True, confirm=True))]
        for tool, args in calls:
            with self.subTest(tool=tool):
                f = self.use(TimelineFake(self.once(lambda f, op, n: n == 1)))
                dispatch.run(tool, dict(args))
                if len(f.calls) > 1:
                    self.assertEqual(f.cur, "OTHER")
                self.assertNotIn("set_current_timeline", f.calls)

    def test_file_only_calls_need_no_resolve(self):
        def no_bridge(*args, **kw):
            raise AssertionError("Resolve was called")

        self.use(no_bridge)
        self.assertEqual(dispatch.run("add_audio_markers", dict(SAMPLE_ARGS["add_audio_markers"], dry_run=True))
                         ["_operation"]["status"], "planned")
        with tempfile.TemporaryDirectory() as folder:
            r = dispatch.run("export_srt", dict(SAMPLE_ARGS["export_srt"], output=os.path.join(folder, "a.srt")))
            self.assertEqual(r["_operation"]["status"], "success")
