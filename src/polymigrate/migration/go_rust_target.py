"""Bounded Go-to-Rust adapter composed from checked subset translators."""
from __future__ import annotations

import ast
import hashlib

from polymigrate.migration.go_python_target import GoToPythonTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.python_rust_target import PythonToRustTargetAdapter, UnsupportedPythonSyntax


class GoToRustTargetAdapter:
    """Translate the checked intersection of the single-file Go/Python/Rust subsets."""

    language_id = "rust"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "go":
            raise ValueError("Go-to-Rust adapter requires a Go source project")
        if len(project.units) != 1 or project.units[0].relative_path != "main.go":
            raise UnsupportedGoSyntax(
                "Deterministic Go-to-Rust translation requires exactly one root main.go file"
            )

        python_artifacts = GoToPythonTargetAdapter().generate(project, context)
        if len(python_artifacts) != 1:
            raise UnsupportedGoSyntax("Go translation did not produce exactly one intermediate Python artifact")
        try:
            tree = ast.parse(python_artifacts[0].content)
        except (SyntaxError, RecursionError):
            raise UnsupportedGoSyntax("The Go-to-Python intermediate artifact is not valid Python") from None

        # Go prints booleans in lowercase, while Python/Rust's compatibility
        # helper prints True/False. Reject the entire program if that difference
        # could be observable, rather than silently changing output.
        if any(isinstance(node, ast.Constant) and type(node.value) is bool for node in ast.walk(tree)):
            raise UnsupportedGoSyntax(
                "Boolean literals are excluded from deterministic Go-to-Rust output because printed casing differs across runtimes"
            )

        # Go fmt.Println(a, b) is represented by the intermediate adapter as
        # print(*[a, b]); normalize only this exact generated AST shape.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "print":
                continue
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Starred):
                continue
            expansion = node.args[0].value
            if not isinstance(expansion, ast.ListComp) or len(expansion.generators) != 1:
                raise UnsupportedGoSyntax("Unsupported generated print argument expansion")
            iterable = expansion.generators[0].iter
            if not isinstance(iterable, ast.List):
                raise UnsupportedGoSyntax("Unsupported generated print argument expansion")
            node.args = list(iterable.elts)

        normalized_python = ast.unparse(ast.fix_missing_locations(tree)) + "\n"
        python_project = SourceProject(
            source_root=project.source_root,
            language_id="python",
            units=(
                SourceUnit(
                    relative_path="main.py",
                    source_text=normalized_python,
                    content_sha256=hashlib.sha256(normalized_python.encode("utf-8")).hexdigest(),
                ),
            ),
            metadata={"composed_from": ("go", "python")},
        )
        target = PythonToRustTargetAdapter()
        try:
            artifacts = target.generate(python_project, context)
        except UnsupportedPythonSyntax as exc:
            raise UnsupportedGoSyntax(
                f"Go syntax is outside the composable Go-to-Rust subset: {exc}"
            ) from None

        self.warnings = [
            "Deterministic Go-to-Rust subset: composes the bounded Go-to-Python and Python-to-Rust translators; syntax outside their intersection is rejected.",
            "Only one root main.go file is supported; modules, project manifests, dependencies, frameworks, and full-project migration are not supported.",
        ]
        return artifacts
