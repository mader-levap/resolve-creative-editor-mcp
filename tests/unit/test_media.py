"""Media tools: every tool in the schema has a handler, calls reach it, and both servers offer it."""
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from tests import support  # first: gives the tests a temporary bridge folder  # noqa: F401

from resolve_editor import media
from resolve_editor.schemas import media as media_schema
from resolve_editor.servers import gateway, legacy

NAMES = {t["name"] for t in media_schema.TOOLS}


class MediaTools(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "a.mp4")
        open(self.path, "wb").close()

    def test_every_tool_in_the_schema_has_a_handler(self):
        self.assertEqual(set(media.HANDLERS), NAMES)

    def test_a_call_reaches_its_tool_with_the_resolved_path(self):
        for name in sorted(NAMES):
            with self.subTest(tool=name):
                stub = mock.Mock(return_value={"tool": name})
                args = {"path": self.path, "extra": 1}
                with mock.patch.dict(media.HANDLERS, {name: stub}):
                    self.assertEqual(media.run_media_tool(name, args), {"tool": name})
                stub.assert_called_once_with(os.path.abspath(self.path), args)

    def test_unknown_tools_and_missing_files_are_refused(self):
        with self.assertRaisesRegex(ValueError, "unsupported media tool: nope"):
            media.run_media_tool("nope", {"path": self.path})
        with self.assertRaises(FileNotFoundError):
            media.run_media_tool("probe_media", {"path": self.path + ".missing"})

    def test_both_servers_offer_every_media_tool(self):
        self.assertEqual({t["name"] for t in gateway._media_tools()}, {"media__" + n for n in NAMES})
        result = {"image": "", "mimeType": "image/jpeg"}  # what make_contact_sheet returns; the others ignore it
        for name in sorted(NAMES):
            with self.subTest(tool=name), mock.patch.object(media, "run_media_tool", return_value=result) as run:
                self.assertFalse(legacy.run_tool(name, {"path": self.path}).get("isError"))
                run.assert_called_once_with(name, {"path": self.path})


class Transcription(unittest.TestCase):
    """Transcripts are cached by the file's content, the model and the language; the source is only read."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = os.path.join(folder.name, "talk.wav")
        with open(self.path, "wb") as f:
            f.write(b"not really audio")
        cache = tempfile.TemporaryDirectory()  # the transcripts cache is in the bridge folder: one per test
        self.addCleanup(cache.cleanup)
        folder_patch = mock.patch("resolve_editor.paths.DIR", cache.name)
        folder_patch.start()
        self.addCleanup(folder_patch.stop)
        self.loads: list[tuple[str, str | None]] = []  # (model, language) of each real transcription
        loads = self.loads

        class Model:  # stands in for faster_whisper.WhisperModel
            def __init__(self, size, device, compute_type):
                self.size = size
                assert (device, compute_type) == ("cpu", "int8"), "CPU/int8 by default (AGENTS.md)"

            def transcribe(self, path, language, word_timestamps, vad_filter):
                loads.append((self.size, language))
                word = mock.Mock(start=0.0, end=0.5, word="Hi", probability=0.9)
                seg = mock.Mock(start=0.0, end=0.5, text="Hi", words=[word])
                return [seg], mock.Mock(language=language or "en", language_probability=0.99)

        patch = mock.patch.dict("sys.modules", {"faster_whisper": mock.Mock(WhisperModel=Model)})
        patch.start()
        self.addCleanup(patch.stop)

    def run_tool(self, **args):
        return media.run_media_tool("transcribe_audio", {"path": self.path, **args})

    def test_the_second_call_is_read_from_the_cache(self):
        first, second = self.run_tool(), self.run_tool()
        self.assertEqual((first["cache_hit"], second["cache_hit"]), (False, True))
        self.assertEqual(first["segments"], second["segments"])
        self.assertEqual(first["segments"][0]["words"][0]["word"], "Hi")
        self.assertEqual(len(self.loads), 1)

    def test_another_model_or_language_is_transcribed_again(self):
        self.run_tool()
        self.run_tool(model="small")
        self.run_tool(language="cs")
        self.run_tool(model="small")
        self.assertEqual(self.loads, [("base", None), ("small", None), ("base", "cs")])

    def test_changed_content_is_transcribed_again(self):
        self.run_tool()
        with open(self.path, "ab") as f:
            f.write(b"!")
        self.assertFalse(self.run_tool()["cache_hit"])
        self.assertEqual(len(self.loads), 2)

    def test_the_source_file_is_not_changed(self):
        before = (pathlib.Path(self.path).read_bytes(), os.stat(self.path).st_mtime_ns)
        self.run_tool()
        self.run_tool()
        self.assertEqual((pathlib.Path(self.path).read_bytes(), os.stat(self.path).st_mtime_ns), before)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["talk.wav"], "nothing written next to it")

    @unittest.expectedFailure  # docs/ISSUES.md I-26: the cached copy keeps the path it was made from
    def test_a_cached_transcript_names_the_file_asked_for(self):
        self.run_tool()
        copy = os.path.join(os.path.dirname(self.path), "copy.wav")
        with open(self.path, "rb") as f, open(copy, "wb") as g:
            g.write(f.read())
        r = media.run_media_tool("transcribe_audio", {"path": copy})
        self.assertTrue(r["cache_hit"])
        self.assertEqual(r["path"], copy)
