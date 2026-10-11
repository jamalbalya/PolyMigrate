"""Tests for bounded, content-free cross-file context supplied to migration models."""
import hashlib
import json
import unittest

from polymigrate.migration.context import build_source_project_index
from polymigrate.migration.pipeline import SourceProject, SourceUnit


def make_project(count=4):
    units = []
    for index in range(count):
        source = f"def function_{index}(): return {index}"
        units.append(SourceUnit(
            relative_path=f"src/file_{index}.py",
            source_text=source,
            content_sha256=hashlib.sha256(source.encode()).hexdigest(),
            symbols=(f"function_{index}", "Client"),
            dependencies=("requests", "project.helpers"),
        ))
    return SourceProject(
        source_root=__import__("pathlib").Path("/tmp/source"),
        language_id="python",
        units=tuple(units),
        metadata={"parser_backends": ["python-ast"]},
    )


class SourceProjectIndexTests(unittest.TestCase):
    def test_index_is_deterministic_and_content_free(self):
        project = make_project()
        first = build_source_project_index(project)
        second = build_source_project_index(project)
        self.assertEqual(first, second)
        self.assertEqual(first["total_source_files"], 4)
        self.assertEqual(first["included_file_count"], 4)
        self.assertEqual(first["files"][0]["path"], "src/file_0.py")
        self.assertIn("function_0", first["files"][0]["symbols"])
        self.assertIn("requests", first["files"][0]["dependencies"])
        self.assertNotIn("source_text", json.dumps(first))
        self.assertNotIn("def function_0", json.dumps(first))

    def test_file_and_metadata_counts_are_bounded(self):
        index = build_source_project_index(
            make_project(10), max_files=3, max_symbols_per_file=1,
            max_dependencies_per_file=1,
        )
        self.assertEqual(index["included_file_count"], 3)
        self.assertEqual(index["omitted_file_count"], 7)
        self.assertTrue(index["truncated"])
        self.assertEqual(len(index["files"][0]["symbols"]), 1)
        self.assertEqual(len(index["files"][0]["dependencies"]), 1)

    def test_total_serialized_context_respects_size_cap(self):
        project = make_project(100)
        index = build_source_project_index(project, max_context_chars=512)
        serialized = json.dumps(index, sort_keys=True, ensure_ascii=False)
        self.assertLessEqual(len(serialized), 512)
        self.assertTrue(index["truncated"])
        self.assertEqual(index["included_file_count"], len(index["files"]))
        self.assertEqual(index["omitted_file_count"], 100 - len(index["files"]))

    def test_invalid_limits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            build_source_project_index(make_project(), max_files=0)
        with self.assertRaisesRegex(ValueError, "at least 512"):
            build_source_project_index(make_project(), max_context_chars=100)


if __name__ == "__main__":
    unittest.main()
