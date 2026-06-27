"""Tests for the publish-to-macdo client state handling (phase ③).

Pure stdlib (unittest) — run with `python3 -m unittest discover tests` from the repo root.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "publish-to-macdo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import macdo_publish as mp  # noqa: E402


def _args(**kw):
    """A parse_args-shaped Namespace with every attribute merge_manifest reads, defaulted to None."""
    import argparse
    defaults = dict(type=None, name=None, summary=None, description=None,
                    primary_url=None, demo_url=None, source_url=None,
                    framework=None, package_manager=None, build_command=None,
                    output_dir=None, creator_name=None, creator_url=None,
                    category=None, original_language=None, created_with=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class SchemaV2Test(unittest.TestCase):
    def test_schema_constant_is_v2(self):
        self.assertEqual(mp.SCHEMA, "https://mac.do/schemas/tool-manifest-v2.json")

    def test_force_upgrades_carried_forward_v1_schema(self):
        carried = {"schema": "https://mac.do/schemas/tool-manifest-v1.json", "name": "X"}
        manifest = mp.merge_manifest(carried, _args(name="X", summary="s", description="d",
                                                    primary_url="https://example.com"),
                                     {"type": "web"})
        self.assertEqual(manifest["schema"], mp.SCHEMA)


class BuildSubmissionHeadersTest(unittest.TestCase):
    def test_includes_tool_id_header_when_present(self):
        headers = mp.build_submission_headers("cred", "key-1", "11111111-1111-1111-1111-111111111111")
        self.assertEqual(headers["X-Macdo-Tool-Id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(headers["Authorization"], "Bearer cred")
        self.assertEqual(headers["Idempotency-Key"], "key-1")

    def test_omits_tool_id_header_when_absent(self):
        headers = mp.build_submission_headers("cred", "key-1", None)
        self.assertNotIn("X-Macdo-Tool-Id", headers)


class ProjectStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "projects.json"
        os.environ["MACDO_PROJECTS_FILE"] = str(self.store)

    def tearDown(self):
        os.environ.pop("MACDO_PROJECTS_FILE", None)
        self._tmp.cleanup()

    def test_round_trips_manifest_and_tool_id_keyed_by_path(self):
        project = Path("/tmp/example-project")
        mp.save_project_state(project, {"name": "Example"}, "tool-abc")
        state = mp.project_state(project)
        self.assertEqual(state["tool_id"], "tool-abc")
        self.assertEqual(state["manifest"], {"name": "Example"})

    def test_unknown_project_returns_empty_state(self):
        self.assertEqual(mp.project_state(Path("/tmp/never-published")), {})

    def test_does_not_write_into_project_directory(self):
        project_dir = Path(self._tmp.name) / "proj"
        project_dir.mkdir()
        mp.save_project_state(project_dir, {"name": "X"}, "tool-1")
        self.assertFalse((project_dir / "macdo.json").exists())

    def test_dry_run_save_without_tool_id_keeps_manifest(self):
        project = Path("/tmp/dry-run-project")
        mp.save_project_state(project, {"name": "DryRun"}, None)
        state = mp.project_state(project)
        self.assertEqual(state["manifest"], {"name": "DryRun"})
        self.assertNotIn("tool_id", state)

    def test_corrupt_store_is_non_fatal(self):
        self.store.write_text("{ not json", encoding="utf-8")
        self.assertEqual(mp.read_projects(), {})


class LegacyManifestTest(unittest.TestCase):
    def test_reads_legacy_macdo_json_for_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "macdo.json").write_text(json.dumps({"name": "Legacy"}), encoding="utf-8")
            self.assertEqual(mp.read_legacy_manifest(project), {"name": "Legacy"})

    def test_returns_none_without_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(mp.read_legacy_manifest(Path(tmp)))


class CategoryVocabTest(unittest.TestCase):
    def test_vocab_has_39_keys_incl_other(self):
        self.assertEqual(len(mp.CATEGORY_VOCAB), 39)
        self.assertIn("other", mp.CATEGORY_VOCAB)
        self.assertIn("developer-tools", mp.CATEGORY_VOCAB)

    def test_normalize_lowercases_and_hyphenates_whitespace(self):
        self.assertEqual(mp.normalize_category("  Developer Tools "), "developer-tools")
        self.assertEqual(mp.normalize_category("AI Coding"), "ai-coding")

    def test_category_flag_is_repeatable(self):
        args = mp.parse_args(["--category", "developer-tools", "--category", "productivity",
                              "--primary-url", "https://example.com"])
        self.assertEqual(args.category, ["developer-tools", "productivity"])

    def test_default_category_is_other(self):
        manifest = mp.merge_manifest({}, _args(name="X", summary="s", description="d",
                                               primary_url="https://example.com"), {"type": "web"})
        self.assertEqual(manifest["categories"], ["other"])

    def test_valid_categories_pass_validation(self):
        manifest = _valid_manifest(categories=["Developer Tools", "productivity"])
        mp.validate_manifest(manifest)  # must not raise
        # validation normalizes in place to vocab keys
        self.assertEqual(manifest["categories"], ["developer-tools", "productivity"])

    def test_unknown_category_fails_fast(self):
        manifest = _valid_manifest(categories=["nonsense-xyz"])
        with self.assertRaises(SystemExit):
            mp.validate_manifest(manifest)


def _valid_manifest(**overrides):
    """A minimal valid v2 manifest dict for validate_manifest tests."""
    m = {
        "schema": mp.SCHEMA, "name": "Tiny Tool", "summary": "A tiny tool.",
        "description": "A tiny tool for testing.", "type": "web",
        "categories": ["other"], "primary_url": "https://example.com",
    }
    m.update(overrides)
    return m


if __name__ == "__main__":
    unittest.main()
