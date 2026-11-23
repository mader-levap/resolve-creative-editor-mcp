"""A bridge that acks a request and then stops answering (ISSUES.md I-22)."""
import json
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.test_bridge_lock import REQUEST_RE, FakeBridge

from resolve_editor import bridge, paths
from resolve_editor.tools import diagnostics


class StuckBridge(FakeBridge):
    """Like the Lua loop stuck inside a Resolve call: it acks op "hang", then reads nothing until released (the
    user restarting it), and answers normally after that."""

    def __init__(self, folder):
        super().__init__(folder, delay=0)
        self.release = threading.Event()

    def run(self):
        last = None
        while not self.stop.is_set():
            try:
                with open(os.path.join(self.folder, "request.lua"), encoding="utf-8") as f:
                    m = REQUEST_RE.search(f.read())
                req = json.loads(m.group(2)) if m else None
            except (OSError, ValueError):
                req = None
            if not req or req["id"] == last:
                time.sleep(0.01)
                continue
            last = req["id"]
            self.reply(f"{req['id']}:")  # ack
            if req["op"] == "hang":
                while not (self.release.is_set() or self.stop.is_set()):
                    time.sleep(0.01)
                continue  # the stuck call never answers
            answer = {"id": req["id"], "ok": True, "result": req["args"]}
            self.reply(f"{req['id']}:" + json.dumps(answer).encode().hex())


class Folder(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = folder.name
        for target, name, value in ((paths, "DIR", self.dir),
                                    (bridge, "REPLY_CSV", os.path.join(self.dir, "reply.csv")),
                                    (bridge, "PREFS", os.path.join(self.dir, "no.prefs"))):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def hang_file(self):
        return os.path.join(self.dir, "bridge_hang.json")


class BridgeHang(Folder):
    def setUp(self):
        super().setUp()
        self.fake = StuckBridge(self.dir)
        self.fake.start()
        self.addCleanup(self.fake.join)
        self.addCleanup(self.fake.stop.set)

    def test_a_stuck_bridge_is_named_until_it_answers_again(self):
        with self.assertRaises(TimeoutError) as caught:
            bridge.call_bridge("hang", {}, timeout=1, ack_timeout=0.5)
        text = str(caught.exception)
        for part in ("hang", "stopped answering", "may have been made", "restart", "edit__doctor"):
            self.assertIn(part, text)
        with open(self.hang_file(), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["op"], "hang")

        with self.assertRaises(ConnectionError) as no_ack:  # still stuck: no ack
            bridge.call_bridge("echo", {"n": 1}, timeout=1, ack_timeout=0.5)
        text = str(no_ack.exception)
        self.assertIn("stuck", text)
        self.assertIn("hang", text)
        self.assertNotIn("Bridge not running", text)

        self.fake.release.set()  # the user restarted it
        self.assertEqual(bridge.call_bridge("echo", {"n": 2}, timeout=5, ack_timeout=2)["result"], {"n": 2})
        self.assertFalse(os.path.exists(self.hang_file()))

    def test_without_a_hang_no_ack_is_the_usual_not_running(self):
        self.fake.stop.set()
        self.fake.join()
        with self.assertRaises(ConnectionError) as caught:
            bridge.call_bridge("echo", {}, timeout=1, ack_timeout=0.3)
        self.assertIn("Bridge not running", str(caught.exception))


class DoctorAfterHang(Folder):
    def test_doctor_reports_the_hang_and_the_bridges_own_record(self):
        with open(self.hang_file(), "w", encoding="utf-8") as f:
            json.dump({"op": "get_state", "at": "2026-11-22 20:11:58"}, f)
        with mock.patch.object(bridge, "call_bridge", side_effect=ConnectionError("still stuck since get_state")):
            r = diagnostics.doctor({})
        self.assertEqual(r["bridge_hang"]["op"], "get_state")
        self.assertIn("still stuck", r["bridge"])
        stuck = {"op": "get_state", "phase": "reply", "at": 1795900318}
        with mock.patch.object(bridge, "call_bridge",
                               return_value={"ok": True, "result": {"previous_run_stuck": stuck}}):
            r = diagnostics.doctor({})
        self.assertEqual(r["bridge"], "connected")
        self.assertEqual(r["previous_run_stuck"], stuck)


if __name__ == "__main__":
    unittest.main()
