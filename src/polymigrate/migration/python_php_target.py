"""Deterministic translator for a deliberately small Python-to-PHP subset.

Supports simple assignments, integer/string/boolean expressions, and positional
print(). Unsupported syntax is rejected rather than guessed. Integer arithmetic
is restricted to signed 32-bit values for predictable cross-platform behavior.
"""
from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_PHP_INT_MIN = -(2**31)
_PHP_INT_MAX = 2**31 - 1
_PHP_BUILTINS = {"print", "str", "abs"}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported Python-to-PHP subset."""


def _php_string(value: str) -> str:
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise UnsupportedPythonSyntax("PHP string literals containing unsupported control characters are rejected")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class PythonToPHPTargetAdapter:
    """Translate each Python source file into a standalone PHP file."""

    language_id = "php"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    @staticmethod
    def _int_value(node: ast.expr, values: dict[str, int]) -> int:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToPHPTargetAdapter._int_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToPHPTargetAdapter._int_value(node.left, values)
            right = PythonToPHPTargetAdapter._int_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "abs" and len(node.args) == 1 and not node.keywords):
            value = abs(PythonToPHPTargetAdapter._int_value(node.args[0], values))
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for signed 32-bit PHP integers")
        if not _PHP_INT_MIN <= value <= _PHP_INT_MAX:
            raise UnsupportedPythonSyntax("Integer literal or arithmetic result exceeds the signed 32-bit range")
        return value

    def _expr(self, node: ast.expr, assigned: set[str], types: dict[str, str],
              integer_values: dict[str, int], uses_boolean_string: list[bool]) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return ("true" if node.value else "false"), "bool"
            if type(node.value) is int:
                self._int_value(node, integer_values)
                return str(node.value), "int"
            if isinstance(node.value, str):
                return _php_string(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer, string, and boolean literals are supported")
        if isinstance(node, ast.Name):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id):
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not supported")
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return "$" + node.id, types[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str":
            if "str" in assigned:
                raise UnsupportedPythonSyntax("Shadowing the str() builtin is not supported")
            if len(node.args) != 1 or node.keywords:
                raise UnsupportedPythonSyntax("str() must have exactly one positional argument")
            expression, value_type = self._expr(node.args[0], assigned, types, integer_values, uses_boolean_string)
            if value_type == "bool":
                uses_boolean_string[0] = True
                return f"polymigrateString({expression})", "string"
            if value_type in {"int", "string"}:
                return f"(string) ({expression})", "string"
            raise UnsupportedPythonSyntax("str() supports only integer, string, and boolean values")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "abs":
            if "abs" in assigned:
                raise UnsupportedPythonSyntax("Shadowing the abs() builtin is not supported")
            if len(node.args) != 1 or node.keywords:
                raise UnsupportedPythonSyntax("abs() must have exactly one positional argument")
            expression, value_type = self._expr(node.args[0], assigned, types, integer_values, uses_boolean_string)
            if value_type != "int":
                raise UnsupportedPythonSyntax("abs() supports only integer values")
            self._int_value(node, integer_values)
            return f"abs({expression})", "int"
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, left_type = self._expr(node.left, assigned, types, integer_values, uses_boolean_string)
            right, right_type = self._expr(node.right, assigned, types, integer_values, uses_boolean_string)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Mixed or unknown operand types are not supported")
            if left_type == "bool":
                raise UnsupportedPythonSyntax("Boolean arithmetic is not supported")
            if left_type == "string" and not isinstance(node.op, ast.Add):
                raise UnsupportedPythonSyntax("Strings support only concatenation with '+'")
            if left_type == "int":
                self._int_value(node, integer_values)
            operator = "." if left_type == "string" else {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(node.op)]
            return f"({left} {operator} {right})", left_type
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            expression, value_type = self._expr(node.operand, assigned, types, integer_values, uses_boolean_string)
            if value_type != "int":
                raise UnsupportedPythonSyntax("Unary + and - are supported only for integers")
            self._int_value(node, integer_values)
            return ("+" if isinstance(node.op, ast.UAdd) else "-") + expression, "int"
        raise UnsupportedPythonSyntax(f"Unsupported expression syntax: {type(node).__name__}")

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "python":
            raise ValueError("Python-to-PHP adapter requires a Python source project")
        if not project.units:
            raise UnsupportedPythonSyntax("No Python source units were supplied")
        artifacts: list[GeneratedArtifact] = []
        self.warnings = [
            "Deterministic Python-to-PHP translation supports only simple assignments, bounded integer/string/boolean expressions, str(), abs(), and positional print().",
            "Control flow, functions, imports, classes, collections, and project manifest reconstruction are not supported by this deterministic subset.",
        ]
        for unit in project.units:
            try:
                tree = ast.parse(unit.source_text, filename=unit.relative_path)
            except (SyntaxError, ValueError, RecursionError) as exc:
                raise UnsupportedPythonSyntax(f"Cannot parse {unit.relative_path}: {type(exc).__name__}") from None
            assigned: set[str] = set()
            types: dict[str, str] = {}
            integer_values: dict[str, int] = {}
            uses_boolean_string = [False]
            statements: list[str] = []
            referenced = {node.id for node in ast.walk(tree)
                          if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                        raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                    name = node.targets[0].id
                    if name in _PHP_BUILTINS:
                        raise UnsupportedPythonSyntax(f"Variable name '{name}' conflicts with a supported builtin")
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        raise UnsupportedPythonSyntax(f"Variable name '{name}' is not supported")
                    expression, value_type = self._expr(node.value, assigned, types, integer_values, uses_boolean_string)
                    if name in assigned:
                        if types[name] != value_type:
                            raise UnsupportedPythonSyntax(f"Changing the type of '{name}' is not supported")
                        statements.append(f"${name} = {expression};")
                    else:
                        statements.append(f"${name} = {expression};")
                        assigned.add(name)
                    types[name] = value_type
                    if value_type == "int":
                        integer_values[name] = self._int_value(node.value, integer_values)
                    else:
                        integer_values.pop(name, None)
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    call = node.value
                    if not isinstance(call.func, ast.Name) or call.func.id != "print":
                        raise UnsupportedPythonSyntax("Only calls to print() are supported as expression statements")
                    if call.keywords or len(call.args) > 32:
                        raise UnsupportedPythonSyntax("print() supports at most 32 positional arguments and no keywords")
                    expressions = [
                        self._expr(arg, assigned, types, integer_values, uses_boolean_string)
                        for arg in call.args
                    ]
                    values = ", ".join(expression for expression, _ in expressions)
                    if not expressions:
                        statements.append("echo PHP_EOL;")
                    else:
                        if any(value_type == "bool" for _, value_type in expressions):
                            uses_boolean_string[0] = True
                        statements.append(
                            "echo implode(' ', array_map('polymigrateString', [" + values + "])) . PHP_EOL;"
                        )
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    continue
                else:
                    raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")
            unused = sorted(assigned - referenced)
            if unused:
                raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
            helper = (
                "\nfunction polymigrateString($value): string {\n"
                "    if (is_bool($value)) { return $value ? 'True' : 'False'; }\n"
                "    return (string) $value;\n"
                "}\n"
                if uses_boolean_string[0] else ""
            )
            source = "<?php\n" + helper + ("\n" if helper else "") + "\n".join(statements) + "\n"
            relative = PurePosixPath(unit.relative_path)
            output_path = relative.with_suffix(".php").as_posix()
            artifacts.append(GeneratedArtifact(output_path, source))
        return artifacts
