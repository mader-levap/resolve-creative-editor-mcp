"""Markers need a name and are read back (docs/ISSUES.md I-19)."""
from unittest import mock

from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch, media, session


class Markers(Base):
    def setUp(self):
        self.f = self.use(FakeResolve([item("a", 1000, 300)]))

    def status(self, r):
        return r["_operation"]["status"], r["_operation"]["verification"]

    def test_unnamed_or_blank_markers_are_refused_before_sending(self):
        for markers in ([{"at": 1001}], [{"at": 1001, "name": ""}], [{"at": 1001, "name": "  "}],
                        [{"at": 1001, "name": "ok"}, {"at": 1002}]):
            with self.subTest(markers=markers):
                r = dispatch.run("add_markers", {"markers": markers})
                self.assertEqual(r["_operation"]["status"], "blocked")
                self.assertIn("no name", r["reason"])
                self.assertNotIn("add_markers", self.f.calls)
        r = dispatch.run("add_markers", {"markers": [{"at": 1001, "name": "a"}, {"at": 1002}]})
        self.assertIn("marker(s) 2 have", r["reason"])

    def test_named_markers_are_added_and_read_back(self):
        r = dispatch.run("add_markers", {"markers": [{"at": 1001, "name": "a"}, {"at": "00:00:33:10", "name": "b"}]})
        self.assertEqual(self.status(r), ("success", "passed"), r)
        self.assertEqual(r["_operation"]["changes"]["markers_added"], 2)
        self.assertIn("list_markers", self.f.calls)

    def test_refused_markers_are_named_without_guessing_one_cause(self):
        self.f.markers[1] = {"name": "a"}  # already there, same name: still not added by this call
        r = dispatch.run("add_markers", {"markers": [{"at": 1001, "name": "a"}, {"at": 1002, "name": "b"},
                                                     {"at": 1002, "name": "c"}]})
        self.assertEqual(self.status(r), ("partial", "contradiction"), r)
        self.assertEqual(r["_operation"]["changes"]["markers_added"], 1)
        text = " ".join(r["_operation"]["warnings"])
        self.assertIn(session.to_tc(1001), text)
        self.assertIn("c at", text)
        self.assertIn(" or ", text)  # more than one possible cause

    def test_bridge_count_is_not_trusted(self):
        with mock.patch.object(self.f, "add_markers", lambda markers: len(markers)):  # claims all, adds none
            r = dispatch.run("add_markers", {"markers": [{"at": 1001, "name": "a"}]})
        self.assertEqual(self.status(r), ("partial", "contradiction"), r)

    def test_audio_markers_are_read_back(self):
        def fake_media(name, args):
            return {"silence_intervals": [{"start": 1, "end": 2}]} if name == "detect_silence" else {"duration": 5}
        with mock.patch.object(media, "run_media_tool", fake_media):
            r = dispatch.run("add_audio_markers", {"path": "a.mp4", "kind": "silence"})
            self.assertEqual(self.status(r), ("success", "passed"), r)
            r = dispatch.run("add_audio_markers", {"path": "a.mp4", "kind": "silence"})  # same frame again
            self.assertEqual(self.status(r), ("partial", "contradiction"), r)

    def test_batch_with_an_unnamed_marker_stops_without_writing(self):
        r = dispatch.run("batch", {"confirm": True, "timeline": "T", "operations": [
            {"tool": "add_markers", "args": {"markers": [{"at": 1001}]}},
            {"tool": "add_markers", "args": {"markers": [{"at": 1002, "name": "b"}]}}]})
        self.assertEqual(r["results"][0]["status"], "blocked")
        self.assertEqual(r["not_run"], ["add_markers"])
        self.assertNotIn("add_markers", self.f.calls)
