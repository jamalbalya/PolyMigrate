"""Deterministic translator for a deliberately small Python-to-C11 subset."""
from __future__ import annotations

import ast
import json
import re
from pathlib import PurePosixPath

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1
_BUILTINS = {"print", "abs", "printf", "main"}
_RESERVED = {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if",
    "inline", "int", "long", "register", "restrict", "return", "short",
    "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
    "unsigned", "void", "volatile", "while", "_Alignas", "_Alignof",
    "_Atomic", "_Bool", "_Complex", "_Generic", "_Imaginary", "_Noreturn",
    "_Static_assert", "_Thread_local", "bool", "true", "false", "NULL",
    "stdin", "stdout", "stderr", "EOF", "INT32_MIN", "INT32_MAX",
    "PRId32", "size_t", "int32_t",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported Python-to-C subset."""


def _c_string(value: str) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise UnsupportedPythonSyntax("C string literals containing lone Unicode surrogates are rejected")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise UnsupportedPythonSyntax("C string literals containing unsupported control characters are rejected")
    return json.dumps(value, ensure_ascii=False)


class PythonToCTargetAdapter:
    """Translate one Python file into a small standalone C11 program."""

    language_id = "c"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    @staticmethod
    def _int_value(node: ast.expr, values: dict[str, int]) -> int:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToCTargetAdapter._int_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToCTargetAdapter._int_value(node.left, values)
            right = PythonToCTargetAdapter._int_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "abs" and len(node.args) == 1 and not node.keywords):
            value = abs(PythonToCTargetAdapter._int_value(node.args[0], values))
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for signed 32-bit C integers")
        if not _INT_MIN <= value <= _INT_MAX:
            raise UnsupportedPythonSyntax("Integer literal or arithmetic result exceeds the signed 32-bit C range")
        return value

    def _expr(self, node: ast.expr, assigned: set[str], types: dict[str, str],
              integer_values: dict[str, int]) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return ("true" if node.value else "false"), "bool"
            if type(node.value) is int:
                self._int_value(node, integer_values)
                return str(node.value), "int"
            if isinstance(node.value, str):
                return _c_string(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer, string, and boolean literals are supported")
        if isinstance(node, ast.Name):
            if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id)
                    or node.id in _RESERVED or node.id in _BUILTINS
                    or node.id.startswith("__")
                    or (node.id.startswith("_") and len(node.id) > 1 and node.id[1].isupper())):
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not a supported C identifier")
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return node.id, types[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            expression, value_type = self._expr(node.operand, assigned, types, integer_values)
            if value_type != "int":
                raise UnsupportedPythonSyntax("Unary + and - are supported only for integers")
            self._int_value(node, integer_values)
            return ("+" if isinstance(node.op, ast.UAdd) else "-") + expression, "int"
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, left_type = self._expr(node.left, assigned, types, integer_values)
            right, right_type = self._expr(node.right, assigned, types, integer_values)
            if left_type != "int" or right_type != "int":
                raise UnsupportedPythonSyntax("C arithmetic supports only integers; strings and booleans cannot be operands")
            self._int_value(node, integer_values)
            operator = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(node.op)]
            return f"({left} {operator} {right})", "int"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "abs":
            if "abs" in assigned:
                raise UnsupportedPythonSyntax("Shadowing the abs() builtin is not supported")
            if len(node.args) != 1 or node.keywords:
                raise UnsupportedPythonSyntax("abs() must have exactly one positional argument")
            expression, value_type = self._expr(node.args[0], assigned, types, integer_values)
            if value_type != "int":
                raise UnsupportedPythonSyntax("abs() supports only integer values")
            self._int_value(node, integer_values)
            return f"abs((int)({expression}))", "int"
        raise UnsupportedPythonSyntax(f"Unsupported expression syntax: {type(node).__name__}")

    def _print(self, call: ast.Call, assigned: set[str], types: dict[str, str],
               integer_values: dict[str, int]) -> list[str]:
        if not isinstance(call.func, ast.Name) or call.func.id != "print":
            raise UnsupportedPythonSyntax("Only calls to print() are supported as expression statements")
        if call.keywords or len(call.args) > 32:
            raise UnsupportedPythonSyntax("print() supports at most 32 positional arguments and no keywords")
        expressions = [
            self._expr(argument, assigned, types, integer_values) for argument in call.args
        ]
        lines: list[str] = []
        for index, (expression, value_type) in enumerate(expressions):
            if index:
                lines.append('printf(" ");')
            if value_type == "int":
                lines.append(f'printf("%" PRId32, (int32_t)({expression}));')
            elif value_type == "bool":
                lines.append(f'printf("%s", ({expression}) ? "True" : "False");')
            else:
                lines.append(f'printf("%s", {expression});')
        lines.append('printf("\\n");')
        return lines

    def _condition(self, node: ast.expr, assigned: set[str], types: dict[str, str],
                   integer_values: dict[str, int]) -> str:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return "(!(" + self._condition(node.operand, assigned, types, integer_values) + "))"
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            operator = " && " if isinstance(node.op, ast.And) else " || "
            return "(" + operator.join(
                self._condition(item, assigned, types, integer_values) for item in node.values
            ) + ")"
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise UnsupportedPythonSyntax("Chained comparisons are not supported in C conditions")
            left, left_type = self._expr(node.left, assigned, types, integer_values)
            right, right_type = self._expr(node.comparators[0], assigned, types, integer_values)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("C comparisons require operands of the same inferred type")
            operator_node = node.ops[0]
            operators = {
                ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<",
                ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            }
            operator = operators.get(type(operator_node))
            if operator is None:
                raise UnsupportedPythonSyntax("Only simple equality and ordering comparisons are supported")
            if left_type == "string":
                if not isinstance(operator_node, (ast.Eq, ast.NotEq)):
                    raise UnsupportedPythonSyntax("String ordering comparisons are not supported in C")
                comparison = f"(strcmp({left}, {right}) {operator} 0)"
                return comparison
            if left_type == "bool" and not isinstance(operator_node, (ast.Eq, ast.NotEq)):
                raise UnsupportedPythonSyntax("Boolean ordering comparisons are not supported in C")
            return f"({left} {operator} {right})"
        expression, value_type = self._expr(node, assigned, types, integer_values)
        if value_type == "bool":
            return expression
        if value_type == "int":
            return f"(({expression}) != 0)"
        if value_type == "string":
            return f"(({expression})[0] != 0)"
        raise UnsupportedPythonSyntax("Condition type is not supported in C")

    def _if_statement(self, node: ast.If, assigned: set[str], types: dict[str, str],
                      integer_values: dict[str, int], *, depth: int = 1,
                      keyword: str = "if", close_end: bool = True) -> list[str]:
        if depth > 20:
            raise UnsupportedPythonSyntax("if/elif chains are limited to 20 branches in C")
        condition = self._condition(node.test, assigned, types, integer_values)
        rendered = [f"{keyword} ({condition}) {{"]
        for statement in node.body:
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                rendered.extend("    " + line for line in self._print(
                    statement.value, assigned, types, integer_values
                ))
            elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                  and isinstance(statement.value.value, str)):
                continue
            else:
                raise UnsupportedPythonSyntax("C conditional bodies may contain only print() calls")
        if len(rendered) == 1:
            raise UnsupportedPythonSyntax("Empty conditional bodies are not supported in C")
        if node.orelse:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                rendered.extend(self._if_statement(
                    node.orelse[0], assigned, types, integer_values,
                    depth=depth + 1, keyword="} else if", close_end=False,
                ))
            else:
                rendered.append("} else {")
                for statement in node.orelse:
                    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                        rendered.extend("    " + line for line in self._print(
                            statement.value, assigned, types, integer_values
                        ))
                    elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                          and isinstance(statement.value.value, str)):
                        continue
                    else:
                        raise UnsupportedPythonSyntax("C conditional bodies may contain only print() calls")
                if rendered[-1] == "} else {":
                    raise UnsupportedPythonSyntax("Empty conditional bodies are not supported in C")
        if close_end:
            rendered.append("}")
        return rendered

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        del context
        if project.language_id != "python":
            raise ValueError("PythonToCTargetAdapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("This adapter currently accepts exactly one Python source file")
        unit = project.units[0]
        try:
            tree = ast.parse(unit.source_text, filename=unit.relative_path)
        except (SyntaxError, ValueError, RecursionError) as exc:
            raise UnsupportedPythonSyntax(f"Cannot parse {unit.relative_path}: {type(exc).__name__}") from None
        assigned: set[str] = set()
        types: dict[str, str] = {}
        integer_values: dict[str, int] = {}
        statements: list[str] = []
        referenced = {
            item.id for item in ast.walk(tree)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
        }
        declarations = {"int": "int32_t", "string": "const char *", "bool": "bool"}
        uses_abs = any(
            isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "abs"
            for item in ast.walk(tree)
        )
        self.warnings = [
            "Deterministic Python-to-C supports one file, signed 32-bit integer arithmetic, simple string and boolean values, abs(), positional print(), and print-only if/elif/else chains with bounded scalar conditions.",
            "Loops, conditional assignments, string concatenation, str(), imports, functions, classes, collections, and full-project migration are not supported by this subset.",
        ]
        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                name = node.targets[0].id
                if name in _BUILTINS:
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' conflicts with a supported C builtin")
                if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                        or name in _RESERVED or name.startswith("__")
                        or (name.startswith("_") and len(name) > 1 and name[1].isupper())):
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not a supported C identifier")
                expression, value_type = self._expr(node.value, assigned, types, integer_values)
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
                statements.extend(self._print(node.value, assigned, types, integer_values))
            elif isinstance(node, ast.If):
                statements.extend(self._if_statement(node, assigned, types, integer_values))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")

        unused = sorted(assigned - referenced)
        if unused:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
        includes = "#include <inttypes.h>\n#include <stdbool.h>\n#include <stdint.h>\n#include <stdio.h>\n#include <string.h>\n"
        if uses_abs:
            includes += "#include <stdlib.h>\n"
        body = "\n".join("    " + statement for statement in statements)
        source = includes + "\nint main(void) {\n" + body + ("\n" if body else "") + "    return 0;\n}\n"
        return [GeneratedArtifact(PurePosixPath(unit.relative_path).with_suffix(".c").as_posix(), source)]
