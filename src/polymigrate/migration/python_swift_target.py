"""Deterministic translator for a deliberately small Python-to-Swift subset.

Supports one source file, simple assignments, signed 32-bit integer arithmetic,
string concatenation, booleans, str(), abs(), Unicode-scalar len(), and bounded
positional print(). Unsupported syntax is rejected rather than guessed.
"""
from __future__ import annotations

import ast
import re

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_SWIFT_KEYWORDS = {
    "associatedtype", "class", "deinit", "enum", "extension", "fileprivate",
    "func", "import", "init", "inout", "internal", "let", "open", "operator",
    "private", "protocol", "public", "static", "struct", "subscript", "typealias",
    "var", "break", "case", "continue", "default", "defer", "do", "else",
    "fallthrough", "for", "guard", "if", "in", "repeat", "return", "switch",
    "where", "while", "as", "Any", "catch", "false", "is", "nil", "rethrows",
    "super", "self", "Self", "throw", "throws", "true", "try", "_",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported Python-to-Swift subset."""


def _swift_string_literal(value: str) -> str:
    pieces = ['"']
    escapes = {'"': r'\"', "\\": r"\\", "\n": r"\n", "\r": r"\r", "\t": r"\t"}
    for char in value:
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise UnsupportedPythonSyntax("Lone Unicode surrogates cannot be represented in Swift UTF-8 source")
        if char in escapes:
            pieces.append(escapes[char])
        elif codepoint < 32 or codepoint == 0x7F:
            raise UnsupportedPythonSyntax("Swift strings containing unsupported control characters are rejected")
        else:
            pieces.append(char)
    pieces.append('"')
    return "".join(pieces)


class PythonToSwiftTargetAdapter:
    """Translate a strict assignment/expression/print subset into main.swift."""

    language_id = "swift"

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self._types: dict[str, str] = {}
        self._int_values: dict[str, int] = {}
        self._string_values: dict[str, str] = {}
        self._bool_values: dict[str, bool] = {}

    @staticmethod
    def _checked_int(node: ast.expr, values: dict[str, int]) -> int:
        minimum, maximum = -(2**31), 2**31 - 1
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
              and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
              and node.operand.value == 2**31):
            value = minimum
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToSwiftTargetAdapter._checked_int(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToSwiftTargetAdapter._checked_int(node.left, values)
            right = PythonToSwiftTargetAdapter._checked_int(node.right, values)
            value = left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) else left * right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "abs" and len(node.args) == 1 and not node.keywords):
            value = abs(PythonToSwiftTargetAdapter._checked_int(node.args[0], values))
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for Swift Int32")
        if not minimum <= value <= maximum:
            raise UnsupportedPythonSyntax("Integer literal or arithmetic result exceeds Swift's signed Int32 range")
        return value

    def _expr(self, node: ast.expr, assigned: set[str]) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return ("true" if node.value else "false"), "bool"
            if type(node.value) is int:
                self._checked_int(node, self._int_values)
                return str(node.value), "int"
            if isinstance(node.value, str):
                return _swift_string_literal(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer, string, and boolean literals are supported")

        if isinstance(node, ast.Name):
            if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id)
                    or node.id in _SWIFT_KEYWORDS or node.id in {"print", "abs", "str", "len"}
                    or node.id.startswith("__")):
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not supported in Swift")
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return node.id, self._types[node.id]

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            expression, value_type = self._expr(node.operand, assigned)
            if value_type != "int":
                raise UnsupportedPythonSyntax("Unary + and - are supported only for integers")
            self._checked_int(node, self._int_values)
            return ("+" if isinstance(node.op, ast.UAdd) else "-") + expression, "int"

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.right, assigned)
            if left_type == right_type == "int":
                self._checked_int(node, self._int_values)
                return f"({left} + {right})", "int"
            if left_type == right_type == "string":
                return f"({left} + {right})", "string"
            raise UnsupportedPythonSyntax("Addition requires two integers or two strings in the Swift subset")

        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Sub, ast.Mult)):
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.right, assigned)
            if left_type != "int" or right_type != "int":
                raise UnsupportedPythonSyntax("Swift arithmetic supports only integer operands")
            self._checked_int(node, self._int_values)
            return f"({left} {'-' if isinstance(node.op, ast.Sub) else '*'} {right})", "int"

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name in assigned:
                raise UnsupportedPythonSyntax(f"Shadowing the {name}() builtin is not supported")
            if name == "abs":
                if len(node.args) != 1 or node.keywords:
                    raise UnsupportedPythonSyntax("abs() must have exactly one positional argument")
                expression, value_type = self._expr(node.args[0], assigned)
                if value_type != "int":
                    raise UnsupportedPythonSyntax("abs() supports only integer values")
                self._checked_int(node, self._int_values)
                return f"abs({expression})", "int"
            if name == "str":
                if len(node.args) != 1 or node.keywords:
                    raise UnsupportedPythonSyntax("str() must have exactly one positional argument")
                expression, value_type = self._expr(node.args[0], assigned)
                if value_type == "string":
                    return expression, "string"
                if value_type == "int":
                    return f"String({expression})", "string"
                if value_type == "bool":
                    return f"(({expression}) ? \"True\" : \"False\")", "string"
                raise UnsupportedPythonSyntax("str() supports only integer, string, and boolean values")
            if name == "len":
                if len(node.args) != 1 or node.keywords:
                    raise UnsupportedPythonSyntax("len() must have exactly one positional argument")
                expression, value_type = self._expr(node.args[0], assigned)
                if value_type != "string":
                    raise UnsupportedPythonSyntax("len() supports strings only")
                return f"Int32(({expression}).unicodeScalars.count)", "int"
        raise UnsupportedPythonSyntax(f"Unsupported expression syntax: {type(node).__name__}")

    def _print_call(self, call: ast.Call, assigned: set[str]) -> list[str]:
        if not isinstance(call.func, ast.Name) or call.func.id != "print":
            raise UnsupportedPythonSyntax("Only calls to print() are supported as expression statements")
        if call.keywords or len(call.args) > 32:
            raise UnsupportedPythonSyntax("print() supports at most 32 positional arguments and no keywords")
        if not call.args:
            return ['print("")']
        lines: list[str] = []
        for index, arg in enumerate(call.args):
            expression, value_type = self._expr(arg, assigned)
            if value_type == "bool":
                expression = f"({expression} ? \"True\" : \"False\")"
            lines.append(f"print({expression}, terminator: {'\" \"' if index < len(call.args) - 1 else '\"\"'})")
        lines.append('print("")')
        return lines

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        self.warnings = [
            "Deterministic Python-to-Swift translation supports one file and a strict expression/assignment/print subset only.",
            "Functions, imports, collections, control flow, project dependencies, and full-project migration are unsupported.",
        ]
        if project.language_id != "python":
            raise ValueError("Python-to-Swift target requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("Swift deterministic strategy accepts exactly one Python source file")
        unit = project.units[0]
        if not unit.relative_path.endswith((".py", ".pyi")):
            raise UnsupportedPythonSyntax("Python-to-Swift input must be a Python source file")
        tree = ast.parse(unit.source_text, filename=unit.relative_path)
        assigned: set[str] = set()
        statements: list[str] = []
        swift_types = {"int": "Int32", "string": "String", "bool": "Bool"}
        referenced_names = {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                name = node.targets[0].id
                if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                        or name in _SWIFT_KEYWORDS or name in {"print", "abs", "str", "len"}
                        or name.startswith("__")):
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not supported in Swift")
                expression, inferred_type = self._expr(node.value, assigned)
                if name in assigned:
                    if self._types[name] != inferred_type:
                        raise UnsupportedPythonSyntax(f"Changing the type of '{name}' is not supported")
                    statements.append(f"{name} = {expression}")
                else:
                    statements.append(f"var {name}: {swift_types[inferred_type]} = {expression}")
                    assigned.add(name)
                self._types[name] = inferred_type
                if inferred_type == "int":
                    self._int_values[name] = self._checked_int(node.value, self._int_values)
                elif inferred_type == "string":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        self._string_values[name] = node.value.value
                    elif isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add):
                        left = self._string_values.get(node.value.left.id) if isinstance(node.value.left, ast.Name) else node.value.left.value if isinstance(node.value.left, ast.Constant) and isinstance(node.value.left.value, str) else None
                        right = self._string_values.get(node.value.right.id) if isinstance(node.value.right, ast.Name) else node.value.right.value if isinstance(node.value.right, ast.Constant) and isinstance(node.value.right.value, str) else None
                        if left is not None and right is not None:
                            self._string_values[name] = left + right
                        else:
                            self._string_values.pop(name, None)
                    else:
                        self._string_values.pop(name, None)
                else:
                    if isinstance(node.value, ast.Constant) and type(node.value.value) is bool:
                        self._bool_values[name] = node.value.value
                    else:
                        self._bool_values.pop(name, None)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                statements.extend(self._print_call(node.value, assigned))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}; Swift subset only supports assignments and print()")
        unused = sorted(assigned - referenced_names)
        if unused:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
        self._types = {}
        self._int_values = {}
        self._string_values = {}
        self._bool_values = {}
        content = "\n".join(statements) + "\n"
        return [GeneratedArtifact("main.swift", content)]
