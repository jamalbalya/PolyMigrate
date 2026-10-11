"""Deterministic Python-to-Kotlin translator for a bounded single-file subset."""
from __future__ import annotations

import ast
import json
import re
from pathlib import PurePosixPath

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1
_KOTLIN_RESERVED = {
    "as", "break", "class", "continue", "do", "else", "false", "for", "fun",
    "if", "in", "interface", "is", "null", "object", "package", "return",
    "super", "this", "throw", "true", "try", "typealias", "typeof", "val",
    "var", "when", "while", "by", "catch", "constructor", "delegate", "dynamic",
    "field", "file", "finally", "get", "import", "init", "param", "property",
    "receiver", "set", "setparam", "where", "actual", "abstract", "annotation",
    "companion", "const", "crossinline", "data", "enum", "external", "final",
    "infix", "inline", "inner", "internal", "lateinit", "noinline", "open",
    "operator", "out", "override", "private", "protected", "public", "reified",
    "sealed", "suspend", "tailrec", "vararg",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when a Python construct is outside the supported Kotlin subset."""


def _kotlin_string(value: str) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise UnsupportedPythonSyntax("Kotlin string literals containing lone Unicode surrogates are rejected")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise UnsupportedPythonSyntax("Kotlin string literals containing unsupported control characters are rejected")
    return json.dumps(value, ensure_ascii=False).replace("$", r"\$")


class PythonToKotlinTargetAdapter:
    """Translate one Python file into a minimal Kotlin/JVM console program."""

    language_id = "kotlin"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def _int_value(self, node: ast.expr, integer_values: dict[str, int]) -> int:
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            value = node.value
        elif isinstance(node, ast.Name) and node.id in integer_values:
            value = integer_values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            operand = self._int_value(node.operand, integer_values)
            value = -operand if isinstance(node.op, ast.USub) else operand
        elif isinstance(node, ast.BinOp):
            left = self._int_value(node.left, integer_values)
            right = self._int_value(node.right, integer_values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.FloorDiv):
                if right == 0:
                    raise UnsupportedPythonSyntax("Integer division by zero is not supported")
                value = left // right
            elif isinstance(node.op, ast.Mod):
                if right == 0:
                    raise UnsupportedPythonSyntax("Integer modulo by zero is not supported")
                value = left % right
            else:
                raise UnsupportedPythonSyntax("Only bounded integer arithmetic is supported")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "abs":
            if len(node.args) != 1 or node.keywords:
                raise UnsupportedPythonSyntax("abs() supports exactly one positional argument")
            value = abs(self._int_value(node.args[0], integer_values))
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe in the Kotlin subset")
        if not _INT_MIN <= value <= _INT_MAX:
            raise UnsupportedPythonSyntax("Integer expression exceeds the signed 32-bit Kotlin Int range")
        return value

    def _expr(self, node: ast.expr, assigned: set[str], types: dict[str, str],
              integer_values: dict[str, int]) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return ("true" if node.value else "false"), "bool"
            if isinstance(node.value, int):
                if not _INT_MIN <= node.value <= _INT_MAX:
                    raise UnsupportedPythonSyntax("Integer literal exceeds the signed 32-bit Kotlin Int range")
                return str(node.value), "int"
            if isinstance(node.value, str):
                return _kotlin_string(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer, string, and boolean literals are supported")
        if isinstance(node, ast.Name):
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return node.id, types[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            expression, value_type = self._expr(node.operand, assigned, types, integer_values)
            if value_type != "int":
                raise UnsupportedPythonSyntax("Unary numeric operators require an integer")
            self._int_value(node, integer_values)
            return ("-" if isinstance(node.op, ast.USub) else "+") + expression, "int"
        if isinstance(node, ast.BinOp):
            left, left_type = self._expr(node.left, assigned, types, integer_values)
            right, right_type = self._expr(node.right, assigned, types, integer_values)
            if isinstance(node.op, ast.Add) and left_type == right_type == "string":
                return f"({left} + {right})", "string"
            if left_type != "int" or right_type != "int":
                raise UnsupportedPythonSyntax("Kotlin arithmetic supports only integers, except string concatenation with +")
            self._int_value(node, integer_values)
            operators = {
                ast.Add: "+", ast.Sub: "-", ast.Mult: "*",
                ast.FloorDiv: "Math.floorDiv", ast.Mod: "Math.floorMod",
            }
            operator = operators.get(type(node.op))
            if operator is None:
                raise UnsupportedPythonSyntax("Only +, -, *, //, and % are supported for integer expressions")
            if operator in {"Math.floorDiv", "Math.floorMod"}:
                return f"{operator}({left}, {right})", "int"
            return f"({left} {operator} {right})", "int"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if node.keywords or len(node.args) != 1:
                raise UnsupportedPythonSyntax(f"{name}() supports exactly one positional argument")
            if name == "str":
                expression, _ = self._expr(node.args[0], assigned, types, integer_values)
                return f"pyString({expression})", "string"
            if name == "abs":
                expression, value_type = self._expr(node.args[0], assigned, types, integer_values)
                if value_type != "int":
                    raise UnsupportedPythonSyntax("abs() supports integer values only")
                self._int_value(node, integer_values)
                return f"kotlin.math.abs({expression})", "int"
        raise UnsupportedPythonSyntax(f"Unsupported expression syntax: {type(node).__name__}")

    def _condition(self, node: ast.expr, assigned: set[str], types: dict[str, str],
                   integer_values: dict[str, int]) -> str:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return "!(" + self._condition(node.operand, assigned, types, integer_values) + ")"
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            operator = "&&" if isinstance(node.op, ast.And) else "||"
            return "(" + f" {operator} ".join(
                self._condition(item, assigned, types, integer_values) for item in node.values
            ) + ")"
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise UnsupportedPythonSyntax("Chained comparisons are not supported in Kotlin conditions")
            left, left_type = self._expr(node.left, assigned, types, integer_values)
            right, right_type = self._expr(node.comparators[0], assigned, types, integer_values)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Kotlin comparisons require operands of the same known type")
            operators = {
                ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<",
                ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            }
            operator = operators.get(type(node.ops[0]))
            if operator is None:
                raise UnsupportedPythonSyntax("Only ==, !=, <, <=, >, and >= comparisons are supported")
            if left_type == "string" and operator not in {"==", "!="}:
                raise UnsupportedPythonSyntax("String ordering comparisons are not supported")
            if left_type == "bool" and operator not in {"==", "!="}:
                raise UnsupportedPythonSyntax("Boolean ordering comparisons are not supported")
            return f"({left} {operator} {right})"
        expression, value_type = self._expr(node, assigned, types, integer_values)
        if value_type == "bool":
            return expression
        if value_type == "int":
            return f"({expression} != 0)"
        if value_type == "string":
            return f"({expression}.isNotEmpty())"
        raise UnsupportedPythonSyntax("Condition type is not supported")

    def _print_call(self, call: ast.Call, assigned: set[str], types: dict[str, str],
                    integer_values: dict[str, int]) -> str:
        if not isinstance(call.func, ast.Name) or call.func.id != "print":
            raise UnsupportedPythonSyntax("Only calls to print() are supported as expression statements")
        if call.keywords or len(call.args) > 32:
            raise UnsupportedPythonSyntax("print() supports at most 32 positional arguments and no keywords")
        expressions = [
            self._expr(arg, assigned, types, integer_values) for arg in call.args
        ]
        if not expressions:
            return "println()"
        values = ", ".join(expression for expression, _ in expressions)
        return f"println(listOf<Any>({values}).joinToString(\" \") {{ pyString(it) }})"

    def _if_statement(self, node: ast.If, assigned: set[str], types: dict[str, str],
                      integer_values: dict[str, int]) -> str:
        def render_body(body: list[ast.stmt]) -> list[str]:
            rendered: list[str] = []
            for statement in body:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    rendered.append(self._print_call(statement.value, assigned, types, integer_values))
                elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                      and isinstance(statement.value.value, str)):
                    continue
                else:
                    raise UnsupportedPythonSyntax("Kotlin conditional bodies may contain only print() statements")
            if not rendered:
                raise UnsupportedPythonSyntax("Conditional bodies must contain at least one print() statement")
            return rendered

        rendered: list[str] = []
        cursor = node
        depth = 0
        while True:
            depth += 1
            if depth > 20:
                raise UnsupportedPythonSyntax("if/elif chains are limited to 20 branches")
            condition = self._condition(cursor.test, assigned, types, integer_values)
            keyword = "if" if depth == 1 else "} else if"
            rendered.append(f"{keyword} ({condition}) {{")
            rendered.extend("    " + line for line in render_body(cursor.body))
            if cursor.orelse and len(cursor.orelse) == 1 and isinstance(cursor.orelse[0], ast.If):
                cursor = cursor.orelse[0]
                continue
            if cursor.orelse:
                rendered.append("} else {")
                rendered.extend("    " + line for line in render_body(cursor.orelse))
            rendered.append("}")
            break
        return "\n".join(rendered)


    def _for_statement(self, node: ast.For, assigned: set[str], types: dict[str, str],
                       integer_values: dict[str, int], referenced_after: bool) -> str | None:
        if not isinstance(node.target, ast.Name):
            raise UnsupportedPythonSyntax("range() loop targets must be simple variable names")
        name = node.target.id
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in _KOTLIN_RESERVED
                or name in {"print", "str", "abs", "range", "pyString", "println", "Math",
                            "Int", "String", "Boolean", "Any", "listOf"}):
            raise UnsupportedPythonSyntax(f"Loop variable '{name}' is not a supported Kotlin identifier")
        if name in assigned:
            raise UnsupportedPythonSyntax("range() loop variables cannot shadow an already assigned variable")
        if node.orelse:
            raise UnsupportedPythonSyntax("for/else statements are not supported in Kotlin")
        if (not isinstance(node.iter, ast.Call) or not isinstance(node.iter.func, ast.Name)
                or node.iter.func.id != "range"):
            raise UnsupportedPythonSyntax("Only range() loops are supported in Kotlin")
        call = node.iter
        if call.keywords or len(call.args) not in {1, 2, 3}:
            raise UnsupportedPythonSyntax("range() supports one, two, or three positional integer arguments")

        rendered_args: list[str] = []
        values: list[int] = []
        for argument in call.args:
            expression, value_type = self._expr(argument, assigned, types, integer_values)
            if value_type != "int":
                raise UnsupportedPythonSyntax("range() arguments must be statically known integers")
            rendered_args.append(expression)
            values.append(self._int_value(argument, integer_values))
        if len(values) == 1:
            start_expr, start_value = "0", 0
            stop_expr, stop_value = rendered_args[0], values[0]
            step_value = 1
        elif len(values) == 2:
            start_expr, start_value = rendered_args[0], values[0]
            stop_expr, stop_value = rendered_args[1], values[1]
            step_value = 1
        else:
            start_expr, start_value = rendered_args[0], values[0]
            stop_expr, stop_value, step_value = rendered_args[1], values[1], values[2]
        if step_value == 0:
            raise UnsupportedPythonSyntax("range() step cannot be zero")
        if abs(step_value) > _INT_MAX:
            raise UnsupportedPythonSyntax("range() step magnitude exceeds the signed 32-bit Kotlin Int range")
        actual_range = range(start_value, stop_value, step_value)
        count = len(actual_range)
        if count > 10_000:
            raise UnsupportedPythonSyntax("range() loops are limited to 10000 actual iterations")
        if not node.body:
            raise UnsupportedPythonSyntax("Empty range() loop bodies are not supported")

        assigned.add(name)
        types[name] = "int"
        previous_value = integer_values.get(name)
        rendered_body: list[str] | None = None
        validation_values = list(actual_range) if count else [start_value]
        try:
            for loop_value in validation_values:
                integer_values[name] = loop_value
                body_lines: list[str] = []
                for statement in node.body:
                    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                        body_lines.append(self._print_call(statement.value, assigned, types, integer_values))
                    elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                          and isinstance(statement.value.value, str)):
                        continue
                    else:
                        raise UnsupportedPythonSyntax("range() loop bodies may contain only print() statements")
                if not body_lines:
                    raise UnsupportedPythonSyntax("range() loop bodies must contain at least one print() statement")
                if rendered_body is None:
                    rendered_body = body_lines
        finally:
            assigned.discard(name)
            types.pop(name, None)
            if previous_value is None:
                integer_values.pop(name, None)
            else:
                integer_values[name] = previous_value

        if count == 0:
            if referenced_after:
                raise UnsupportedPythonSyntax("A zero-iteration range() leaves its loop variable undefined in Python")
            return None

        last_value = actual_range[-1]
        if step_value > 0:
            progression = f"{start_expr}..{last_value} step {step_value}"
        else:
            progression = f"{start_expr} downTo {last_value} step {abs(step_value)}"
        body = "\n".join("    " + line for line in (rendered_body or []))
        rendered = f"for ({name} in {progression}) {{\n{body}\n}}"
        if referenced_after:
            rendered += f"\nvar {name}: Int = {last_value}"
            assigned.add(name)
            types[name] = "int"
            integer_values[name] = last_value
        return rendered

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        del context
        if project.language_id != "python":
            raise ValueError("PythonToKotlinTargetAdapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("This adapter currently accepts exactly one source file")
        self.warnings = [
            "Deterministic Python-to-Kotlin translation supports one file, bounded Int/String/Boolean expressions, str(), abs(), print(), print-only if/elif/else chains, and statically bounded print-only range() loops.",
            "Assignments inside branches or loops, nested control flow, while loops, functions, imports, classes, collections, and full project migration are not supported by this subset."
        ]
        try:
            tree = ast.parse(project.units[0].source_text)
        except (SyntaxError, RecursionError):
            raise UnsupportedPythonSyntax("Python source contains invalid or excessively nested syntax") from None
        has_str_call = any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "str" for item in ast.walk(tree))
        has_abs_call = any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "abs" for item in ast.walk(tree))
        has_range_call = any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "range" for item in ast.walk(tree))
        if has_str_call and any(isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == "str" for item in ast.walk(tree)):
            raise UnsupportedPythonSyntax("Shadowing the str() builtin is not supported")
        if has_abs_call and any(isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == "abs" for item in ast.walk(tree)):
            raise UnsupportedPythonSyntax("Shadowing the abs() builtin is not supported")
        if has_range_call and any(isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == "range" for item in ast.walk(tree)):
            raise UnsupportedPythonSyntax("Shadowing the range() builtin is not supported")

        assigned: set[str] = set()
        types: dict[str, str] = {}
        integer_values: dict[str, int] = {}
        statements: list[str] = []
        referenced = {
            item.id for item in ast.walk(tree)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
        }
        for node_index, node in enumerate(tree.body):
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                name = node.targets[0].id
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in _KOTLIN_RESERVED or name in {"print", "str", "abs", "pyString", "println", "Math", "Int", "String", "Boolean", "Any", "listOf"}:
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not supported in Kotlin")
                expression, value_type = self._expr(node.value, assigned, types, integer_values)
                if name in assigned:
                    if types[name] != value_type:
                        raise UnsupportedPythonSyntax(f"Changing the type of '{name}' is not supported")
                    statements.append(f"{name} = {expression}")
                else:
                    statements.append(f"var {name}: { {'int': 'Int', 'string': 'String', 'bool': 'Boolean'}[value_type] } = {expression}")
                    assigned.add(name)
                types[name] = value_type
                if value_type == "int":
                    integer_values[name] = self._int_value(node.value, integer_values)
                else:
                    integer_values.pop(name, None)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                statements.append(self._print_call(node.value, assigned, types, integer_values))
            elif isinstance(node, ast.If):
                statements.append(self._if_statement(node, assigned, types, integer_values))
            elif isinstance(node, ast.For):
                referenced_after = any(
                    isinstance(child, ast.Name) and child.id == node.target.id and isinstance(child.ctx, ast.Load)
                    for later in tree.body[node_index + 1:] for child in ast.walk(later)
                ) if isinstance(node.target, ast.Name) else False
                rendered_loop = self._for_statement(
                    node, assigned, types, integer_values, referenced_after
                )
                if rendered_loop is not None:
                    statements.append(rendered_loop)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")

        unused = sorted(assigned - referenced)
        if unused:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
        body = "\n".join("    " + statement for statement in statements)
        kotlin = (
            "fun pyString(value: Any): String = when (value) {\n"
            "    is Boolean -> if (value) \"True\" else \"False\"\n"
            "    else -> value.toString()\n"
            "}\n\n"
            "fun main() {\n" + body + "\n}\n"
        )
        return [GeneratedArtifact("Main.kt", kotlin)]
