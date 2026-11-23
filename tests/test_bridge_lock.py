"""Several processes sharing one bridge (ISSUES.md I-15)."""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.support import ROOT
from tests.test_bridge import reply_export

from resolve_editor import bridge, paths

# A client process: the real call_bridge on the test's folder, never the user's (the env is set before the import).
PRELUDE = """import json, os, sys
os.environ["RESOLVE_BRIDGE_DIR"], os.environ["RESOLVE_FUSION_PREFS"] = sys.argv[1], sys.argv[2]
sys.path.insert(0, sys.argv[3])
from resolve_editor import bridge
"""
CLIENT = PRELUDE + """
name, n, out = sys.argv[4], int(sys.argv[5]), {"ok": 0, "errors": []}
for i in range(n):
    try:
        r = bridge.call_bridge("echo", {"client": name, "n": i}, timeout=20, ack_timeout=5)
        if r.get("result") == {"client": name, "n": i}:
            out["ok"] += 1
        else:
            out["errors"].append(f"call {i} got {r}")
    except Exception as exc:
        out["errors"].append(f"call {i}: {type(exc).__name__}: {exc}")
print(json.dumps(out))
"""
HOLDER = PRELUDE + """
with bridge._bridge_lock(5):
    print("held", flush=True)
    sys.stdin.read() if sys.argv[4] == "stdin" else __import__("time").sleep(float(sys.argv[4]))
"""
LOOPER = PRELUDE + """
import time
end, n = time.time() + float(sys.argv[4]), 0
while time.time() < end:  # back to back, like a long batch
    bridge.call_bridge("echo", {"loop": n}, timeout=20, ack_timeout=5)
    n += 1
print(n)
"""
REQUEST_RE = re.compile(r"local s = \[(=*)\[(.*?)\]\1\]", re.S)


class FakeBridge(threading.Thread):
    """Like the main loop in resolve_bridge.lua: reads request.lua, answers each new id once (ack, then the reply
    in reply.csv), deletes nothing. The delays widen the windows in which clients can collide."""

    def __init__(self, folder, delay=0.02):
        super().__init__(daemon=True)
        self.folder, self.delay, self.stop, self.seen = folder, delay, threading.Event(), []

    def reply(self, value):
        for _ in range(100):  # a client may be reading it
            try:
                with open(os.path.join(self.folder, "reply.csv"), "wb") as f:
                    f.write(reply_export(value))
                return
            except PermissionError:
                time.sleep(0.01)

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
            self.seen.append(req)
            time.sleep(self.delay)
            self.reply(f"{req['id']}:")
            time.sleep(self.delay)
            answer = {"id": req["id"], "ok": True, "result": req["args"]}
            self.reply(f"{req['id']}:" + json.dumps(answer).encode().hex())


class BridgeLock(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir, self.prefs = folder.name, os.path.join(folder.name, "no.prefs")
        csv = os.path.join(self.dir, "reply.csv")
        for target, name, value in ((paths, "DIR", self.dir), (bridge, "REPLY_CSV", csv),
                                    (bridge, "PREFS", self.prefs)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def fake_bridge(self):
        fake = FakeBridge(self.dir)
        fake.start()
        self.addCleanup(fake.join)
        self.addCleanup(fake.stop.set)
        return fake

    def child(self, script, *args, **kw):
        return subprocess.Popen([sys.executable, "-c", script, self.dir, self.prefs, str(ROOT), *args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)

    def hold_lock(self, how):
        p = self.child(HOLDER, how, stdin=subprocess.PIPE)
        self.addCleanup(p.wait, 10)
        self.assertEqual(p.stdout.readline().strip(), "held", p.stderr.read() if p.poll() is not None else "")
        return p

    def test_two_processes_lose_nothing(self):
        fake, n = self.fake_bridge(), 20
        clients = [self.child(CLIENT, name, str(n)) for name in ("A", "B")]
        for p in clients:
            out, err = p.communicate(timeout=120)
            self.assertEqual(p.returncode, 0, err)
            result = json.loads(out)
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["ok"], n)
        ids = [r["id"] for r in fake.seen]
        self.assertEqual(len(ids), 2 * n, "every request ran")
        self.assertEqual(len(set(ids)), len(ids), "none ran twice")

    def test_waiter_that_gives_up_sends_nothing(self):
        fake = self.fake_bridge()
        holder = self.hold_lock("stdin")
        with self.assertRaises(bridge.BridgeBusy) as caught:
            bridge.call_bridge("echo", {}, timeout=5, ack_timeout=2, lock_timeout=0.5)
        self.assertIn("nothing was sent", str(caught.exception))
        self.assertNotIn("not running", str(caught.exception))
        holder.stdin.close()
        time.sleep(0.2)
        self.assertEqual(fake.seen, [])
        self.assertEqual([f for f in os.listdir(self.dir) if f.startswith("request")], [])

    def test_waiter_runs_once_the_lock_is_free(self):
        fake = self.fake_bridge()
        before = time.time()
        self.hold_lock("1.5")
        r = bridge.call_bridge("echo", {"x": 1}, timeout=10, ack_timeout=5, lock_timeout=10)
        self.assertEqual(r["result"], {"x": 1})
        self.assertGreaterEqual(fake.seen[0]["ts"], int(before) + 1, "ts is taken after the wait")  # bridge drops old

    def test_a_client_calling_back_to_back_lets_a_waiter_in(self):
        fake = self.fake_bridge()
        looper = self.child(LOOPER, "60")
        self.addCleanup(looper.communicate, timeout=60)
        self.addCleanup(looper.kill)
        deadline = time.time() + 20
        while len(fake.seen) < 3 and time.time() < deadline:  # the looper is running
            time.sleep(0.05)
        for i in range(5):  # a waiter can slip in by chance; five in a row can't
            r = bridge.call_bridge("echo", {"waiter": i}, timeout=10, ack_timeout=5, lock_timeout=2)
            self.assertEqual(r["result"], {"waiter": i})
        self.assertIsNone(looper.poll(), "the looper was still calling")
        looped = len(fake.seen)
        time.sleep(1)
        self.assertGreater(len(fake.seen), looped, "and the looper isn't starved in turn")

    def test_lock_is_released_after_an_error(self):
        with self.assertRaises(ConnectionError):  # no bridge: no ack
            bridge.call_bridge("echo", {}, timeout=1, ack_timeout=0.2, lock_timeout=1)
        with bridge._bridge_lock(0):
            pass
        self.assertEqual([f for f in os.listdir(self.dir) if f.startswith("request")], [])


if __name__ == "__main__":
    unittest.main()
