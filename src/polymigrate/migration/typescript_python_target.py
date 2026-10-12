"""Deterministic TypeScript-to-Python adapter reusing the constrained scalar parser."""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from polymigrate.migration.javascript_python_target import _Parser, UnsupportedJavaScriptSyntax
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject


class TypeScriptToPythonTargetAdapter:
    """Translate a single main.ts scalar subset with validated primitive annotations."""

    language_id = "python"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict[str, Any]) -> list[GeneratedArtifact]:
        if project.language_id != "typescript":
            raise ValueError("TypeScript-to-Python adapter requires a TypeScript source project")
        if len(project.units) != 1 or project.units[0].relative_path != "main.ts":
            raise UnsupportedJavaScriptSyntax("TypeScript-to-Python subset currently requires one root main.ts file")
        if PurePosixPath(project.units[0].relative_path).suffix.lower() != ".ts":
            raise UnsupportedJavaScriptSyntax("Only .ts source files are supported; TSX is not supported")
        self.warnings = [
            "Deterministic TypeScript-to-Python subset only: a single root main.ts file with scalar declarations, primitive number/string/boolean annotations, same-type assignments, safe-integer arithmetic, scalar console.log, print-only if/else, and bounded integer for-loops is supported.",
            "Interfaces, type aliases, enums, generics, functions, imports/modules, TSX, floating-point arithmetic, escaped string literals, dynamic coercion, and full-project migration are unsupported.",
        ]
        generated = _Parser(project.units[0].source_text, allow_type_annotations=True).parse()
        return [GeneratedArtifact("main.py", generated)]
