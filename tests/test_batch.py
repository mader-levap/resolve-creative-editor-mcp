"""Batches."""
from unittest import mock

from tests.support import SAMPLE_ARGS, Base, FakeResolve, item

from resolve_editor import audit, dispatch, media, outcome, timeline
from resolve_editor.tools.clips import FADES_NOT_SAVED


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
        def fake_media(name, args):
            return ({"silence_intervals": [{"start": 1, "end": 2}]} if name == "detect_silence"
                    else {"duration": 5})
        patch = mock.patch.object(media, "run_media_tool", fake_media)
        patch.start()
        self.addCleanup(patch.stop)

    def batch(self, *ops):
        return dispatch.run("batch", {"confirm": True, "timeline": "T", "operations": list(ops)})

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
                with mock.patch.dict(dispatch.HANDLERS, {"stub": lambda a, result=result: dict(result)}):
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
        r = self.batch({"tool": "add_markers", "args": SAMPLE_ARGS["add_markers"]}, {"tool": "timeline_summary"},
                       self.NEXT)
        self.assertEqual(r["_operation"]["status"], "success")
        self.assertEqual((f.calls.count("add_markers"), f.calls.count("copy_grade")), (1, 1))
        self.assertFalse(r.get("reason"))
        self.assertFalse(r.get("not_run"))


