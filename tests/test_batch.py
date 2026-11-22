"""Batches."""
from unittest import mock

from tests.support import Base, FakeResolve, SAMPLE_ARGS, item

from resolve_editor import dispatch, media, outcome


class Answers(FakeResolve):
    """FakeResolve with fixed answers for some ops, which then change nothing."""

    def __init__(self, answers):
        super().__init__([item("a", 1000, 10, src=5)])
        self.answers = answers

    def __call__(self, op, args, **kw):
        if op in self.answers:
            self.calls.append(op)
            return {"ok": True, "result": self.answers[op]}
        return super().__call__(op, args, **kw)


# For each tool that can return partial: bridge answers that make it do so.
PARTIALS = {
    "place_clips": {"append_clips": []},
    "move_item": {"copy_settings": {"copied": [], "failed": []}},
    "set_enabled": {"set_enabled": {"changed": 0}},
    "set_fades": {"set_fades": {"fades": {}}},
    "add_transition": {"add_transition": {"id": "t", "name": "X", "start": 1005, "duration": 3}},
    "set_audio": {},  # the fake doesn't change AudioVolume
    "add_markers": {"add_markers": {"added": 0}},
    "add_audio_markers": {"add_markers": {"added": 0}},
    "add_captions": {"add_title_cards": {"placed": [item("t", 1000, 1)]}},
}


class BatchPreview(Base):
    def test_batch_previews_without_writing(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        r = dispatch.run("batch", {"operations": [{"tool": "move_item", "args": {"item_id": "a", "record": 1050}}]})
        self.assertEqual(r["_operation"]["status"], "preview")
        self.assertNotIn("delete_items", f.calls)


class BatchStop(Base):
    """A batch goes on only after a step that succeeded (ISSUES.md I-03)."""

    NEXT = {"tool": "copy_grade", "args": SAMPLE_ARGS["copy_grade"]}

    def setUp(self):
        fake_media = lambda name, args: ({"silence_intervals": [{"start": 1, "end": 2}]} if name == "detect_silence"
                                         else {"duration": 5})
        patch = mock.patch.object(media, "run_media_tool", fake_media)
        patch.start()
        self.addCleanup(patch.stop)

    def batch(self, *ops):
        return dispatch.run("batch", {"confirm": True, "operations": list(ops)})

    def test_stops_after_each_tool_that_can_be_partial(self):
        for tool, answers in PARTIALS.items():
            with self.subTest(tool=tool):
                f = self.use(Answers(answers))
                args = dict(SAMPLE_ARGS[tool], **({"duration": 10} if tool == "add_transition" else {}))
                r = self.batch({"tool": tool, "args": args}, self.NEXT)
                self.assertEqual(r["results"][0]["status"], "partial")
                self.assertNotIn("copy_grade", f.calls)
                self.assertEqual(r["_operation"]["status"], "partial")

    def test_only_success_planned_and_reads_continue(self):
        for status, goes_on in (("success", True), ("planned", True), (None, True), ("partial", False),
                                ("preview", False), ("failed", False), ("blocked", False), ("something_new", False)):
            with self.subTest(status=status):
                f = self.use(Answers({}))
                result = {"count": 1} if status is None else outcome.op(status)  # a read has no _operation
                with mock.patch.dict(dispatch.HANDLERS, {"stub": lambda a: dict(result)}):
                    r = self.batch({"tool": "stub"}, self.NEXT)
                self.assertEqual("copy_grade" in f.calls, goes_on)
                self.assertEqual(r["_operation"]["status"], "success" if goes_on else "partial")

    def test_stop_says_why_and_what_was_not_run(self):
        self.use(Answers({}))
        r = self.batch({"tool": "add_markers", "args": SAMPLE_ARGS["add_markers"]},
                       {"tool": "set_audio", "args": SAMPLE_ARGS["set_audio"]}, self.NEXT)
        self.assertEqual([x["status"] for x in r["results"]], ["success", "partial"])
        self.assertEqual(r["not_run"], ["copy_grade"])
        self.assertIn("step 2 of 3 (set_audio: partial); 1 not run", r["reason"])
        self.assertIn("don't repeat the whole batch", r["reason"])
        self.assertEqual(r["results"][1]["changes"], {"items_changed": 0})
        self.assertIn("clamped", " ".join(r["results"][1]["warnings"]))
        self.assertTrue(r["snapshot"])

    def test_stop_at_last_step(self):
        self.use(Answers({}))
        r = self.batch({"tool": "set_audio", "args": SAMPLE_ARGS["set_audio"]})
        self.assertEqual(r["not_run"], [])
        self.assertIn("step 1 of 1 (set_audio: partial); 0 not run", r["reason"])

    def test_success_runs_every_step_once(self):
        f = self.use(Answers({}))
        r = self.batch({"tool": "add_markers", "args": SAMPLE_ARGS["add_markers"]}, {"tool": "timeline_summary"}, self.NEXT)
        self.assertEqual(r["_operation"]["status"], "success")
        self.assertEqual((f.calls.count("add_markers"), f.calls.count("copy_grade")), (1, 1))
        self.assertFalse(r.get("reason"))
        self.assertFalse(r.get("not_run"))
