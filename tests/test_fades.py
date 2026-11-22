"""Fades."""
from tests.support import Base, FakeResolve, item

from resolve_editor import dispatch


class Fades(Base):
    def test_missing_end_keeps_current_length(self):
        f = self.use(FakeResolve([item("a", 1000, 60)], details={"a": {"fades": {"FadeIn": 30, "FadeOut": 10}}}))
        r = dispatch.run("set_fades", {"item_ids": ["a"], "fade_out": 60})
        self.assertEqual(r["_operation"]["verification"], "passed", r)
        self.assertEqual(f.settings["a"]["fades"], {"FadeIn": 30, "FadeOut": 60})
        self.assertIn("lost when Resolve restarts", r["_operation"]["warnings"][0])
        dispatch.run("set_fades", {"item_ids": ["a"], "fade_in": 0})
        self.assertEqual(f.settings["a"]["fades"], {"FadeIn": 0, "FadeOut": 60})

    def test_both_ends_given_skips_read(self):
        f = self.use(FakeResolve([item("a", 1000, 60)]))
        dispatch.run("set_fades", {"item_ids": ["a"], "fade_in": 5, "fade_out": 6})
        self.assertNotIn("item_details", f.calls)
        self.assertEqual(f.settings["a"]["fades"], {"FadeIn": 5, "FadeOut": 6})

    def test_nothing_given_is_refused(self):
        f = self.use(FakeResolve([item("a", 1000, 60)]))
        self.assertEqual(dispatch.run("set_fades", {"item_ids": ["a"]})["_operation"]["status"], "blocked")
        self.assertNotIn("set_fades", f.calls)
