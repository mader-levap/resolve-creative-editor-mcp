"""The media tools on a real file, through FFmpeg. Skipped when FFmpeg isn't installed.

The clip: 3 s of black at 320x240, 30 fps; clicks at 0, 0.5, 1.0 and 1.5 s, then silence.
"""
import base64
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tests import support  # first: gives the tests a temporary bridge folder  # noqa: F401

from resolve_editor import media
from resolve_editor.tools import delivery, markers

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def state(path):
    """The file's bytes and modification time, to show it wasn't changed."""
    return pathlib.Path(path).read_bytes(), os.stat(path).st_mtime_ns


@unittest.skipUnless(FFMPEG, "FFmpeg isn't installed")
class OnARealFile(unittest.TestCase):
    folder: tempfile.TemporaryDirectory[str]
    path: str
    before: tuple[bytes, int]

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.folder.name, "clip.mp4")
        clicks = "aevalsrc='if(lt(t,1.6)*lt(mod(t,0.5),0.03),0.8*sin(2*PI*1000*t),0)':s=48000:d=3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=320x240:r=30:d=3",
                        "-f", "lavfi", "-i", clicks, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", cls.path], check=True, timeout=120)
        cls.before = state(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        out = tempfile.TemporaryDirectory()  # where derived files go (the bridge folder)
        self.addCleanup(out.cleanup)
        self.out = out.name
        patch = mock.patch("resolve_editor.paths.DIR", self.out)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.source_untouched)

    def source_untouched(self):
        self.assertEqual(state(self.path), self.before)
        self.assertEqual(os.listdir(self.folder.name), ["clip.mp4"], "nothing written next to the source")

    def tool(self, name, **args):
        return media.run_media_tool(name, {"path": self.path, **args})

    def test_probe(self):
        r = self.tool("probe_media")
        self.assertAlmostEqual(float(r["duration"]), 3, delta=0.05)
        video, sound = r["streams"]
        self.assertEqual((video["type"], video["width"], video["height"], video["frame_rate"]),
                         ("video", 320, 240, "30/1"))
        self.assertEqual((sound["type"], sound["sample_rate"]), ("audio", "48000"))

    def test_silence(self):
        r = self.tool("detect_silence", min_duration=0.5)
        self.assertEqual(len(r["silence_intervals"]), 1, r)
        gap = r["silence_intervals"][0]
        self.assertAlmostEqual(gap["start"], 1.53, delta=0.1)
        self.assertAlmostEqual(gap["end"], 3.0, delta=0.05)
        with self.assertRaisesRegex(ValueError, "noise_db"):
            self.tool("detect_silence", noise_db=5)

    def test_extract_audio_writes_a_wav_in_the_bridge_folder(self):
        r = self.tool("extract_audio", sample_rate=16000)
        self.assertEqual(os.path.dirname(r["audio_path"]), self.out)
        with open(r["audio_path"], "rb") as f:
            self.assertEqual(f.read(4), b"RIFF")
        self.assertEqual(self.tool("probe_media", path=r["audio_path"])["streams"][0]["sample_rate"], "16000")
        with self.assertRaisesRegex(ValueError, "sample_rate"):
            self.tool("extract_audio", sample_rate=22050)

    def test_contact_sheet_is_a_jpeg(self):
        r = self.tool("make_contact_sheet", interval_seconds=1, columns=2)
        self.assertEqual(os.path.dirname(r["path"]), self.out)
        self.assertEqual(base64.b64decode(r["image"])[:2], b"\xff\xd8", "JPEG start of image")

    def test_qc_finds_black_freeze_silence_and_loudness(self):
        r = delivery.qc_file({"path": self.path})
        qc = r["qc"]
        self.assertEqual(r["_operation"]["status"], "success")
        self.assertEqual(len(qc["black_segments"]), 1)
        self.assertAlmostEqual(qc["black_segments"][0][1] - qc["black_segments"][0][0], 3, delta=0.1)
        self.assertEqual(qc["frozen_at_seconds"], [0.0])
        self.assertAlmostEqual(qc["silence_at_seconds"][0], 1.53, delta=0.1)
        self.assertIsNotNone(qc["integrated_lufs"])
        self.assertIsNotNone(qc["true_peak_dbfs"])

    def test_beats_at_the_clicks(self):
        found = markers._beats(self.path)
        self.assertEqual(len(found), 3, found)  # the click at 0 has nothing before it to rise from
        for got, want in zip(found, (0.5, 1.0, 1.5), strict=True):
            self.assertAlmostEqual(got, want, delta=0.06)
