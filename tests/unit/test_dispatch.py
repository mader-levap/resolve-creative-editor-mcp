"""dispatch.run itself: required arguments, and the tool-name lists agreeing with each other."""
from tests.support import SAMPLE_ARGS, Base, FakeResolve, sample_items

from resolve_editor import dispatch
from resolve_editor.schemas import edit as edit_schema


class RequiredArguments(Base):
    def test_a_missing_argument_is_blocked_before_resolve_is_called(self):
        f = self.use(FakeResolve(sample_items()))
        r = dispatch.run("set_enabled", {"item_ids": ["a"]})
        self.assertEqual(r["_operation"]["status"], "blocked", r)
        self.assertEqual(r["reason"], "missing argument(s): enabled")
        self.assertEqual(f.calls, [])

    def test_null_counts_as_missing_and_every_one_is_named(self):
        self.use(FakeResolve(sample_items()))
        r = dispatch.run("copy_grade", {"from_id": None})
        self.assertEqual(r["reason"], "missing argument(s): from_id, to_ids")

    def test_false_and_empty_are_given(self):
        f = self.use(FakeResolve(sample_items()))
        r = dispatch.run("set_enabled", {"item_ids": [], "enabled": False})
        self.assertNotEqual(r["_operation"]["status"], "blocked", r)
        self.assertIn("set_enabled", f.calls)

    def test_a_batch_step_without_its_argument_is_blocked_in_the_preview(self):
        self.use(FakeResolve(sample_items()))
        r = dispatch.run("batch", {"operations": [{"tool": "move_item", "args": {"item_id": "a"}}]})
        self.assertEqual(r["plan"][0]["preview"]["reason"], "missing argument(s): record")

    def test_every_sample_passes(self):
        for name, args in SAMPLE_ARGS.items():
            with self.subTest(tool=name):
                self.assertEqual(dispatch.missing(name, args), [])


class ToolLists(Base):
    def test_every_list_names_only_real_tools(self):
        for name in ("READ_ONLY", "PREVIEWABLE", "CONFIRMABLE", "TIMELINE_READS"):
            with self.subTest(list=name):
                self.assertLessEqual(getattr(dispatch, name), set(dispatch.HANDLERS))

    def test_every_tool_has_a_schema_and_every_schema_a_tool(self):
        self.assertEqual({t["name"] for t in edit_schema.TOOLS}, set(dispatch.HANDLERS))
