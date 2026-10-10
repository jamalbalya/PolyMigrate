"""Deterministic translator for a deliberately small Python-to-JavaScript subset.

Supported: integer/string literals, simple assignments, print(expr), + - *,
and unary +/- on integers. Python integers are restricted to JavaScript's safe
integer range. Unsupported syntax is rejected rather than guessed.
"""
from __future__ import annotations

import ast
import json
import re

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_JS_KEYWORDS = {
    "await", "break", "case", "catch", "class", "const", "continue", "debugger",
    "default", "delete", "do", "else", "enum", "export", "extends", "false",
    "finally", "for", "function", "if", "implements", "import", "in", "instanceof",
    "interface", "let", "new", "null", "package", "private", "protected", "public",
    "return", "static", "super", "switch", "this", "throw", "true", "try", "typeof",
    "var", "void", "while", "with", "yield",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported translation subset."""


class PythonToJavaScriptTargetAdapter:
    """Translate a constrained subset of one Python file into standalone JavaScript."""

    language_id = "javascript"

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self._types: dict[str, str] = {}
        self._int_values: dict[str, int] = {}

    @staticmethod
    def _checked_integer_value(node: ast.expr, values: dict[str, int]) -> int:
        limit = 2**53 - 1
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToJavaScriptTargetAdapter._checked_integer_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToJavaScriptTargetAdapter._checked_integer_value(node.left, values)
            right = PythonToJavaScriptTargetAdapter._checked_integer_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for JavaScript Number")
        if not -limit <= value <= limit:
            raise UnsupportedPythonSyntax(
                "Integer literal or arithmetic result exceeds JavaScript's safe integer range"
            )
        return value

    def _expr(self, node: ast.expr, assigned: set[str]) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            if type(node.value) is int:
                self._checked_integer_value(node, self._int_values)
                return str(node.value), "int"
            if isinstance(node.value, str):
                return json.dumps(node.value, ensure_ascii=True), "string"
            raise UnsupportedPythonSyntax("Only integer and string literals are supported")
        if isinstance(node, ast.Name):
            if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", node.id) or node.id in _JS_KEYWORDS:
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not supported in JavaScript")
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return node.id, self._types[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.right, assigned)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Mixed or unknown operand types are not supported")
            if left_type == "string" and not isinstance(node.op, ast.Add):
                raise UnsupportedPythonSyntax("Strings support only concatenation with '+'")
            if left_type == "int":
                self._checked_integer_value(node, self._int_values)
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(node.op)]
            return f"({left} {op} {right})", left_type
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value, value_type = self._expr(node.operand, assigned)
            if value_type != "int":
                raise UnsupportedPythonSyntax("Unary + and - are supported only for integers")
            self._checked_integer_value(node, self._int_values)
            sign = "+" if isinstance(node.op, ast.UAdd) else "-"
            return sign + value, "int"
        raise UnsupportedPythonSyntax(f"Unsupported expression syntax: {type(node).__name__}")

    def generate(self, project: SourceProject, context: dict[str, object]) -> list[GeneratedArtifact]:
        del context
        if project.language_id != "python":
            raise ValueError("PythonToJavaScriptTargetAdapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("This adapter currently accepts exactly one source file")
        self.warnings = [
            "Translation supports only a small documented Python syntax subset.",
            "Generated output must pass build, test, security, and behavior checks.",
        ]
        self._types = {}
        self._int_values = {}
        assigned: set[str] = set()
        statements: list[str] = []
        try:
            tree = ast.parse(project.units[0].source_text)
        except (SyntaxError, RecursionError):
            raise UnsupportedPythonSyntax("Python source contains invalid or excessively nested syntax") from None
        referenced_names = {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                name = node.targets[0].id
                if name == "print":
                    raise UnsupportedPythonSyntax("Variable name 'print' conflicts with the supported print() builtin")
                if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name) or name in _JS_KEYWORDS:
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not supported in JavaScript")
                expr, inferred_type = self._expr(node.value, assigned)
                if name in assigned:
                    if self._types[name] != inferred_type:
                        raise UnsupportedPythonSyntax(f"Changing the type of '{name}' is not supported")
                    statements.append(f"{name} = {expr};")
                else:
                    statements.append(f"let {name} = {expr};")
                    assigned.add(name)
                self._types[name] = inferred_type
                if inferred_type == "int":
                    self._int_values[name] = self._checked_integer_value(node.value, self._int_values)
                else:
                    self._int_values.pop(name, None)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if not isinstance(call.func, ast.Name) or call.func.id != "print":
                    raise UnsupportedPythonSyntax("Only calls to print() are supported as expression statements")
                if len(call.args) != 1 or call.keywords:
                    raise UnsupportedPythonSyntax("print() must have exactly one positional argument")
                expr, _ = self._expr(call.args[0], assigned)
                statements.append(f"console.log({expr});")
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")
        unused_names = sorted(assigned - referenced_names)
        if unused_names:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused_names))
        return [GeneratedArtifact("main.js", "\n".join(statements) + "\n")]
