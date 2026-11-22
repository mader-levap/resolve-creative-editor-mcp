"""Media tools: every tool in the schema has a handler, calls reach it, and both servers offer it."""
import os
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
