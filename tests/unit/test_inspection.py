"""Read-only inspection and its cache."""
from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch
from resolve_editor.tools import inspection


class Inspection(Base):
    def test_summary_ignores_transitions_and_is_compact(self):
        items = [item("a", 1000, 10), item("t", 1005, 10, name="Cross Dissolve", type="transition"),
                 item("b", 1010, 10)]
        items += [item(f"g{i}", 1100 + i * 20, 10, name=f"x{i}") for i in range(30)]
        self.use(FakeResolve(items))
        r = dispatch.run("timeline_summary", {"limit": 3})
        self.assertEqual(r["transitions"], 1)
        self.assertEqual(r["overlaps"]["count"], 0)
        self.assertEqual(len(r["gaps"]["first"]), 3)
        self.assertEqual(r["gaps"]["first"][0]["at"], "00:00:34:00")  # frame 1020 at 30 fps

    def test_reused_clips(self):
        r = inspection.analyze([item("a", 0, 10), item("b", 20, 10), item("c", 25, 10, name="z")])
        self.assertEqual(r["reused_clips"], {"a.mp4": ["0", "20"]})

    def test_cache_avoids_repeat_reads(self):
        f = self.use(FakeResolve([item("a", 1000, 10)]))
        dispatch.run("timeline_summary", {})
        dispatch.run("timeline_summary", {})
        self.assertEqual(f.calls.count("list_timeline_items"), 2)  # video + audio once, not twice per call


class EmptyTracks(Base):
    """Tracks come from Resolve's counts, so an empty one shows with 0 (docs/ISSUES.md I-11)."""

    def test_added_empty_tracks_show_with_zero(self):
        f = self.use(FakeResolve([item("a", 1000, 10), item("a2", 1000, 10, kind="audio")]))
        f.tracks["video"] = 3
        f.tracks["audio"] = 2
        r = dispatch.run("timeline_summary", {})
        self.assertEqual(r["tracks"], {"A1": 1, "A2": 0, "V1": 1, "V2": 0, "V3": 0})
        self.assertNotIn("note", r)

    def test_an_older_bridge_lists_tracks_with_items_and_says_so(self):
        f = self.use(FakeResolve([item("a", 1000, 10)]))
        f.track_counts = False
        f.tracks["video"] = 3
        r = dispatch.run("timeline_summary", {})
        self.assertEqual(r["tracks"], {"V1": 1})
        self.assertIn("restart the bridge", r["note"])

    def test_analyze_without_counts_is_unchanged(self):
        r = inspection.analyze([item("a", 0, 10, track=2)])
        self.assertEqual(r["tracks"], {"V2": 1})


class InspectDetails(Base):
    def test_details_add_settings_and_list_only_changed_ones(self):
        items = [item("a", 1000, 10, src=5), item("t", 1008, 4, type="transition"), item("b", 1010, 10)]
        f = self.use(FakeResolve(items, details={
            "a": {"properties": {"ZoomX": 1.5, "Opacity": 100, "Pan": 0}, "markers": {"7": {"name": "m"}}},
            "b": {"enabled": False, "color": "", "speed": {"Percentage": 50}}}))
        f.settings["t"] = {}  # a transition has no clip details
        r = dispatch.run("inspect_range", {"start": 1000, "end": 1020, "details": True})
        rows = {x["id"]: x for x in r["items"]}
        self.assertEqual(r["count"], 3)
        self.assertEqual((rows["a"]["changed_settings"], rows["a"]["markers"], rows["a"]["color"]),
                         ({"ZoomX": 1.5}, 1, "Orange"))
        self.assertEqual((rows["b"]["enabled"], rows["b"]["speed"], rows["b"]["color"]), (False, 50, None))
        self.assertNotIn("changed_settings", rows["t"], "transitions aren't asked for details")

    def test_without_details_no_details_are_read(self):
        f = self.use(FakeResolve([item("a", 1000, 10)]))
        r = dispatch.run("inspect_range", {"start": 1000, "end": 1020})
        self.assertNotIn("changed_settings", r["items"][0])
        self.assertNotIn("item_details", f.calls)
