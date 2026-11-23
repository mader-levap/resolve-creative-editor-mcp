"""Previews change nothing."""
import builtins
import os
import subprocess
from typing import Any
from unittest import mock

from tests.support import READ_OPS, SAMPLE_ARGS, Base, FakeResolve, item, sample_items

from resolve_editor import audit, dispatch, media
from resolve_editor.schemas import edit as schema


class PreviewSafety(Base):
    """Without confirm=true (the boolean, at the top level) nothing may be changed (docs/ISSUES.md I-01)."""

    def setUp(self):
        self.effects: list[tuple[str, object]]
        self.effects, real_open = [], builtins.open

        def guarded_open(file, mode="r", *args, **kw):
            if set(mode) & set("wax+"):
                self.effects.append(("file write", str(file)))
                return real_open(os.devnull, mode, *args, **kw)
            return real_open(file, mode, *args, **kw)

        def forbid(what):
            def call(*args, **kw):
                self.effects.append((what, args[:1]))
                raise RuntimeError(f"{what} during a preview")
            return call

        for target, name, fake in ((builtins, "open", guarded_open),
                                   (audit, "log_audit", lambda *args: self.effects.append(("audit", args[0]))),
                                   (media, "run_media_tool", forbid("media tool")),
                                   (subprocess, "run", forbid("subprocess"))):
            patch = mock.patch.object(target, name, fake)
            patch.start()
            self.addCleanup(patch.stop)

    def attempt(self, tool, args):
        """Run on a fresh fake; return the result and everything that had a side effect."""
        f = self.use(FakeResolve(sample_items()))
        self.effects.clear()
        try:
            r = dispatch.run(tool, args)
        except Exception as exc:
            r = {"error": repr(exc)}
        return r, [op for op in f.calls if op not in READ_OPS] + self.effects

    def test_every_handler_has_sample_args(self):
        self.assertEqual(set(SAMPLE_ARGS), set(dispatch.HANDLERS))

    def test_previewable_matches_schemas(self):
        with_confirm = {t["name"] for t in schema.TOOLS if "confirm" in t["inputSchema"]["properties"]}
        self.assertEqual(dispatch.PREVIEWABLE, with_confirm - {"batch"})

    def test_batch_preview_changes_nothing_for_any_tool(self):
        for tool in sorted(set(dispatch.HANDLERS) - {"batch"}):
            for inner in ({}, {"confirm": True}):
                with self.subTest(tool=tool, inner=inner):
                    r, effects = self.attempt("batch", {"operations": [{"tool": tool,
                                                                        "args": {**SAMPLE_ARGS[tool], **inner}}]})
                    self.assertEqual(effects, [])
                    self.assertEqual(r.get("_operation", {}).get("status"), "preview", r)
                    step = r["plan"][0]
                    if tool in dispatch.PREVIEWABLE:
                        self.assertEqual(step["preview"]["_operation"]["status"], "preview", step)
                    else:
                        self.assertIn("not_run", step)
                        self.assertNotIn("confirm", step["args"])
                        self.assertTrue(r["_operation"]["warnings"])

    def test_unknown_new_handler_is_never_called(self):
        new = mock.Mock(return_value={})
        with mock.patch.dict(dispatch.HANDLERS, {"brand_new_tool": new}):
            r, effects = self.attempt("batch", {"operations": [{"tool": "brand_new_tool"}]})
        new.assert_not_called()
        self.assertEqual(effects, [])
        self.assertIn("not_run", r["plan"][0])

    def test_only_boolean_true_confirms(self):
        cases = {t["name"]: SAMPLE_ARGS[t["name"]] for t in schema.TOOLS if "confirm" in t["inputSchema"]["properties"]}
        cases["batch"] = {"operations": [{"tool": "add_transition", "args": {"item_id": "a"}}]}
        for tool, args in cases.items():
            for value in ("false", "true", "no", 1, [1], False, None):
                with self.subTest(tool=tool, confirm=value):
                    r, effects = self.attempt(tool, {**args, "confirm": value})
                    self.assertEqual(effects, [])
                    self.assertEqual(r.get("_operation", {}).get("status"), "preview", r)

    def test_captions_from_path_are_not_transcribed(self):
        segments: dict[str, list[Any]]
        for segments in ({}, {"segments": []}):
            with self.subTest(segments=segments):
                r, effects = self.attempt("batch", {"operations": [{"tool": "add_captions",
                                                                    "args": {"path": "a.mp4", **segments}}]})
                self.assertEqual(effects, [])
                self.assertIn("not_run", r["plan"][0])

    def test_preview_then_confirm_runs_each_step_once(self):
        f = self.use(FakeResolve([item("a", 1000, 10, src=5)]))
        ops = [{"tool": "add_transition", "args": {"item_id": "a"}},
               {"tool": "set_speed", "args": {"item_id": "a", "percentage": 50, "confirm": False}}]
        dispatch.run("batch", {"operations": ops})
        dispatch.run("batch", {"operations": ops, "confirm": True, "timeline": "T"})
        writes = [c for c in f.calls if c not in READ_OPS and c != "set_current_timeline"]
        self.assertEqual(writes, ["duplicate_timeline", "add_transition", "set_speed"])
