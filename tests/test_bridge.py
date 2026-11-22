"""The bridge transport, reading side."""
import builtins
import io
import json
import os
import tempfile
import types
import unittest
from unittest import mock

from tests import support  # first: gives the tests a temporary bridge folder  # noqa: F401

from resolve_editor import bridge, paths

RID = "0123456789abcdef" * 2


def reply_export(value, file_name="bridge_token.png"):
    """A token-clip export as Resolve 21.2 writes it: UTF-16 with BOM, 18 columns, Comments is the 8th."""
    head = ["File Name", "Clip Directory", "Duration TC", "Start TC", "End TC", "Keywords", "Scene", "Comments"]
    row = [file_name, "C:\\bridge\\zażółć, folder", "00:00:00:01", "01:00:00:00", "01:00:00:01", "a:b", "", value]
    head += [f"Column {i}" for i in range(10)]
    row += [""] * 10
    return "".join(",".join(f'"{v}"' for v in line) + "\r\n" for line in (head, row)).encode("utf-16")


class GrowingFile(io.RawIOBase):
    """A file that is still being written: each part is what one read finds, b"" is end of file for now."""

    def __init__(self, parts):
        self.parts = list(parts)

    def readable(self):
        return True

    def readinto(self, buffer):
        part = self.parts.pop(0) if self.parts else b""
        if len(part) > len(buffer):
            self.parts.insert(0, part[len(buffer):])
            part = part[:len(buffer)]
        buffer[:len(part)] = part
        return len(part)


class BridgeReply(unittest.TestCase):
    """Reading reply.csv while Resolve writes it, and replies of any size (ISSUES.md I-13)."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.csv = os.path.join(folder.name, "reply.csv")
        for target, name, value in ((paths, "DIR", folder.name), (bridge, "REPLY_CSV", self.csv),
                                    (bridge, "PREFS", os.path.join(folder.name, "no.prefs")),
                                    (bridge, "ensure_token_png", lambda: None)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, data):
        with open(self.csv, "wb") as f:
            f.write(data)

    def half_written_on_first_open(self):
        """First open: empty, then the header, then no row yet. Later opens see the file on disk."""
        data = reply_export(f"{RID}:")
        header = data[:data.index("\r\n".encode("utf-16-le")) + 4]
        parts, real_open = [[b"", header, b""]], builtins.open

        def fake_open(file, *args, **kw):
            if file == self.csv and parts:
                return io.TextIOWrapper(io.BufferedReader(GrowingFile(parts.pop())), encoding="utf-16", newline="")
            return real_open(file, *args, **kw)
        return mock.patch.object(builtins, "open", fake_open)

    def call(self, on_poll):
        """call_bridge on a fake clock; on_poll(n) plays Resolve between polls."""
        now, polls = [0.0], [0]

        def sleep(_):
            now[0] += 0.5
            polls[0] += 1
            on_poll(polls[0])
        clock = types.SimpleNamespace(time=lambda: now[0], sleep=sleep)
        with (mock.patch.object(bridge, "time", clock),
              mock.patch.object(bridge.uuid, "uuid4", lambda: types.SimpleNamespace(hex=RID))):
            return bridge.call_bridge("get_state", {}, timeout=10, ack_timeout=5)

    def test_half_written_file_is_not_a_reply(self):
        with self.half_written_on_first_open():
            self.assertEqual(bridge._read_csv_reply(), (None, None))

    def test_large_replies_are_read(self):
        for size in (65_537, 200_000, 5_000_000):
            with self.subTest(payload_bytes=size):
                self.write(reply_export(f"{RID}:" + "7b" * size))
                got, payload = bridge.read_reply(RID)
                self.assertEqual((got, len(payload or "")), (RID, size * 2))

    def test_call_gets_large_reply_after_ack(self):
        answer = {"id": RID, "ok": True, "result": "x" * 200_000}
        done = reply_export(f"{RID}:" + json.dumps(answer).encode().hex())
        self.write(reply_export(f"{RID}:"))
        self.assertEqual(self.call(lambda n: self.write(done) if n == 2 else None), answer)

    def test_call_keeps_polling_past_half_written_file(self):
        answer = {"id": RID, "ok": True, "result": {"timeline": "T"}}
        self.write(reply_export(f"{RID}:" + json.dumps(answer).encode().hex()))
        with self.half_written_on_first_open():
            self.assertEqual(self.call(lambda n: None), answer)

    def test_no_truncation_gives_wrong_data(self):
        answer = {"id": RID, "ok": True, "result": [{"name": "zażółć", "start": 216000}] * 3}
        data = reply_export(f"{RID}:" + json.dumps(answer, ensure_ascii=False).encode().hex())
        for cut in range(len(data) + 1):
            self.write(data[:cut])
            got, payload = bridge._read_csv_reply()
            self.assertIn(got, (None, RID), cut)
            if payload:
                try:
                    decoded = json.loads(bytes.fromhex(payload).decode("utf-8"))
                except ValueError:
                    continue  # call_bridge polls again
                self.assertEqual(decoded, answer, cut)
        self.assertEqual(json.loads(bytes.fromhex(payload).decode("utf-8")), answer)  # type: ignore[arg-type]  # the loop ends on a full reply

    def test_other_columns_and_stale_replies(self):
        self.assertEqual(bridge.read_reply(RID), (None, None), "no file")
        self.write(reply_export("01:00:00:00 just a comment"))
        self.assertEqual(bridge.read_reply(), (None, None), "no reply in the file")
        self.write(reply_export(f"{RID}:7b7d", file_name="token deadbeef:cafe, 01:02.png"))
        self.assertEqual(bridge.read_reply(RID), (RID, "7b7d"))
        self.assertEqual(bridge.read_reply("f" * 32), (None, None), "someone else's reply")