class BatchError(Base):
    """An error inside a step stops the batch like a failed step, and nothing is lost (ISSUES.md I-02)."""

    def setUp(self):
        self.audited: list[tuple[str, str]] = []
        patch = mock.patch.object(audit, "log_audit", lambda tool, args, status: self.audited.append((tool, status)))
        patch.start()
        self.addCleanup(patch.stop)

    def batch(self, *ops):
        return dispatch.run("batch", {"confirm": True, "timeline": "T", "operations": list(ops)})

    STEPS = ({"tool": "add_markers", "args": SAMPLE_ARGS["add_markers"]},
             {"tool": "add_transition", "args": SAMPLE_ARGS["add_transition"]},
             {"tool": "copy_grade", "args": SAMPLE_ARGS["copy_grade"]})

    def test_refusal_at_step_2_of_3_keeps_results_and_backup(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)], fail_on={"add_transition": 1}))
        r = self.batch(*self.STEPS)
        self.assertEqual([x["status"] for x in r["results"]], ["success", "failed"])
        self.assertIn("add_transition failed", r["results"][1]["reason"])
        self.assertIn("read it back", " ".join(r["results"][1]["warnings"]))
        self.assertEqual(r["not_run"], ["copy_grade"])
        self.assertNotIn("copy_grade", f.calls)
        self.assertIn(r["snapshot"], f.timelines)
        self.assertIn("step 2 of 3 (add_transition: failed); 1 not run", r["reason"])
        self.assertEqual(r["_operation"]["status"], "partial")

    def test_failed_batch_is_audited(self):
        self.use(FakeResolve([item("a", 1000, 10, src=5)], fail_on={"add_transition": 1}))
        self.batch(*self.STEPS)
        self.assertEqual([x for x in self.audited if x[0] != "edit__snapshot_timeline"],
                         [("edit__add_markers", "success"), ("edit__add_transition", "error"),
                          ("edit__batch", "partial")])

    def test_any_exception_in_a_step_is_caught(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))

        def boom(a):
            raise ValueError("bad value")
        with mock.patch.dict(dispatch.HANDLERS, {"stub": boom}):
            r = self.batch({"tool": "stub"}, self.STEPS[2])
        self.assertEqual(r["results"][0]["status"], "failed")
        self.assertIn("ValueError: bad value", r["results"][0]["reason"])
        self.assertNotIn("copy_grade", f.calls)
        self.assertEqual(r["not_run"], ["copy_grade"])

    def test_backup_error_runs_no_step(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)], fail_on={"duplicate_timeline": 1}))
        r = self.batch(*self.STEPS)
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertIn("duplicate_timeline failed", r["reason"])
        self.assertEqual(r["not_run"], ["add_markers", "add_transition", "copy_grade"])
        self.assertFalse({"add_markers", "add_transition", "copy_grade"} & set(f.calls))
        self.assertIn(("edit__batch", "failed"), self.audited)

    def test_backup_not_made_runs_no_step(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        with mock.patch.object(timeline, "snapshot_timeline", lambda a: outcome.blocked("no current timeline")):
            r = self.batch(*self.STEPS)
        self.assertEqual(r["_operation"]["status"], "failed")
        self.assertIn("no current timeline", r["reason"])
        self.assertEqual(r["not_run"], ["add_markers", "add_transition", "copy_grade"])
        self.assertFalse({"add_markers", "add_transition", "copy_grade"} & set(f.calls))

    def test_single_write_that_raises_is_audited_and_still_raises(self):
        self.use(FakeResolve([item("a", 1000, 10, src=5)], fail_on={"add_transition": 1}))
        with self.assertRaises(RuntimeError):
            dispatch.run("add_transition", dict(SAMPLE_ARGS["add_transition"], confirm=True, timeline="T"))
        self.assertEqual(self.audited, [("edit__add_transition", "error")])

    def test_preview_that_raises_is_not_audited(self):
        self.use(FakeResolve([item("a", 1000, 10, src=5)], fail_on={"item_details": 9}))
        with self.assertRaises(RuntimeError):
            dispatch.run("move_item", SAMPLE_ARGS["move_item"])
        self.assertEqual(self.audited, [])


class BatchReport(Base):
    """A batch keeps every step's warnings (ISSUES.md I-20) and is only passed when every write was (I-18)."""

    def batch(self, *ops):
        self.use(FakeResolve([item("a", 1000, 10, src=5), item("b", 1100, 10, src=5)]))
        return dispatch.run("batch", {"confirm": True, "timeline": "T", "operations": [
            {"tool": t, "args": SAMPLE_ARGS[t] if a is None else a} for t, a in ops]})

    def verdict(self, r):
        return r["_operation"]["status"], r["_operation"]["verification"]

    def test_successful_steps_keep_their_warnings(self):
        r = self.batch(("set_fades", None), ("add_markers", None))
        self.assertIn(FADES_NOT_SAVED, r["results"][0]["warnings"])
        self.assertIn(FADES_NOT_SAVED, " ".join(r["_operation"]["warnings"]))
        self.assertIn("step 1 (set_fades)", " ".join(r["_operation"]["warnings"]))
        self.assertNotIn("warnings", r["results"][1])  # none to show

    def test_identical_warnings_are_listed_once_with_their_steps(self):
        r = self.batch(("move_item", {"item_id": "a", "record": 1050}), ("move_item", {"item_id": "b", "record": 1200}))
        keyframes = [w for w in r["_operation"]["warnings"] if "keyframes are not copied" in w]
        self.assertEqual(len(keyframes), 1, r["_operation"]["warnings"])
        self.assertIn("steps 1, 2 (move_item)", keyframes[0])

    def test_verification_follows_the_writes(self):
        for ops, expected in (([("copy_grade", None)], ("success", "unverified")),
                              ([("copy_grade", None), ("add_markers", None)], ("success", "unverified")),
                              ([("add_markers", None), ("timeline_summary", {})], ("success", "passed"))):
            with self.subTest(ops=[t for t, _ in ops]):
                r = self.batch(*ops)
                self.assertEqual(self.verdict(r), expected, r)
                if "copy_grade" in [t for t, _ in ops]:
                    self.assertEqual(r["results"][0]["verification"], "unverified")

    def test_a_stop_is_still_a_contradiction_with_the_steps_changes(self):
        r = self.batch(("copy_grade", None), ("add_markers", {"markers": [{"at": 1001}]}), ("set_fades", None))
        self.assertEqual(self.verdict(r), ("partial", "contradiction"))
        self.assertEqual(r["results"][1]["status"], "blocked")
        self.assertIn("changes", r["results"][1])
        self.assertIn("grades can't be read back", " ".join(r["_operation"]["warnings"]))
