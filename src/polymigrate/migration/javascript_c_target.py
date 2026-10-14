"""Bounded JavaScript-to-C adapter composed from checked subset translators."""
from __future__ import annotations

import ast
import hashlib

from polymigrate.migration.boolean_output import has_boolean_print_expression
from polymigrate.migration.javascript_python_target import (
    JavaScriptToPythonTargetAdapter,
    UnsupportedJavaScriptSyntax,
)
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.python_c_target import PythonToCTargetAdapter, UnsupportedPythonSyntax


class JavaScriptToCTargetAdapter:
    """Translate only the checked intersection of the single-file JavaScript/Python/C subsets."""

    language_id = "c"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "javascript":
            raise ValueError("JavaScript-to-C adapter requires a JavaScript source project")
        if len(project.units) != 1 or project.units[0].relative_path != "main.js":
            raise UnsupportedJavaScriptSyntax(
                "Deterministic JavaScript-to-C translation requires exactly one root main.js file"
            )

        intermediate = JavaScriptToPythonTargetAdapter().generate(project, context)
        if len(intermediate) != 1:
            raise UnsupportedJavaScriptSyntax(
                "JavaScript translation did not produce exactly one intermediate Python artifact"
            )
        try:
            tree = ast.parse(intermediate[0].content)
        except (SyntaxError, ValueError, RecursionError):
            raise UnsupportedJavaScriptSyntax("The JavaScript-to-Python intermediate artifact is not valid Python") from None

        # JavaScript prints booleans as lowercase true/false. Python-to-C preserves
        # Python-style boolean text, so reject those cases rather than drift.
        if any(isinstance(node, ast.Constant) and type(node.value) is bool for node in ast.walk(tree)):
            raise UnsupportedJavaScriptSyntax(
                "Boolean literals are excluded from deterministic JavaScript-to-C migration because printed casing differs"
            )

        # Normalize only the verified generated console.log(a, b) shape:
        # print(*[a, b]). Never rewrite arbitrary starred calls.
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

        if has_boolean_print_expression(tree):
            raise UnsupportedJavaScriptSyntax(
                "Boolean-valued output expressions are excluded from deterministic JavaScript-to-C migration because printed casing differs"
            )

        normalized = ast.unparse(ast.fix_missing_locations(tree)) + "\n"
        python_project = SourceProject(
            source_root=project.source_root,
            language_id="python",
            units=(SourceUnit(
                relative_path="main.py",
                source_text=normalized,
                content_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            ),),
            metadata={"composed_from": ("javascript", "python")},
        )
        try:
            artifacts = PythonToCTargetAdapter().generate(python_project, context)
        except UnsupportedPythonSyntax as exc:
            raise UnsupportedJavaScriptSyntax(
                f"JavaScript syntax is outside the composable JavaScript-to-C subset: {exc}"
            ) from None

        self.warnings = [
            "Deterministic JavaScript-to-C subset: composes the bounded JavaScript-to-Python and Python-to-C translators; syntax outside their intersection is rejected.",
            "Only one root main.js file is supported; modules, project manifests, dependencies, frameworks, and full-project migration are not supported.",
        ]
        return artifacts
