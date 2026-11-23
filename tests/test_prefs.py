"""Standard Generator Duration from Resolve's saved preferences (ISSUES.md I-24)."""
import os
import tempfile
from unittest import mock

from tests.support import Base, FakeResolve

from resolve_editor import dispatch, prefs
from resolve_editor.tools import diagnostics

XML = """<?xml version="1.0" encoding="UTF-8"?>
<SyncedUserPreferences>
 <StandardTransitionDuration>0.5</StandardTransitionDuration>
 <GeneratorDurationType>{kind}</GeneratorDurationType>
 <GeneratorDurationSecs>15</GeneratorDurationSecs>
 <GeneratorDurationFrames>125</GeneratorDurationFrames>
 <StillDurationSecs>5</StillDurationSecs>
</SyncedUserPreferences>
"""


class Prefs(Base):
    def write(self, text):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = os.path.join(folder.name, "config.user.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        patch = mock.patch.object(prefs, "USER_PREFS", path)
        patch.start()
        self.addCleanup(patch.stop)

    def test_seconds_and_frames(self):
        self.write(XML.format(kind="DURATION_IN_SECONDS"))
        self.assertEqual(prefs.generator_duration(), {"seconds": 15.0})
        self.assertEqual(prefs.generator_frames(30), 450)
        self.write(XML.format(kind="DURATION_IN_FRAMES"))
        self.assertEqual(prefs.generator_duration(), {"frames": 125})
        self.assertEqual(prefs.generator_frames(60), 125)

    def test_missing_file_or_entries_give_none(self):
        self.assertIsNone(prefs.generator_duration())  # tests point at a file that doesn't exist
        self.write("<SyncedUserPreferences><StillDurationSecs>5</StillDurationSecs></SyncedUserPreferences>")
        self.assertIsNone(prefs.generator_duration())
        self.write("not xml <")
        self.assertIsNone(prefs.generator_duration())
        self.assertIsNone(prefs.generator_frames(30))

    def test_doctor_reports_it(self):
        self.write(XML.format(kind="DURATION_IN_SECONDS"))
        with mock.patch("resolve_editor.bridge.call_bridge", return_value={"ok": True, "result": {}}):
            r = diagnostics.doctor({})
        self.assertIn("15 s", r["standard_generator_duration"])
        self.assertIn("saved preferences", r["standard_generator_duration"])

    def test_caption_preview_names_the_captions_placed_in_parts(self):
        self.write(XML.format(kind="DURATION_IN_SECONDS"))
        self.use(FakeResolve([]))  # 30 fps timeline: 15 s is 450 frames
        segs = [{"start": 0, "end": 2, "text": "short"}, {"start": 3, "end": 43, "text": "forty seconds"}]
        r = dispatch.run("add_captions", {"segments": segs})
        note = [w for w in r["_operation"]["warnings"] if "15 s" in w]
        self.assertEqual(len(note), 1, r["_operation"]["warnings"])
        self.assertIn("450 frames", note[0])
        self.assertIn("1 caption", note[0])
        self.assertIn("3 parts", note[0])

    def test_caption_preview_without_the_preference_is_unchanged(self):
        self.use(FakeResolve([]))
        r = dispatch.run("add_captions", {"segments": [{"start": 0, "end": 40, "text": "x"}]})
        self.assertFalse([w for w in r["_operation"]["warnings"] if "frames)" in w], r["_operation"]["warnings"])
