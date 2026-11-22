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
