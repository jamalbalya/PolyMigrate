"""Bounded JavaScript-to-Go translator composed from checked subset adapters.

The adapter composes JavaScript → Python and Python → Go rather than guessing
at unsupported syntax. It remains limited to the intersection of both subsets.
"""
from __future__ import annotations

import ast
import hashlib

from polymigrate.migration.javascript_python_target import (
    JavaScriptToPythonTargetAdapter,
    UnsupportedJavaScriptSyntax,
)
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.python_go_target import (
    PythonToGoTargetAdapter,
    UnsupportedPythonSyntax,
)


class JavaScriptToGoTargetAdapter:
    """Translate the safely composable JavaScript/Python/Go subset into Go."""

    language_id = "go"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "javascript":
            raise ValueError("JavaScript-to-Go adapter requires a JavaScript source project")
        if len(project.units) != 1:
            raise UnsupportedJavaScriptSyntax(
                "Deterministic JavaScript-to-Go translation currently requires exactly one source file"
            )

        intermediate = JavaScriptToPythonTargetAdapter()
        try:
            python_artifacts = intermediate.generate(project, context)
        except UnsupportedJavaScriptSyntax:
            raise
        if not python_artifacts:
            raise UnsupportedJavaScriptSyntax("JavaScript translation produced no intermediate Python artifact")

        for artifact in python_artifacts:
            try:
                intermediate_tree = ast.parse(artifact.content)
            except SyntaxError as exc:
                raise UnsupportedJavaScriptSyntax(
                    "The JavaScript-to-Python intermediate artifact is not valid Python"
                ) from None
            if any(
                isinstance(node, ast.Constant) and type(node.value) is bool
                for node in ast.walk(intermediate_tree)
            ):
                raise UnsupportedJavaScriptSyntax(
                    "Boolean literals are not supported in the deterministic JavaScript-to-Go subset because their printed casing differs across runtimes"
                )
            # JavaScript-to-Python preserves console.log's multi-argument
            # formatting with print(*[...]). The Python-to-Go parser accepts
            # ordinary positional print arguments, so normalize only this
            # generated, structurally verified list-comprehension shape.
            for node in ast.walk(intermediate_tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "print":
                    continue
                if len(node.args) != 1 or not isinstance(node.args[0], ast.Starred):
                    continue
                value = node.args[0].value
                if not isinstance(value, ast.ListComp) or len(value.generators) != 1:
                    raise UnsupportedJavaScriptSyntax("Unsupported generated print argument expansion")
                iterable = value.generators[0].iter
                if not isinstance(iterable, ast.List):
                    raise UnsupportedJavaScriptSyntax("Unsupported generated print argument expansion")
                node.args = list(iterable.elts)
            artifact_content = ast.unparse(ast.fix_missing_locations(intermediate_tree)) + "\n"

        python_units = tuple(
            SourceUnit(
                relative_path=artifact.relative_path,
                source_text=artifact_content,
                content_sha256=hashlib.sha256(artifact_content.encode("utf-8")).hexdigest(),
            )
            for artifact in python_artifacts
        )
        python_project = SourceProject(
            source_root=project.source_root,
            language_id="python",
            units=python_units,
            metadata={"composed_from": ("javascript", "python")},
        )
        target = PythonToGoTargetAdapter()
        try:
            artifacts = target.generate(python_project, context)
        except UnsupportedPythonSyntax as exc:
            raise UnsupportedJavaScriptSyntax(
                f"JavaScript syntax is outside the composable JavaScript-to-Go subset: {exc}"
            ) from None

        self.warnings = [
            "This deterministic translator composes the bounded JavaScript-to-Python and Python-to-Go subsets; syntax outside their intersection is rejected.",
            "Only a single source file is supported; this is not a full project, dependency, or framework migration.",
        ]
        return artifacts
