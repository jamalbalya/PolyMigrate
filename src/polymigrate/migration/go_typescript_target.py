"""Bounded Go-to-TypeScript translator composed from checked subset adapters.

The adapter composes Go → Python and Python → TypeScript rather than guessing
at unsupported syntax. It accepts only the intersection of those subsets.
"""
from __future__ import annotations

import ast
import hashlib

from polymigrate.migration.go_python_target import GoToPythonTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.python_javascript_target import (
    PythonToTypeScriptTargetAdapter,
    UnsupportedPythonSyntax,
)


class GoToTypeScriptTargetAdapter:
    """Translate a safely composable subset of a single Go main.go into TypeScript."""

    language_id = "typescript"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "go":
            raise ValueError("Go-to-TypeScript adapter requires a Go source project")
        if len(project.units) != 1:
            raise UnsupportedGoSyntax(
                "Deterministic Go-to-JavaScript translation currently requires exactly one source file"
            )

        intermediate = GoToPythonTargetAdapter()
        python_artifacts = intermediate.generate(project, context)
        if len(python_artifacts) != 1:
            raise UnsupportedGoSyntax("Go translation did not produce exactly one intermediate Python artifact")

        artifact = python_artifacts[0]
        try:
            tree = ast.parse(artifact.content)
        except (SyntaxError, RecursionError):
            raise UnsupportedGoSyntax("The Go-to-Python intermediate artifact is not valid Python") from None

        if any(isinstance(node, ast.Constant) and type(node.value) is bool for node in ast.walk(tree)):
            raise UnsupportedGoSyntax(
                "Boolean literals are not supported in deterministic Go-to-JavaScript output because their printed casing differs across runtimes"
            )

        # Go-to-Python preserves fmt.Println argument formatting with
        # print(*[...]). Normalize only that generated, verified AST shape.
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
            units=(SourceUnit(
                relative_path="main.py",
                source_text=normalized_python,
                content_sha256=hashlib.sha256(normalized_python.encode("utf-8")).hexdigest(),
            ),),
            metadata={"composed_from": ("go", "python")},
        )
        target = PythonToJavaScriptTargetAdapter()
        try:
            artifacts = target.generate(python_project, context)
        except UnsupportedPythonSyntax as exc:
            raise UnsupportedGoSyntax(
                f"Go syntax is outside the composable Go-to-JavaScript subset: {exc}"
            ) from None

        self.warnings = [
            "Deterministic Go-to-JavaScript subset: composes the bounded Go-to-Python and Python-to-TypeScript translators; syntax outside their intersection is rejected.",
            "Only a single source file is supported; this is not a full project, dependency, or framework migration.",
        ]
        return artifacts
