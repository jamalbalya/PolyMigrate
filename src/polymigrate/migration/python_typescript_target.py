"""Deterministic TypeScript target for the bounded Python-to-JavaScript subset."""
from __future__ import annotations

import ast
from pathlib import PurePosixPath

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject
from polymigrate.migration.python_javascript_target import (
    PythonToJavaScriptTargetAdapter,
    UnsupportedPythonSyntax as JavaScriptUnsupportedPythonSyntax,
)


class UnsupportedPythonSyntax(ValueError):
    """Raised when source syntax is outside the supported Python-to-TypeScript subset."""


_TYPESCRIPT_RESERVED = {
    "abstract", "any", "as", "assert", "asserts", "async", "await", "bigint",
    "boolean", "break", "case", "catch", "class", "const", "constructor",
    "continue", "debugger", "declare", "default", "delete", "do", "else", "enum",
    "export", "extends", "false", "finally", "for", "from", "function", "get",
    "global", "if", "implements", "import", "in", "infer", "instanceof",
    "interface", "is", "keyof", "let", "module", "namespace", "never", "new",
    "null", "number", "object", "of", "package", "private", "protected", "public",
    "readonly", "require", "return", "set", "static", "string", "super", "switch",
    "symbol", "this", "throw", "true", "try", "type", "typeof", "undefined",
    "unique", "unknown", "var", "void", "while", "with", "yield",
}


class PythonToTypeScriptTargetAdapter:
    """Translate one Python file through the checked JavaScript subset into TypeScript."""

    language_id = "typescript"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "python":
            raise ValueError("Python-to-TypeScript adapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax(
                "Deterministic Python-to-TypeScript translation currently requires exactly one Python source file"
            )
        unit = project.units[0]
        try:
            tree = ast.parse(unit.source_text, filename=unit.relative_path)
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise UnsupportedPythonSyntax(f"Cannot parse {unit.relative_path}: {type(exc).__name__}") from None
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id in _TYPESCRIPT_RESERVED:
                raise UnsupportedPythonSyntax(
                    f"Variable name '{node.id}' is reserved by TypeScript and is not supported"
                )

        javascript_adapter = PythonToJavaScriptTargetAdapter()
        try:
            artifacts = javascript_adapter.generate(project, context)
        except JavaScriptUnsupportedPythonSyntax as exc:
            message = str(exc).replace("JavaScript", "TypeScript")
            raise UnsupportedPythonSyntax(message) from None

        self.warnings = [
            "TypeScript output reuses the bounded deterministic Python-to-JavaScript subset and is expected to pass the strict TypeScript compiler.",
            "Type inference is compiler-checked; this is not a full-project migration and does not reconstruct manifests, frameworks, or dependencies.",
        ]
        translated: list[GeneratedArtifact] = []
        for artifact in artifacts:
            relative = PurePosixPath(artifact.relative_path)
            if relative.suffix != ".js":
                raise UnsupportedPythonSyntax("The JavaScript subset returned an unexpected output file type")
            translated.append(GeneratedArtifact(relative.with_suffix(".ts").as_posix(), artifact.content))
        return translated
