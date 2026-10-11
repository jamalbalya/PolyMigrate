"""Deterministic translator for a deliberately small Python-to-C# subset."""
from __future__ import annotations

import ast
import json
import re
from pathlib import PurePosixPath

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_CSHARP_INT_MIN = -(2**31)
_CSHARP_INT_MAX = 2**31 - 1
_CSHARP_BUILTINS = {
    "print", "str", "abs", "range", "PolymigrateString", "Console", "Math",
    "CultureInfo", "System", "String",
}
_CSHARP_RESERVED = {
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch", "char",
    "checked", "class", "const", "continue", "decimal", "default", "delegate",
    "do", "double", "else", "enum", "event", "explicit", "extern", "false",
    "finally", "fixed", "float", "for", "foreach", "goto", "if", "implicit",
    "in", "int", "interface", "internal", "is", "lock", "long", "namespace",
    "new", "null", "object", "operator", "out", "override", "params", "private",
    "protected", "public", "readonly", "ref", "return", "sbyte", "sealed",
    "short", "sizeof", "stackalloc", "static", "string", "struct", "switch",
    "this", "throw", "true", "try", "typeof", "uint", "ulong", "unchecked",
    "unsafe", "ushort", "using", "virtual", "void", "volatile", "while",
    "var", "async", "await", "record", "required", "file", "global", "init",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported Python-to-C# subset."""


def _csharp_string(value: str) -> str:
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise UnsupportedPythonSyntax("C# string literals containing unsupported control characters are rejected")
    return json.dumps(value, ensure_ascii=False)


class PythonToCSharpTargetAdapter:
    """Translate a single Python source file into a standalone .NET console project."""

    language_id = "csharp"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    @staticmethod
    def _int_value(node: ast.expr, values: dict[str, int]) -> int:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToCSharpTargetAdapter._int_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToCSharpTargetAdapter._int_value(node.left, values)
            right = PythonToCSharpTargetAdapter._int_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "abs" and len(node.args) == 1 and not node.keywords):
            value = abs(PythonToCSharpTargetAdapter._int_value(node.args[0], values))
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for signed 32-bit C# integers")
        if not _CSHARP_INT_MIN <= value <= _CSHARP_INT_MAX:
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
                return _csharp_string(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer, string, and boolean literals are supported")
        if isinstance(node, ast.Name):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id) or node.id in _CSHARP_RESERVED:
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not a supported C# local variable")
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
                return f"PolymigrateString({expression})", "string"
            if value_type == "int":
                return f"({expression}).ToString(CultureInfo.InvariantCulture)", "string"
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
            return f"Math.Abs({expression})", "int"
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
            raise ValueError("Python-to-C# adapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("Deterministic Python-to-C# translation currently requires exactly one Python source file")
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
        declarations = {"int": "int", "string": "string", "bool": "bool"}

        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                name = node.targets[0].id
                if name in _CSHARP_BUILTINS:
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' conflicts with a supported builtin")
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in _CSHARP_RESERVED:
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not a supported C# local variable")
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
                    statements.append("Console.WriteLine();")
                else:
                    uses_boolean_string[0] = True
                    values = ", ".join(f"PolymigrateString({expression})" for expression, _ in expressions)
                    statements.append(f"Console.WriteLine(string.Join(\" \", new string[] {{ {values} }}));")
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")

        unused = sorted(assigned - referenced)
        if unused:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
        helper = (
            "    private static string PolymigrateString(bool value) => value ? \"True\" : \"False\";\n"
            "    private static string PolymigrateString(string value) => value;\n"
            "    private static string PolymigrateString(int value) => value.ToString(CultureInfo.InvariantCulture);\n"
            if uses_boolean_string[0] else ""
        )
        body = "\n".join("        " + statement for statement in statements)
        source = (
            "using System;\nusing System.Globalization;\n\n"
            "internal static class Program\n{\n"
            + helper
            + "    private static int Main()\n    {\n"
            + body + ("\n" if body else "")
            + "        return 0;\n    }\n}\n"
        )
        project_file = (
            "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
            "  <PropertyGroup>\n"
            "    <OutputType>Exe</OutputType>\n"
            "    <TargetFramework>net8.0</TargetFramework>\n"
            "    <ImplicitUsings>disable</ImplicitUsings>\n"
            "    <Nullable>disable</Nullable>\n    <TreatWarningsAsErrors>true</TreatWarningsAsErrors>\n"
            "  </PropertyGroup>\n"
            "</Project>\n"
        )
        return [
            GeneratedArtifact(PurePosixPath(unit.relative_path).with_suffix(".cs").as_posix(), source),
            GeneratedArtifact("PolyMigrate.csproj", project_file),
        ]
