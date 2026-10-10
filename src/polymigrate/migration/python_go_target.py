"""Deterministic translator for a deliberately small Python-to-Go subset.

Supported:
- Integer and string literals
- Simple variable assignments
- print(expr) with exactly one positional argument
- Binary +, -, and * expressions
- Unary + and - on integers

Unsupported syntax is rejected rather than translated speculatively.
Source code is parsed, never executed.
"""
from __future__ import annotations

import ast
import json
import re

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject


_GO_KEYWORDS = {
    "break", "default", "func", "interface", "select", "case", "defer",
    "go", "map", "struct", "chan", "else", "goto", "package", "switch",
    "const", "fallthrough", "if", "range", "type", "continue", "for",
    "import", "return", "var",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported translation subset."""


class PythonToGoTargetAdapter:
    """Translate a constrained subset of Python into one standalone Go program."""

    language_id = "go"

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self._types: dict[str, str] = {}
        self._int_values: dict[str, int] = {}

    @staticmethod
    def _checked_integer_value(node: ast.expr, values: dict[str, int]) -> int:
        """Evaluate integer-only expressions within portable Go int32 bounds."""
        minimum = -(2**31)
        maximum = 2**31 - 1

        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and type(node.operand.value) is int
            and node.operand.value == 2**31
        ):
            # Python parses -2147483648 as unary minus applied to 2147483648.
            # Accept this one magnitude because the signed result is int32-safe.
            value = -(2**31)
        elif isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.UAdd, ast.USub)
        ):
            operand = PythonToGoTargetAdapter._checked_integer_value(
                node.operand, values
            )
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult)
        ):
            left = PythonToGoTargetAdapter._checked_integer_value(
                node.left, values
            )
            right = PythonToGoTargetAdapter._checked_integer_value(
                node.right, values
            )
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        else:
            raise UnsupportedPythonSyntax(
                "Integer expression cannot be proven safe for portable Go int"
            )

        if not minimum <= value <= maximum:
            raise UnsupportedPythonSyntax(
                "Integer literal or arithmetic result exceeds the portable "
                "Go int32 range; translation rejected to avoid behavior changes"
            )
        return value

    def _expr(self, node: ast.expr, assigned: set[str]) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or node.value is None:
                raise UnsupportedPythonSyntax(
                    "Boolean and None literals are not supported"
                )
            if isinstance(node.value, int):
                self._checked_integer_value(node, self._int_values)
                return str(node.value), "int"
            if isinstance(node.value, str):
                return json.dumps(node.value, ensure_ascii=False), "string"
            raise UnsupportedPythonSyntax(
                "Only integer and string literals are supported"
            )

        if isinstance(node, ast.Name):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id):
                raise UnsupportedPythonSyntax("Invalid variable name")
            if node.id in _GO_KEYWORDS:
                raise UnsupportedPythonSyntax(
                    f"Variable name '{node.id}' is a Go keyword"
                )
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(
                    f"Variable '{node.id}' is used before assignment"
                )
            return node.id, self._types[node.id]

        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult)
        ):
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.right, assigned)
            if left_type != right_type:
                raise UnsupportedPythonSyntax(
                    "Mixed or unknown operand types are not supported"
                )
            if left_type == "string" and not isinstance(node.op, ast.Add):
                raise UnsupportedPythonSyntax(
                    "Strings support only concatenation with '+'"
                )
            if left_type == "int":
                self._checked_integer_value(node, self._int_values)
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(node.op)]
            return f"({left} {op} {right})", left_type

        if isinstance(node, ast.UnaryOp,):
            if (
                isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant)
                and type(node.operand.value) is int
                and node.operand.value == 2**31
            ):
                return "-2147483648", "int"
            if isinstance(node.op, (ast.UAdd, ast.USub)):
                value, value_type = self._expr(node.operand, assigned)
                if value_type != "int":
                    raise UnsupportedPythonSyntax(
                        "Unary + and - are supported only for integers"
                    )
                self._checked_integer_value(node, self._int_values)
                sign = "+" if isinstance(node.op, ast.UAdd) else "-"
                return sign + value, "int"

        raise UnsupportedPythonSyntax(
            f"Unsupported expression syntax: {type(node).__name__}"
        )

    def generate(
        self, project: SourceProject, context: dict[str, object]
    ) -> list[GeneratedArtifact]:
        del context
        if project.language_id != "python":
            raise ValueError(
                "PythonToGoTargetAdapter requires a Python source project"
            )
        if not project.units:
            raise ValueError("Python source project contains no source units")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax(
                "This adapter currently accepts exactly one source file"
            )

        self.warnings = [
            "Translation supports only a small documented Python syntax subset.",
            "Generated output must pass build, test, security, and behavior checks.",
        ]
        assigned: set[str] = set()
        self._types = {}
        self._int_values = {}
        statements: list[str] = []
        used_fmt = False

        try:
            tree = ast.parse(project.units[0].source_text)
        except (SyntaxError, RecursionError):
            raise UnsupportedPythonSyntax(
                "Python source contains invalid or excessively nested syntax"
            ) from None

        referenced_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }

        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(
                    node.targets[0], ast.Name
                ):
                    raise UnsupportedPythonSyntax(
                        "Only assignments to one simple variable are supported"
                    )
                name = node.targets[0].id
                if name == "print":
                    raise UnsupportedPythonSyntax(
                        "Variable name 'print' conflicts with the supported print() builtin"
                    )
                if name == "_":
                    raise UnsupportedPythonSyntax(
                        "The Python '_' placeholder is not supported; "
                        "use a named variable"
                    )
                if (
                    not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                    or name in _GO_KEYWORDS
                ):
                    raise UnsupportedPythonSyntax(
                        f"Variable name '{name}' is not supported in Go"
                    )

                expr, inferred_type = self._expr(node.value, assigned)
                if name in assigned:
                    if self._types[name] != inferred_type:
                        raise UnsupportedPythonSyntax(
                            f"Changing the type of '{name}' is not supported"
                        )
                    statements.append(f"{name} = {expr}")
                else:
                    statements.append(f"{name} := {expr}")
                    assigned.add(name)
                self._types[name] = inferred_type
                if inferred_type == "int":
                    self._int_values[name] = self._checked_integer_value(
                        node.value, self._int_values
                    )
                else:
                    self._int_values.pop(name, None)

            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if not isinstance(call.func, ast.Name) or call.func.id != "print":
                    raise UnsupportedPythonSyntax(
                        "Only calls to print() are supported as expression statements"
                    )
                if len(call.args) != 1 or call.keywords:
                    raise UnsupportedPythonSyntax(
                        "print() must have exactly one positional argument"
                    )
                expr, _ = self._expr(call.args[0], assigned)
                statements.append(f"fmt.Println({expr})")
                used_fmt = True

            elif (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            else:
                raise UnsupportedPythonSyntax(
                    f"Unsupported statement syntax: {type(node).__name__}"
                )

        if used_fmt and "fmt" in assigned:
            raise UnsupportedPythonSyntax(
                "Variable name 'fmt' conflicts with the Go fmt import used by print()"
            )

        unused_names = sorted(assigned - referenced_names)
        if unused_names:
            raise UnsupportedPythonSyntax(
                "Assigned variable(s) are never used: " + ", ".join(unused_names)
            )

        imports = 'import "fmt"\n' if used_fmt else ""
        body = "\n".join(f"\t{statement}" for statement in statements)
        content = f"package main\n\n{imports}\nfunc main() {{\n{body}\n}}\n"
        return [GeneratedArtifact("main.go", content)]
