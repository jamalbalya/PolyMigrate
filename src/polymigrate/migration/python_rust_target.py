"""Deterministic translator for a deliberately small Python-to-Rust subset.

Supports simple assignments, integer expressions (+, -, *), string/integer
literals, unary +/- on integers, and one-argument print(). Unsupported syntax
is rejected. Integer arithmetic is limited to signed i32.
"""
from __future__ import annotations

import ast
import json
import re

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_RUST_KEYWORDS = {
    "as", "async", "await", "break", "const", "continue", "crate", "dyn",
    "else", "enum", "extern", "false", "fn", "for", "if", "impl", "in",
    "let", "loop", "match", "mod", "move", "mut", "pub", "ref", "return",
    "self", "Self", "static", "struct", "super", "trait", "true", "type",
    "unsafe", "use", "where", "while", "abstract", "become", "box", "do",
    "final", "macro", "override", "priv", "typeof", "unsized", "virtual", "yield",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported translation subset."""


class PythonToRustTargetAdapter:
    """Translate a constrained subset of one Python file into a minimal Cargo project."""

    language_id = "rust"

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self._types: dict[str, str] = {}
        self._int_values: dict[str, int] = {}

    @staticmethod
    def _checked_integer_value(node: ast.expr, values: dict[str, int]) -> int:
        minimum, maximum = -(2**31), 2**31 - 1
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
              and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
              and node.operand.value == 2**31):
            value = minimum
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToRustTargetAdapter._checked_integer_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToRustTargetAdapter._checked_integer_value(node.left, values)
            right = PythonToRustTargetAdapter._checked_integer_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for Rust i32")
        if not minimum <= value <= maximum:
            raise UnsupportedPythonSyntax("Integer literal or arithmetic result exceeds the signed Rust i32 range")
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
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id) or node.id in _RUST_KEYWORDS:
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not supported in Rust")
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return node.id, self._types[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.right, assigned)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Mixed or unknown operand types are not supported")
            if left_type != "int":
                raise UnsupportedPythonSyntax("Only integer arithmetic is supported in the Rust subset")
            self._checked_integer_value(node, self._int_values)
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(node.op)]
            return f"({left} {op} {right})", "int"
        if (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
                and node.operand.value == 2**31):
            return "-2147483648", "int"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            if (isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant)
                    and type(node.operand.value) is int and node.operand.value == 0):
                return "0", "int"
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
            raise ValueError("PythonToRustTargetAdapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("This adapter currently accepts exactly one source file")
        self.warnings = [
            "Translation supports only a small documented Python syntax subset.",
            "Generated output must pass build, test, security, and behavior checks.",
        ]
        self._types, self._int_values = {}, {}
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
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in _RUST_KEYWORDS:
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not supported in Rust")
                expr, inferred_type = self._expr(node.value, assigned)
                if name in assigned:
                    if self._types[name] != inferred_type:
                        raise UnsupportedPythonSyntax(f"Changing the type of '{name}' is not supported")
                    statements.append(f"{name} = {expr};")
                else:
                    statements.append(f"let mut {name} = {expr};")
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
                statements.append(f'println!("{{}}", {expr});')
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")
        unused_names = sorted(assigned - referenced_names)
        if unused_names:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused_names))
        cargo = '[package]\nname = "polymigrate_generated"\nversion = "0.1.0"\nedition = "2021"\n'
        source = "fn main() {\n" + "\n".join("    " + statement for statement in statements) + "\n}\n"
        return [
            GeneratedArtifact("Cargo.toml", cargo),
            GeneratedArtifact("src/main.rs", source),
        ]
