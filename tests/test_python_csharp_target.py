"""Tests for the constrained deterministic Python-to-C# translator."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.pipeline import SourceProject, SourceUnit
from polymigrate.migration.python_csharp_target import PythonToCSharpTargetAdapter, UnsupportedPythonSyntax


def project_for(source: str, path: str = "main.py") -> SourceProject:
    return SourceProject(
        Path("."),
        "python",
        (SourceUnit(path, source, hashlib.sha256(source.encode("utf-8")).hexdigest()),),
    )


class PythonToCSharpTranslatorTests(unittest.TestCase):
    def test_translates_assignments_arithmetic_and_positional_print(self):
        artifacts = PythonToCSharpTargetAdapter().generate(
            project_for("x = 6\ny = x * 7\nprint(y)\n"), {}
        )
        generated = next(item for item in artifacts if item.relative_path == "main.cs")
        project_file = next(item for item in artifacts if item.relative_path == "PolyMigrate.csproj")
        self.assertIn("int x = 6;", generated.content)
        self.assertIn("int y = (x * 7);", generated.content)
        self.assertIn("Console.WriteLine(string.Join", generated.content)
        self.assertIn("<TargetFramework>net8.0</TargetFramework>", project_file.content)
        self.assertIn("<TreatWarningsAsErrors>true</TreatWarningsAsErrors>", project_file.content)

    def test_preserves_python_boolean_text_and_string_concatenation(self):
        generated = PythonToCSharpTargetAdapter().generate(
            project_for("prefix = 'hello ' + 'world'\nflag = True\nprint(prefix, flag, str(False))\n"), {}
        )[0].content
        self.assertIn('string prefix = ("hello " + "world");', generated)
        self.assertIn("bool flag = true;", generated)
        self.assertIn("PolymigrateString(false)", generated)
        self.assertIn('value ? "True" : "False"', generated)

    def test_translates_nested_source_path(self):
        artifacts = PythonToCSharpTargetAdapter().generate(
            project_for("print('module')\n", "src/module.py"), {}
        )
        self.assertIn("src/module.cs", [item.relative_path for item in artifacts])

    def test_translates_print_only_if_elif_else_conditions(self):
        generated = PythonToCSharpTargetAdapter().generate(
            project_for(
                "count = 3\nlabel = 'ready'\n"
                "if count > 5:\n    print('high')\n"
                "elif count > 0 and label:\n    print('positive', count)\n"
                "else:\n    print('zero')\n"
            ), {}
        )[0].content
        self.assertIn("if ((count > 5)) {", generated)
        self.assertIn("} else if (((count > 0) && (!string.IsNullOrEmpty(label)))) {", generated)
        self.assertIn('Console.WriteLine(string.Join(" ", new string[] { PolymigrateString("positive"), PolymigrateString(count) }));', generated)
        self.assertIn("} else {", generated)

    def test_translates_bounded_range_loop_and_preserves_post_loop_value(self):
        generated = PythonToCSharpTargetAdapter().generate(
            project_for("for i in range(2, 5):\n    print(i)\nprint(i)\n"), {}
        )[0].content
        self.assertIn("for (int polymigrateRangeCounter0 = 2; polymigrateRangeCounter0 < 5; polymigrateRangeCounter0 += 1) {", generated)
        self.assertIn("int i = 4;", generated)
        self.assertLess(generated.index("for (int polymigrateRangeCounter0 = 2"), generated.index("int i = 4;"))

    def test_range_loop_assignments_update_existing_variables_safely(self):
        generated = PythonToCSharpTargetAdapter().generate(
            project_for(
                "counter = 0\n"
                "for i in range(3):\n    counter = counter + 1\n"
                "total = 0\n"
                "for j in range(3):\n    total = total + j\n"
                "print(counter, total)\n"
            ), {}
        )[0].content
        self.assertIn("counter = (counter + 1);", generated)
        self.assertIn("total = (total + polymigrateRangeCounter1);", generated)

    def test_range_loop_assignments_reject_unsafe_or_semantically_ambiguous_cases(self):
        cases = (
            ("for i in range(3):\n    i = i + 1\n", "cannot reassign the loop variable"),
            ("for i in range(3):\n    value = 1\n", "must target existing variables"),
            ("value = 1\nfor i in range(3):\n    value = 'text'\nprint(value)\n", "must preserve the variable type"),
            ("limit = 3\nfor i in range(limit):\n    limit = limit - 1\nprint(limit)\n", "variables used to compute range bounds"),
            ("value = 2147483646\nfor i in range(2):\n    value = value + 1\nprint(value)\n", "signed 32-bit range"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                PythonToCSharpTargetAdapter().generate(project_for(source), {})

    def test_zero_iteration_loop_preserves_state_and_skips_unreachable_assignments(self):
        generated = PythonToCSharpTargetAdapter().generate(
            project_for(
                "value = 2147483647\n"
                "for i in range(0):\n    value = value + 1\n"
                "print(value)\n"
            ), {}
        )[0].content
        self.assertNotIn("polymigrateRangeCounter", generated)
        self.assertIn("int value = 2147483647;", generated)
        self.assertIn("Console.WriteLine(string.Join", generated)

    def test_generated_range_loop_assignments_match_python_output_when_dotnet_is_installed(self):
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            self.skipTest(".NET SDK is not installed in this test environment")
        source = (
            "counter = 0\n"
            "for i in range(3):\n    counter = counter + 1\n"
            "total = 0\n"
            "for j in range(3):\n    total = total + j\n"
            "print(counter, total)\n"
        )
        artifacts = PythonToCSharpTargetAdapter().generate(project_for(source), {})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for artifact in artifacts:
                path = root / artifact.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(artifact.content, encoding="utf-8")
            build = subprocess.run(
                [dotnet, "build", str(root / "PolyMigrate.csproj"), "--configuration", "Release", "--nologo", "--verbosity", "quiet"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)
            assembly = root / "bin" / "Release" / "net8.0" / "PolyMigrate.dll"
            run = subprocess.run([dotnet, str(assembly)], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "3 3\\n")

    def test_zero_iteration_range_does_not_define_loop_variable(self):
        generated = PythonToCSharpTargetAdapter().generate(
            project_for("for i in range(0):\n    print(i)\nprint('done')\n"), {}
        )[0].content
        self.assertNotIn("for (int i", generated)
        self.assertNotIn("int i =", generated)
        self.assertIn('Console.WriteLine(string.Join(" ", new string[] { PolymigrateString("done") }));', generated)
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "used before assignment"):
            PythonToCSharpTargetAdapter().generate(
                project_for("for i in range(0):\n    print(i)\nprint(i)\n"), {}
            )

    def test_range_loop_rejects_unsafe_or_unsupported_cases(self):
        cases = (
            ("for i in range(3, 0, 0):\n    print(i)\n", "step cannot be zero"),
            ("for i in range(10001):\n    print(i)\n", "limited to 10000 actual iterations"),
            ("i = 4\nfor i in range(3):\n    print(i)\n", "cannot shadow an already assigned variable"),
            ("for i in range(3):\n    i = 4\n", "cannot reassign the loop variable"),
            ("for i in range(3):\n    if i:\n        print(i)\n", "range\\(\\) loop bodies may contain"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                PythonToCSharpTargetAdapter().generate(project_for(source), {})

    def test_generated_negative_range_loop_matches_python_output_when_dotnet_is_installed(self):
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            self.skipTest(".NET SDK is not installed in this test environment")
        source = "for i in range(3, 0, -1):\n    print(i)\nprint(i)\n"
        artifacts = PythonToCSharpTargetAdapter().generate(project_for(source), {})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for artifact in artifacts:
                path = root / artifact.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(artifact.content, encoding="utf-8")
            build = subprocess.run(
                [dotnet, "build", str(root / "PolyMigrate.csproj"), "--configuration", "Release", "--nologo", "--verbosity", "quiet"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)
            assembly = root / "bin" / "Release" / "net8.0" / "PolyMigrate.dll"
            run = subprocess.run([dotnet, str(assembly)], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "3\n2\n1\n1\n")

    def test_rejects_conditional_assignments_nested_control_and_chained_comparisons(self):
        cases = (
            ("x = 1\nif x:\n    x = 2\nprint(x)\n", "conditional bodies may contain only print"),
            ("x = 1\nif x:\n    if x:\n        print(x)\n", "conditional bodies may contain only print"),
            ("x = 1\nif 0 < x < 2:\n    print(x)\n", "Chained comparisons are not supported"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                PythonToCSharpTargetAdapter().generate(project_for(source), {})

    def test_generated_conditional_project_matches_python_output_when_dotnet_is_installed(self):
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            self.skipTest(".NET SDK is not installed in this test environment")
        source = (
            "count = 3\nlabel = 'ready'\n"
            "if count > 5:\n    print('high')\n"
            "elif count > 0 and label:\n    print('positive', count)\n"
            "else:\n    print('zero')\n"
        )
        artifacts = PythonToCSharpTargetAdapter().generate(project_for(source), {})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for artifact in artifacts:
                path = root / artifact.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(artifact.content, encoding="utf-8")
            build = subprocess.run(
                [dotnet, "build", str(root / "PolyMigrate.csproj"), "--configuration", "Release", "--nologo", "--verbosity", "quiet"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)
            assembly = root / "bin" / "Release" / "net8.0" / "PolyMigrate.dll"
            run = subprocess.run([dotnet, str(assembly)], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "positive 3\n")

    def test_supports_print_only_conditional_control_flow(self):
        generated = PythonToCSharpTargetAdapter().generate(
            project_for("value = 1\nif value:\n    print(value)\n"), {}
        )[0].content
        self.assertIn("if ((value != 0)) {", generated)
        self.assertIn('Console.WriteLine(string.Join(" ", new string[] { PolymigrateString(value) }));', generated)

    def test_rejects_reserved_and_builtin_identifiers(self):
        for name in ("class", "var", "Console", "PolymigrateString"):
            with self.subTest(name=name), self.assertRaises(UnsupportedPythonSyntax):
                PythonToCSharpTargetAdapter().generate(
                    project_for(f"{name} = 1" + chr(10) + f"print({name})" + chr(10)), {}
                )

    def test_rejects_lone_unicode_surrogates_before_writing_output(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "lone Unicode surrogates"):
            PythonToCSharpTargetAdapter().generate(
                project_for("print('\\ud800')\n"), {}
            )

    def test_rejects_signed_32_bit_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "signed 32-bit range"):
            PythonToCSharpTargetAdapter().generate(
                project_for("value = 2147483647 + 1\nprint(value)\n"), {}
            )

    def test_requires_single_source_file_for_standalone_project(self):
        source = project_for("print('one')\n")
        second_text = "print('two')\n"
        second = SourceUnit("other.py", second_text, hashlib.sha256(second_text.encode()).hexdigest())
        project = SourceProject(Path("."), "python", (source.units[0], second))
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one Python source file"):
            PythonToCSharpTargetAdapter().generate(project, {})

    def test_generated_csharp_builds_and_runs_when_dotnet_is_installed(self):
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            self.skipTest(".NET SDK is not installed in this test environment")
        artifacts = PythonToCSharpTargetAdapter().generate(
            project_for("prefix = 'value='\nnumber = 6 * 7\nflag = True\nprint(prefix, number, flag, str(False))\n"), {}
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for artifact in artifacts:
                path = root / artifact.relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(artifact.content, encoding="utf-8")
            build = subprocess.run(
                [dotnet, "build", str(root / "PolyMigrate.csproj"), "--configuration", "Release", "--nologo", "--verbosity", "quiet"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)
            assembly = root / "bin" / "Release" / "net8.0" / "PolyMigrate.dll"
            run = subprocess.run([dotnet, str(assembly)], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "value= 42 True False\n")


if __name__ == "__main__":
    unittest.main()
