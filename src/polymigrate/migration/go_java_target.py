"""Bounded Go-to-Java adapter composed from checked subset translators."""
from __future__ import annotations
import ast
import hashlib
from polymigrate.migration.go_python_target import GoToPythonTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject, SourceUnit
from polymigrate.migration.python_java_target import PythonToJavaTargetAdapter, UnsupportedPythonSyntax

class GoToJavaTargetAdapter:
    """Translate the checked intersection of the single-file Go/Python/Java subsets."""
    language_id = "java"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "go":
            raise ValueError("Go-to-Java adapter requires a Go source project")
        if len(project.units) != 1 or project.units[0].relative_path != "main.go":
            raise UnsupportedGoSyntax("Deterministic Go-to-Java translation requires exactly one root main.go file")
        intermediate = GoToPythonTargetAdapter().generate(project, context)
        if len(intermediate) != 1:
            raise UnsupportedGoSyntax("Go translation did not produce exactly one intermediate Python artifact")
        try:
            tree = ast.parse(intermediate[0].content)
        except (SyntaxError, RecursionError):
            raise UnsupportedGoSyntax("The Go-to-Python intermediate artifact is not valid Python") from None
        if any(isinstance(n, ast.Constant) and type(n.value) is bool for n in ast.walk(tree)):
            raise UnsupportedGoSyntax("Boolean literals are excluded from deterministic Go-to-Java output because printed casing differs")
        # Normalize only the generated fmt.Println(a, b) shape: print(*[a, b]).
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "print":
                continue
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Starred):
                continue
            expansion = node.args[0].value
            if not isinstance(expansion, ast.ListComp) or len(expansion.generators) != 1:
                raise UnsupportedGoSyntax("Unsupported generated print argument expansion")
            if not isinstance(expansion.generators[0].iter, ast.List):
                raise UnsupportedGoSyntax("Unsupported generated print argument expansion")
            node.args = list(expansion.generators[0].iter.elts)
        normalized = ast.unparse(ast.fix_missing_locations(tree)) + "\n"
        py_project = SourceProject(
            source_root=project.source_root, language_id="python",
            units=(SourceUnit("main.py", normalized, hashlib.sha256(normalized.encode()).hexdigest()),),
            metadata={"composed_from": ("go", "python")},
        )
        try:
            artifacts = PythonToJavaTargetAdapter().generate(py_project, context)
        except UnsupportedPythonSyntax as exc:
            raise UnsupportedGoSyntax(f"Go syntax is outside the composable Go-to-Java subset: {exc}") from None
        self.warnings = [
            "Deterministic Go-to-Java subset: composes the bounded Go-to-Python and Python-to-Java translators; syntax outside their intersection is rejected.",
            "Only one root main.go file is supported; modules, project manifests, dependencies, frameworks, and full-project migration are not supported.",
        ]
        return artifacts
