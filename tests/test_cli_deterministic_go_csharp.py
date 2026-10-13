"""CLI integration tests for deterministic Go-to-C# migration."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


class DeterministicGoCSharpCLITests(unittest.TestCase):
    def test_migration_generates_csharp_without_initializing_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text(
                'package main\nimport "fmt"\nfunc main() {\n    count := 6\n    fmt.Println(count * 7)\n}\n',
                encoding="utf-8",
            )
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "go",
                    "--to", "csharp", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            self.assertTrue((output / "main.cs").is_file())
            self.assertTrue((output / "PolyMigrate.csproj").is_file())
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["source_language"], "go")
            self.assertEqual(report["target_language"], "csharp")
            self.assertIn("Go-to-C#", " ".join(report["warnings"]))


if __name__ == "__main__":
    unittest.main()
