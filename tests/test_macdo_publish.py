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


if __name__ == "__main__":
    unittest.main()
