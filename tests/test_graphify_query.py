"""Graphify CLI adapter tests use mocked subprocesses and never invoke a real executable."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polymigrate.graph.graphify import GraphifyAdapter


class GraphifyQueryTests(unittest.TestCase):
    def _project(self, tmp):
        root = Path(tmp)
        artifact = root / "graphify-out" / "graph.json"
        artifact.parent.mkdir()
        artifact.write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")
        return root, artifact

    def test_query_uses_argument_list_and_existing_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, artifact = self._project(tmp)
            completed = subprocess.CompletedProcess(["graphify"], 0, "auth -> database", "")
            with patch("polymigrate.graph.graphify.shutil.which", return_value="/usr/bin/graphify"),                  patch("polymigrate.graph.graphify.subprocess.run", return_value=completed) as run:
                result = GraphifyAdapter().query(root, "trace authentication")
            self.assertEqual(result.status, "available")
            self.assertEqual(result.output, "auth -> database")
            args, kwargs = run.call_args
            self.assertEqual(args[0], ["/usr/bin/graphify", "query", "trace authentication", "--graph", str(artifact.resolve())])
            self.assertNotIn("shell", kwargs)

    def test_missing_cli_degrades_without_running_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            with patch("polymigrate.graph.graphify.shutil.which", return_value=None),                  patch("polymigrate.graph.graphify.subprocess.run") as run:
                result = GraphifyAdapter(executable="definitely-not-installed-graphify").query(root, "trace calls")
            self.assertEqual(result.status, "unavailable")
            self.assertIn("not found", result.warning)
            run.assert_not_called()

    def test_timeout_returns_degraded_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            with patch("polymigrate.graph.graphify.shutil.which", return_value="/usr/bin/graphify"),                  patch("polymigrate.graph.graphify.subprocess.run", side_effect=subprocess.TimeoutExpired("graphify", 1)):
                result = GraphifyAdapter(timeout=1).query(root, "trace calls")
            self.assertEqual(result.status, "degraded")
            self.assertIn("timed out", result.warning)

    def test_nonzero_exit_does_not_claim_graph_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            completed = subprocess.CompletedProcess(["graphify"], 2, "", "private stderr")
            with patch("polymigrate.graph.graphify.shutil.which", return_value="/usr/bin/graphify"),                  patch("polymigrate.graph.graphify.subprocess.run", return_value=completed):
                result = GraphifyAdapter().query(root, "trace calls")
            self.assertEqual(result.status, "degraded")
            self.assertIsNone(result.output)
            self.assertNotIn("private stderr", result.warning)

    def test_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._project(tmp)
            completed = subprocess.CompletedProcess(["graphify"], 0, "abcdef", "")
            with patch("polymigrate.graph.graphify.shutil.which", return_value="/usr/bin/graphify"),                  patch("polymigrate.graph.graphify.subprocess.run", return_value=completed):
                result = GraphifyAdapter(max_output_chars=3).query(root, "trace calls")
            self.assertEqual(result.output, "abc")
            self.assertIn("truncated", result.warning)

    def test_graphify_environment_excludes_provider_secrets_and_disables_query_logs(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "do-not-inherit", "PATH": "/usr/bin"}, clear=True):
            environment = GraphifyAdapter._safe_environment()
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertEqual(environment["GRAPHIFY_QUERY_LOG_DISABLE"], "1")
        self.assertEqual(environment["PATH"], "/usr/bin")


if __name__ == "__main__":
    unittest.main()
