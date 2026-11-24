"""Timeline export, the audit log and the doctor."""
import json
import os
import tempfile
from unittest import mock

from tests.support import Base, FakeResolve, sample_items

from resolve_editor import audit, bridge, dispatch


class Writes(FakeResolve):
    """export_timeline writes the file, as Resolve does; written=False: Resolve says ok but writes nothing."""

    written = True

    def __call__(self, op, args, **kw):
        if op == "export_timeline" and self.written:
            with open(args["path"], "w", encoding="utf-8") as f:
                f.write("{}")
        return super().__call__(op, args, **kw)


class ExportTimeline(Base):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name

    def test_the_file_is_written_where_asked(self):
        out = os.path.join(self.folder, "cut.otio")
        self.use(Writes(sample_items()))
        r = dispatch.run("export_timeline", {"format": "OTIO", "output": out})
        self.assertEqual((r["_operation"]["status"], r["_operation"]["changes"]["file_written"]), ("success", out))

    def test_ok_without_a_file_is_a_failure(self):
        f = self.use(Writes(sample_items()))
        f.written = False
        r = dispatch.run("export_timeline", {"format": "EDL", "output": os.path.join(self.folder, "cut.edl")})
        self.assertEqual(r["_operation"]["status"], "failed")

    def test_an_existing_file_is_not_overwritten(self):
        out = os.path.join(self.folder, "cut.otio")
        with open(out, "w", encoding="utf-8") as f:
            f.write("mine")
        fake = self.use(Writes(sample_items()))
        with self.assertRaisesRegex(FileExistsError, "overwrite"):
            dispatch.run("export_timeline", {"format": "OTIO", "output": out})
        self.assertNotIn("export_timeline", fake.calls)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.read(), "mine")


class AuditLog(Base):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patch = mock.patch.object(audit, "AUDIT", os.path.join(folder.name, "audit.jsonl"))
        patch.start()
        self.addCleanup(patch.stop)

    def test_no_log_yet_is_an_empty_list(self):
        self.assertEqual(dispatch.run("audit_log", {}), {"entries": []})

    def test_writes_are_logged_and_the_last_ones_returned(self):
        self.use(FakeResolve(sample_items()))
        for n in range(3):
            dispatch.run("set_enabled", {"item_ids": ["a"], "enabled": bool(n % 2)})
        dispatch.run("timeline_summary", {})  # a read: not logged
        rows = dispatch.run("audit_log", {"limit": 2})["entries"]
        self.assertEqual([(e["tool"], e["args"]["enabled"]) for e in rows],
                         [("edit__set_enabled", True), ("edit__set_enabled", False)])
        self.assertEqual(len(dispatch.run("audit_log", {})["entries"]), 3)


class Doctor(Base):
    def test_a_running_bridge_reports_resolve(self):
        self.use(FakeResolve(sample_items()))
        r = dispatch.run("doctor", {})
        self.assertEqual((r["bridge"], r["resolve"]["timeline"]), ("connected", "T"))
        self.assertNotIn("previous_run_stuck", r)

    def test_a_busy_bridge_is_running_not_broken(self):
        def busy(op, args, **kw):
            raise bridge.BridgeBusy("held")
        self.use(busy)
        self.assertIn("busy", dispatch.run("doctor", {})["bridge"])

    def test_a_silent_bridge_says_so(self):
        def silent(op, args, **kw):
            raise TimeoutError("no ack")
        self.use(silent)
        self.assertEqual(dispatch.run("doctor", {})["bridge"], "not answering (TimeoutError): no ack")

    def test_where_the_previous_bridge_stopped_is_reported(self):
        stuck = {"op": "add_title_cards", "phase": "op", "at": 1}
        def answers(op, args, **kw):
            return {"ok": True, "result": {"timeline": "T", "previous_run_stuck": stuck}}
        self.use(answers)
        self.assertEqual(json.dumps(dispatch.run("doctor", {})["previous_run_stuck"]), json.dumps(stuck))
