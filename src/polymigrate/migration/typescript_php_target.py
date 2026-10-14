"""Bounded TypeScript-to-PHP adapter composed from checked subset translators."""
from __future__ import annotations

import ast
import hashlib

from polymigrate.migration.javascript_python_target import UnsupportedJavaScriptSyntax
from polymigrate.migration.typescript_python_target import TypeScriptToPythonTargetAdapter
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.python_php_target import (
    PythonToPHPTargetAdapter,
    UnsupportedPythonSyntax,
)


class TypeScriptToPHPTargetAdapter:
    """Translate the checked intersection of the TypeScript/Python/PHP subsets."""

    language_id = "php"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "typescript":
            raise ValueError("TypeScript-to-PHP adapter requires a TypeScript source project")
        if len(project.units) != 1:
            raise UnsupportedJavaScriptSyntax(
                "Deterministic TypeScript-to-PHP translation requires exactly one source file"
            )

        python_artifacts = TypeScriptToPythonTargetAdapter().generate(project, context)
        if len(python_artifacts) != 1:
            raise UnsupportedJavaScriptSyntax(
                "TypeScript translation did not produce exactly one intermediate Python artifact"
            )
        try:
            tree = ast.parse(python_artifacts[0].content)
        except (SyntaxError, ValueError, RecursionError):
            raise UnsupportedJavaScriptSyntax(
                "The TypeScript-to-Python intermediate artifact is not valid Python"
            ) from None

        # TypeScript/JavaScript and PHP stringification of booleans differs from the
        # intermediate Python representation. Reject bool literals to avoid drift.
        if any(isinstance(node, ast.Constant) and type(node.value) is bool for node in ast.walk(tree)):
            raise UnsupportedJavaScriptSyntax(
                "Boolean literals are excluded from deterministic TypeScript-to-PHP migration because output formatting would differ"
            )

        # Normalize only the known generated shape for console.log(a, b):
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
            metadata={"composed_from": ("typescript", "python")},
        )
        target = PythonToPHPTargetAdapter()
        try:
            artifacts = target.generate(python_project, context)
        except UnsupportedPythonSyntax as exc:
            raise UnsupportedJavaScriptSyntax(
                f"TypeScript syntax is outside the composable TypeScript-to-PHP subset: {exc}"
            ) from None

        self.warnings = [
            "Deterministic TypeScript-to-PHP subset: composes the bounded TypeScript-to-Python and Python-to-PHP translators; syntax outside their intersection is rejected.",
            "Only one source file is supported; modules, project manifests, dependencies, frameworks, and full-project migration are not supported.",
        ]
        return artifacts
