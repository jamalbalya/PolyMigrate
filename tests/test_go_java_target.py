"""Runtime-equivalence tests for the bounded deterministic Go-to-Java adapter."""
import hashlib, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.go_java_target import GoToJavaTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit

class GoToJavaTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        go, javac, java = shutil.which("go"), shutil.which("javac"), shutil.which("java")
        if not go or not javac or not java:
            self.skipTest("Go and JDK toolchains are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source"; source.mkdir()
            go_file = source / "main.go"; go_file.write_text(source_text, encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("go", (".go",)))
            registry.register_target(GoToJavaTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "go", "java", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            java_file = output / "Main.java"; self.assertTrue(java_file.is_file())
            env = dict(os.environ, GOTOOLCHAIN="local", GOPROXY="off", GO111MODULE="off")
            original = subprocess.run([go, "run", str(go_file)], capture_output=True, text=True, env=env, timeout=60)
            compiled = subprocess.run([javac, str(java_file)], cwd=output, capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            target = subprocess.run([java, "-cp", str(output), "Main"], cwd=output, capture_output=True, text=True, timeout=30)
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    @unittest.skipUnless(shutil.which("go") and shutil.which("javac") and shutil.which("java"), "Go and JDK required")
    def test_arithmetic_and_multiple_print_arguments_match(self):
        self._compare_stdout('package main\nimport "fmt"\nfunc main() {\ncount := 6\nfmt.Println("value=", count * 7)\n}\n')

    @unittest.skipUnless(shutil.which("go") and shutil.which("javac") and shutil.which("java"), "Go and JDK required")
    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout('package main\nimport "fmt"\nfunc main() {\ncount := 2\nif count > 1 {\nfmt.Println("many")\n} else {\nfmt.Println("few")\n}\nfor i := 0; i < 3; i++ {\nfmt.Println(i)\n}\n}\n')

    def test_boolean_output_is_rejected(self):
        src='package main\nimport "fmt"\nfunc main() {\nfmt.Println(true)\n}\n'
        project=SourceProject(Path("."), "go", (SourceUnit("main.go",src,hashlib.sha256(src.encode()).hexdigest()),))
        with self.assertRaisesRegex(UnsupportedGoSyntax, "Boolean literals are excluded"):
            GoToJavaTargetAdapter().generate(project, {})

    def test_multiple_files_are_rejected(self):
        src='package main\nimport "fmt"\nfunc main() {\nfmt.Println(1)\n}\n'; extra="package main\n"
        project=SourceProject(Path("."), "go", (SourceUnit("main.go",src,hashlib.sha256(src.encode()).hexdigest()),SourceUnit("extra.go",extra,hashlib.sha256(extra.encode()).hexdigest())))
        with self.assertRaisesRegex(UnsupportedGoSyntax, "exactly one root main.go"):
            GoToJavaTargetAdapter().generate(project, {})

if __name__ == "__main__": unittest.main()
