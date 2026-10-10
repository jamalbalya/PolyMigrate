"""Tests for bounded, allowlisted project-manifest inventory."""
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.manifests import scan_project_manifests


class ProjectManifestScanTests(unittest.TestCase):
    def test_scans_known_manifests_and_redacts_recognizable_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                '{"name":"demo","api_key":"sk-12345678901234567890"}', encoding="utf-8",
            )
            (root / ".env").write_text("API_KEY=sk-12345678901234567890", encoding="utf-8")
            nested = root / "node_modules" / "dep"
            nested.mkdir(parents=True)
            (nested / "package.json").write_text('{"name":"vendor"}', encoding="utf-8")
            manifests, warnings = scan_project_manifests(root)
            self.assertEqual([item["path"] for item in manifests], ["package.json"])
            self.assertNotIn("sk-12345678901234567890", manifests[0]["content"])
            self.assertTrue(any("redacted" in warning for warning in warnings))

    def test_scan_respects_file_and_total_size_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"name":"demo"}', encoding="utf-8")
            (root / "requirements.txt").write_text("requests==2.0\n", encoding="utf-8")
            manifests, warnings = scan_project_manifests(root, max_files=1)
            self.assertEqual(len(manifests), 1)
            self.assertTrue(any("file limit" in warning for warning in warnings))
            manifests, warnings = scan_project_manifests(root, max_total_bytes=5)
            self.assertEqual(manifests, [])
            self.assertTrue(any("byte limit" in warning for warning in warnings))

    def test_symlink_manifest_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            outside = Path(tmp) / "package.json"
            outside.write_text('{"name":"outside"}', encoding="utf-8")
            link = root / "package.json"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation is unavailable")
            manifests, _ = scan_project_manifests(root)
            self.assertEqual(manifests, [])


if __name__ == "__main__":
    unittest.main()
