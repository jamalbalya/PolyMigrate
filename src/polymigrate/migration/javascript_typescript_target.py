"""Bounded JavaScript-to-TypeScript migration composed from checked subset adapters."""
from __future__ import annotations

import ast
import hashlib

from polymigrate.migration.javascript_python_target import (
    JavaScriptToPythonTargetAdapter,
    UnsupportedJavaScriptSyntax,
)
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.python_typescript_target import (
    PythonToTypeScriptTargetAdapter,
    UnsupportedPythonSyntax as TypeScriptUnsupportedPythonSyntax,
)


class JavaScriptToTypeScriptTargetAdapter:
    """Translate the checked intersection of the JavaScript/Python/TypeScript subsets."""

    language_id = "typescript"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "javascript":
            raise ValueError("JavaScript-to-TypeScript adapter requires a JavaScript source project")
        if len(project.units) != 1:
            raise UnsupportedJavaScriptSyntax(
                "Deterministic JavaScript-to-TypeScript translation currently requires exactly one source file"
            )

        intermediate = JavaScriptToPythonTargetAdapter()
        python_artifacts = intermediate.generate(project, context)
        if len(python_artifacts) != 1:
            raise UnsupportedJavaScriptSyntax(
                "JavaScript translation did not produce exactly one intermediate Python artifact"
            )

        try:
            tree = ast.parse(python_artifacts[0].content)
        except (SyntaxError, RecursionError):
            raise UnsupportedJavaScriptSyntax(
                "The JavaScript-to-Python intermediate artifact is not valid Python"
            ) from None

        # Python and JavaScript stringify booleans differently. Reject boolean
        # literals rather than silently changing observable output.
        if any(isinstance(node, ast.Constant) and isinstance(node.value, bool) for node in ast.walk(tree)):
            raise UnsupportedJavaScriptSyntax(
                "Boolean literals are excluded from the deterministic JavaScript-to-TypeScript subset because output formatting would differ"
            )

        # The JavaScript adapter represents console.log(a, b) as print(*[a, b]).
        # Normalize only this generated AST form, not arbitrary source syntax.
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
            units=(
                SourceUnit(
                    relative_path="main.py",
                    source_text=normalized_python,
                    content_sha256=hashlib.sha256(normalized_python.encode("utf-8")).hexdigest(),
                ),
            ),
            metadata={"composed_from": ("javascript", "python")},
        )
        target = PythonToTypeScriptTargetAdapter()
        try:
            artifacts = target.generate(python_project, context)
        except TypeScriptUnsupportedPythonSyntax as exc:
            raise UnsupportedJavaScriptSyntax(
                f"JavaScript syntax is outside the composable JavaScript-to-TypeScript subset: {exc}"
            ) from None

        self.warnings = [
            "Deterministic JavaScript-to-TypeScript subset: composes the bounded JavaScript-to-Python and Python-to-TypeScript translators; syntax outside their intersection is rejected.",
            "Only one source file is supported; this is not full project, dependency, module, or framework migration.",
        ]
        return artifacts
