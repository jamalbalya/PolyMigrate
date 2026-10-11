"""Deterministic translator for a deliberately small Python-to-Java subset.

Supported: one source file; simple variable assignments; signed 32-bit integer
expressions (+, -, *); string concatenation; boolean literals/variables; and
single-argument print(). Unsupported syntax is rejected rather than guessed.
"""
from __future__ import annotations

import ast
import re

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_JAVA_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "final", "finally", "float", "for", "goto", "if", "implements",
    "import", "instanceof", "int", "interface", "long", "native", "new",
    "package", "private", "protected", "public", "return", "short", "static",
    "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "try", "void", "volatile", "while", "true", "false", "null",
    "_",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported translation subset."""


def _java_string_literal(value: str) -> str:
    pieces = ['"']
    escapes = {
        '"': r'\"', "\\": r"\\", "\n": r"\n", "\r": r"\r",
        "\t": r"\t", "\b": r"\b", "\f": r"\f",
    }
    for char in value:
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise UnsupportedPythonSyntax(
                "Lone Unicode surrogates cannot be represented in Java UTF-8 source"
            )
        if char in escapes:
            pieces.append(escapes[char])
        elif codepoint == 0:
            pieces.append(r"\000")
        elif codepoint < 0x20 or codepoint == 0x7F:
            pieces.append("\\" + format(codepoint, "03o"))
        else:
            pieces.append(char)
    pieces.append('"')
    return "".join(pieces)


class PythonToJavaTargetAdapter:
    """Translate a strict Python expression/assignment subset into Main.java."""

    language_id = "java"

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self._types: dict[str, str] = {}
        self._int_values: dict[str, int] = {}

    @staticmethod
    def _checked_integer_value(node: ast.expr, values: dict[str, int]) -> int:
        minimum, maximum = -(2**31), 2**31 - 1
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif (
            isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and type(node.operand.value) is int and node.operand.value == 2**31
        ):
            value = minimum
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToJavaTargetAdapter._checked_integer_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToJavaTargetAdapter._checked_integer_value(node.left, values)
            right = PythonToJavaTargetAdapter._checked_integer_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        else:
            raise UnsupportedPythonSyntax(
                "Integer expression cannot be proven safe for Java signed int"
            )
        if not minimum <= value <= maximum:
            raise UnsupportedPythonSyntax(
                "Integer literal or arithmetic result exceeds Java's signed int32 range"
            )
        return value

    def _expr(self, node: ast.expr, assigned: set[str]) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return ("true" if node.value else "false"), "bool"
            if type(node.value) is int:
                self._checked_integer_value(node, self._int_values)
                return str(node.value), "int"
            if isinstance(node.value, str):
                return _java_string_literal(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer, string, and boolean literals are supported")

        if isinstance(node, ast.Name):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id):
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not supported in Java")
            if node.id in _JAVA_KEYWORDS or node.id == "print":
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not supported in Java")
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return node.id, self._types[node.id]

        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.right, assigned)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Mixed or unknown operand types are not supported")
            if left_type == "bool":
                raise UnsupportedPythonSyntax("Boolean arithmetic is not supported")
            if left_type == "string" and not isinstance(node.op, ast.Add):
                raise UnsupportedPythonSyntax("Strings support only concatenation with '+'")
            if left_type == "int":
                self._checked_integer_value(node, self._int_values)
            operator = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(node.op)]
            return f"({left} {operator} {right})", left_type

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            if (
                isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant)
                and type(node.operand.value) is int and node.operand.value == 2**31
            ):
                return "-2147483648", "int"
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
            raise ValueError("PythonToJavaTargetAdapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("This adapter currently accepts exactly one source file")

        self.warnings = [
            "Python-to-Java translation supports only assignments, bounded integer expressions, string concatenation, booleans, and one-argument print().",
            "Control flow, functions, imports, classes, I/O beyond print(), and project manifests are not translated.",
            "Generated output must pass build, test, security, dependency, and behavior checks.",
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
        java_types = {"int": "int", "string": "String", "bool": "boolean"}

        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                name = node.targets[0].id
                if name == "print" or name in _JAVA_KEYWORDS or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not supported in Java")
                expression, inferred_type = self._expr(node.value, assigned)
                if name in assigned:
                    if self._types[name] != inferred_type:
                        raise UnsupportedPythonSyntax(f"Changing the type of '{name}' is not supported")
                    statements.append(f"{name} = {expression};")
                else:
                    statements.append(f"{java_types[inferred_type]} {name} = {expression};")
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
                expression, expression_type = self._expr(call.args[0], assigned)
                if expression_type == "bool":
                    statements.append(f'System.out.println(({expression}) ? "True" : "False");')
                else:
                    statements.append(f"System.out.println({expression});")

            elif (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            else:
                raise UnsupportedPythonSyntax(
                    f"Unsupported statement syntax: {type(node).__name__}; Java subset only supports assignments and print()"
                )

        unused_names = sorted(assigned - referenced_names)
        if unused_names:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused_names))

        body = "\n".join(f"        {statement}" for statement in statements)
        content = (
            "public final class Main {\n"
            "    public static void main(String[] args) {\n"
            + (body + "\n" if body else "")
            + "    }\n"
            "}\n"
        )
        return [GeneratedArtifact("Main.java", content)]
