"""Bounded JavaScript-to-C# translator composed from checked subset adapters.

The adapter composes JavaScript → Python and Python → C# rather than guessing
at unsupported syntax. It accepts only the intersection of those subsets.
"""
from __future__ import annotations

import ast
import hashlib

from polymigrate.migration.javascript_python_target import (
    JavaScriptToPythonTargetAdapter,
    UnsupportedJavaScriptSyntax,
)
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.python_csharp_target import (
    PythonToCSharpTargetAdapter,
    UnsupportedPythonSyntax,
)


class JavaScriptToCSharpTargetAdapter:
    """Translate a safely composable subset of one JavaScript source file into C#."""

    language_id = "csharp"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "javascript":
            raise ValueError("JavaScript-to-C# adapter requires a JavaScript source project")
        if len(project.units) != 1:
            raise UnsupportedJavaScriptSyntax(
                "Deterministic JavaScript-to-C# translation currently requires exactly one source file"
            )

        intermediate = JavaScriptToPythonTargetAdapter()
        python_artifacts = intermediate.generate(project, context)
        if len(python_artifacts) != 1:
            raise UnsupportedJavaScriptSyntax("JavaScript translation did not produce exactly one intermediate Python artifact")

        artifact = python_artifacts[0]
        try:
            tree = ast.parse(artifact.content)
        except (SyntaxError, RecursionError):
            raise UnsupportedJavaScriptSyntax("The JavaScript-to-Python intermediate artifact is not valid Python") from None

        if any(isinstance(node, ast.Constant) and type(node.value) is bool for node in ast.walk(tree)):
            raise UnsupportedJavaScriptSyntax(
                "Boolean literals are intentionally excluded from the composed JavaScript-to-C# subset"
            )

        # JavaScript-to-Python preserves console.log argument formatting with
        # print(*[...]). Normalize only that generated, verified AST shape.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "print":
                continue
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Starred):
                continue
            expansion = node.args[0].value
            if not isinstance(expansion, ast.ListComp) or len(expansion.generators) != 1:
                raise UnsupportedJavaScriptSyntax("Unsupported generated print argument expansion")
            iterable = expansion.generators[0].iter
            if not isinstance(iterable, ast.List):
                raise UnsupportedJavaScriptSyntax("Unsupported generated print argument expansion")
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
            metadata={"composed_from": ("javascript", "python")},
        )
        target = PythonToCSharpTargetAdapter()
        try:
            artifacts = target.generate(python_project, context)
        except UnsupportedPythonSyntax as exc:
            raise UnsupportedJavaScriptSyntax(
                f"JavaScript syntax is outside the composable JavaScript-to-C# subset: {exc}"
            ) from None

        self.warnings = [
            "Deterministic JavaScript-to-C# subset: composes the bounded JavaScript-to-Python and Python-to-C# translators; syntax outside their intersection is rejected.",
            "Only a single source file is supported; this is not a full project, dependency, or framework migration.",
        ]
        return artifacts
