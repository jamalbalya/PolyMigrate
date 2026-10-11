"""Deterministic translator for a deliberately small Python-to-C++ subset."""
from __future__ import annotations

import ast
import json
import re
from pathlib import PurePosixPath

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_CPP_INT_MIN = -(2**31)
_CPP_INT_MAX = 2**31 - 1
_CPP_BUILTINS = {"print", "str", "abs", "range", "polymigrate_string", "std"}
_CPP_RESERVED = {
    "NULL", "EOF", "INT32_MAX", "INT32_MIN", "UINT32_MAX", "UINT32_MIN", "INT64_MAX", "INT64_MIN", "UINT64_MAX", "UINT64_MIN", "EXIT_SUCCESS", "EXIT_FAILURE",
    "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand", "bitor",
    "bool", "break", "case", "catch", "char", "char8_t", "char16_t", "char32_t",
    "class", "compl", "concept", "const", "consteval", "constexpr", "constinit",
    "const_cast", "continue", "co_await", "co_return", "co_yield", "decltype",
    "default", "delete", "do", "double", "dynamic_cast", "else", "enum",
    "explicit", "export", "extern", "false", "float", "for", "friend", "goto",
    "if", "inline", "int", "long", "mutable", "namespace", "new", "noexcept",
    "not", "not_eq", "nullptr", "operator", "or", "or_eq", "private", "protected",
    "public", "register", "reinterpret_cast", "requires", "return", "short",
    "signed", "sizeof", "static", "static_assert", "static_cast", "struct",
    "switch", "template", "this", "thread_local", "throw", "true", "try",
    "typedef", "typeid", "typename", "union", "unsigned", "using", "virtual",
    "void", "volatile", "wchar_t", "while", "xor", "xor_eq",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported Python-to-C++ subset."""


def _cpp_string(value: str) -> str:
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise UnsupportedPythonSyntax("C++ string literals containing unsupported control characters are rejected")
    return "std::string(" + json.dumps(value, ensure_ascii=False) + ")"


class PythonToCppTargetAdapter:
    """Translate a single Python source file into a standalone C++17 program."""

    language_id = "cpp"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    @staticmethod
    def _int_value(node: ast.expr, values: dict[str, int]) -> int:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToCppTargetAdapter._int_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToCppTargetAdapter._int_value(node.left, values)
            right = PythonToCppTargetAdapter._int_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "abs" and len(node.args) == 1 and not node.keywords):
            value = abs(PythonToCppTargetAdapter._int_value(node.args[0], values))
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for signed 32-bit C++ integers")
        if not _CPP_INT_MIN <= value <= _CPP_INT_MAX:
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
                return _cpp_string(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer, string, and boolean literals are supported")
        if isinstance(node, ast.Name):
            if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id) or node.id in _CPP_RESERVED
                    or node.id.startswith("__") or (node.id.startswith("_") and len(node.id) > 1 and node.id[1].isupper())):
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not a supported C++ identifier")
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return node.id, types[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str":
            if "str" in assigned:
                raise UnsupportedPythonSyntax("Shadowing the str() builtin is not supported")
            if len(node.args) != 1 or node.keywords:
                raise UnsupportedPythonSyntax("str() must have exactly one positional argument")
            expression, value_type = self._expr(node.args[0], assigned, types, integer_values, uses_boolean_string)
            if value_type == "bool":
                uses_boolean_string[0] = True
                return f"polymigrate_string({expression})", "string"
            if value_type == "int":
                return f"std::to_string({expression})", "string"
            if value_type == "string":
                return expression, "string"
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
            return f"std::abs({expression})", "int"
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
            operator = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(node.op)]
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
            raise ValueError("Python-to-C++ adapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("Deterministic Python-to-C++ translation currently requires exactly one Python source file")
        unit = project.units[0]
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
        declarations = {"int": "std::int32_t", "string": "std::string", "bool": "bool"}

        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                name = node.targets[0].id
                if name in _CPP_BUILTINS:
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' conflicts with a supported builtin")
                if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in _CPP_RESERVED
                        or name.startswith("__") or (name.startswith("_") and len(name) > 1 and name[1].isupper())):
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not a supported C++ identifier")
                expression, value_type = self._expr(node.value, assigned, types, integer_values, uses_boolean_string)
                if name in assigned:
                    if types[name] != value_type:
                        raise UnsupportedPythonSyntax(f"Changing the type of '{name}' is not supported")
                    statements.append(f"{name} = {expression};")
                else:
                    statements.append(f"{declarations[value_type]} {name} = {expression};")
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
                if not expressions:
                    statements.append("std::cout << '\\n';")
                else:
                    uses_boolean_string[0] = True
                    output = []
                    for index, (expression, _) in enumerate(expressions):
                        if index:
                            output.append('std::cout << " ";')
                        output.append(f"std::cout << polymigrate_string({expression});")
                    output.append("std::cout << '\\n';")
                    statements.extend(output)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")

        unused = sorted(assigned - referenced)
        if unused:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
        helper = (
            "std::string polymigrate_string(bool value) { return value ? \"True\" : \"False\"; }\n"
            "std::string polymigrate_string(const std::string& value) { return value; }\n"
            "std::string polymigrate_string(std::int32_t value) { return std::to_string(value); }\n"
            if uses_boolean_string[0] else ""
        )
        body = "\n".join("    " + statement for statement in statements)
        source = (
            "#include <cstdint>\n#include <cstdlib>\n#include <iostream>\n#include <string>\n\n"
            + helper + ("\n" if helper else "")
            + "int main() {\n" + body + ("\n" if body else "")
            + "    return 0;\n}\n"
        )
        return [GeneratedArtifact(PurePosixPath(unit.relative_path).with_suffix(".cpp").as_posix(), source)]
