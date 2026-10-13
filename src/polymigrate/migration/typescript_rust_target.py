"""Bounded TypeScript-to-Rust adapter composed from checked subset translators."""
from __future__ import annotations

import ast
import hashlib

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.javascript_python_target import UnsupportedJavaScriptSyntax
from polymigrate.migration.typescript_python_target import TypeScriptToPythonTargetAdapter
from polymigrate.migration.python_rust_target import PythonToRustTargetAdapter, UnsupportedPythonSyntax


class TypeScriptToRustTargetAdapter:
    """Translate the checked intersection of the single-file TypeScript/Python/Rust subsets."""

    language_id = "rust"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "typescript":
            raise ValueError("TypeScript-to-Rust adapter requires a TypeScript source project")
        if len(project.units) != 1 or project.units[0].relative_path != "main.ts":
            raise UnsupportedJavaScriptSyntax(
                "Deterministic TypeScript-to-Rust translation requires exactly one root main.ts file"
            )

        python_artifacts = TypeScriptToPythonTargetAdapter().generate(project, context)
        if len(python_artifacts) != 1:
            raise UnsupportedJavaScriptSyntax(
                "TypeScript translation did not produce exactly one intermediate Python artifact"
            )
        try:
            tree = ast.parse(python_artifacts[0].content)
        except (SyntaxError, RecursionError):
            raise UnsupportedJavaScriptSyntax(
                "The TypeScript-to-Python intermediate artifact is not valid Python"
            ) from None

        # Python's bool formatting is True/False while Rust prints true/false.
        # Reject boolean literals anywhere in the composed program rather than
        # silently changing output or branch semantics.
        if any(isinstance(node, ast.Constant) and type(node.value) is bool for node in ast.walk(tree)):
            raise UnsupportedJavaScriptSyntax(
                "Boolean literals are excluded from deterministic TypeScript-to-Rust migration because output casing differs across runtimes"
            )

        # Normalize only the generated shape for console.log(a, b):
        # print(*[a, b]). Do not rewrite arbitrary starred calls.
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
        target = PythonToRustTargetAdapter()
        try:
            artifacts = target.generate(python_project, context)
        except UnsupportedPythonSyntax as exc:
            raise UnsupportedJavaScriptSyntax(
                f"TypeScript syntax is outside the composable TypeScript-to-Rust subset: {exc}"
            ) from None

        self.warnings = [
            "Deterministic TypeScript-to-Rust subset: composes the bounded TypeScript-to-Python and Python-to-Rust translators; syntax outside their intersection is rejected.",
            "Only one root main.ts file is supported; modules, project manifests, dependencies, frameworks, and full-project migration are not supported.",
        ]
        return artifacts
