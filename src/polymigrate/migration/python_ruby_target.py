"""Deterministic translator for a deliberately small Python-to-Ruby subset."""
from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_RUBY_INT_MIN = -(2**31)
_RUBY_INT_MAX = 2**31 - 1
_RUBY_BUILTINS = {"print", "str", "abs", "range", "polymigrate_string"}
_RUBY_RESERVED = {
    "BEGIN", "END", "alias", "and", "begin", "break", "case", "class", "def",
    "defined", "do", "else", "elsif", "end", "ensure", "false", "for", "if",
    "in", "module", "next", "nil", "not", "or", "redo", "rescue", "retry",
    "return", "self", "super", "then", "true", "undef", "unless", "until",
    "when", "while", "yield",
}


class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported Python-to-Ruby subset."""


def _ruby_string(value: str) -> str:
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise UnsupportedPythonSyntax("Ruby string literals containing unsupported control characters are rejected")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


class PythonToRubyTargetAdapter:
    """Translate supported Python source files to standalone Ruby files."""

    language_id = "ruby"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    @staticmethod
    def _int_value(node: ast.expr, values: dict[str, int]) -> int:
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToRubyTargetAdapter._int_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToRubyTargetAdapter._int_value(node.left, values)
            right = PythonToRubyTargetAdapter._int_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "abs" and len(node.args) == 1 and not node.keywords):
            value = abs(PythonToRubyTargetAdapter._int_value(node.args[0], values))
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for signed 32-bit Ruby integers")
        if not _RUBY_INT_MIN <= value <= _RUBY_INT_MAX:
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
                return _ruby_string(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer, string, and boolean literals are supported")
        if isinstance(node, ast.Name):
            if not re.fullmatch(r"[a-z_][A-Za-z0-9_]*", node.id) or node.id in _RUBY_RESERVED:
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not a supported Ruby local variable")
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
            if value_type in {"int", "string"}:
                return f"({expression}).to_s", "string"
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
            return f"({expression}).abs", "int"
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

    def _condition(self, node: ast.expr, assigned: set[str], types: dict[str, str],
                   integer_values: dict[str, int], uses_boolean_string: list[bool]) -> str:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return "!(" + self._condition(node.operand, assigned, types, integer_values, uses_boolean_string) + ")"
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise UnsupportedPythonSyntax("Chained comparisons are not supported")
            left, left_type = self._expr(node.left, assigned, types, integer_values, uses_boolean_string)
            right, right_type = self._expr(node.comparators[0], assigned, types, integer_values, uses_boolean_string)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Comparisons require operands of the same inferred type")
            operator_node = node.ops[0]
            if isinstance(operator_node, ast.Eq):
                operator = "=="
            elif isinstance(operator_node, ast.NotEq):
                operator = "!="
            elif isinstance(operator_node, ast.Lt):
                operator = "<"
            elif isinstance(operator_node, ast.LtE):
                operator = "<="
            elif isinstance(operator_node, ast.Gt):
                operator = ">"
            elif isinstance(operator_node, ast.GtE):
                operator = ">="
            else:
                raise UnsupportedPythonSyntax("Only simple equality and integer ordering comparisons are supported")
            if left_type in {"string", "bool"} and not isinstance(operator_node, (ast.Eq, ast.NotEq)):
                raise UnsupportedPythonSyntax("String and boolean ordering comparisons are not supported")
            return f"({left} {operator} {right})"
        expression, value_type = self._expr(node, assigned, types, integer_values, uses_boolean_string)
        if value_type == "bool":
            return expression
        if value_type == "int":
            return f"({expression} != 0)"
        if value_type == "string":
            return f"({expression} != '')"
        raise UnsupportedPythonSyntax("Condition type is not supported")

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        if project.language_id != "python":
            raise ValueError("Python-to-Ruby adapter requires a Python source project")
        if not project.units:
            raise UnsupportedPythonSyntax("No Python source units were supplied")
        artifacts: list[GeneratedArtifact] = []
        self.warnings = [
            "Deterministic Python-to-Ruby translation supports simple assignments, signed 32-bit integer/string/boolean expressions, str(), abs(), positional print(), print-only if/elif/else chains, and bounded print-only range() loops.",
            "Functions, imports, classes, collections, branch assignments, nested control flow, and project manifest reconstruction are not supported by this deterministic subset.",
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
            loop_variables: set[str] = set()
            referenced = {node.id for node in ast.walk(tree)
                          if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}

            def render_print(call: ast.Call) -> str:
                if not isinstance(call.func, ast.Name) or call.func.id != "print":
                    raise UnsupportedPythonSyntax("Only calls to print() are supported as expression statements")
                if call.keywords or len(call.args) > 32:
                    raise UnsupportedPythonSyntax("print() supports at most 32 positional arguments and no keywords")
                expressions = [
                    self._expr(arg, assigned, types, integer_values, uses_boolean_string)
                    for arg in call.args
                ]
                if not expressions:
                    return "puts"
                uses_boolean_string[0] = True
                values = ", ".join(expression for expression, _ in expressions)
                return "puts [" + values + "].map { |value| polymigrate_string(value) }.join(' ')"

            def render_body(body: list[ast.stmt], indent: int) -> list[str]:
                rendered: list[str] = []
                for statement in body:
                    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                        rendered.append(" " * indent + render_print(statement.value))
                    elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                        continue
                    else:
                        raise UnsupportedPythonSyntax("if/elif/else and range() loop bodies may contain only print() statements")
                if not rendered:
                    raise UnsupportedPythonSyntax("Empty control-flow bodies are not supported")
                return rendered

            def render_if(statement: ast.If, indent: int = 0, depth: int = 1,
                          keyword: str = "if", close_end: bool = True) -> list[str]:
                if depth > 20:
                    raise UnsupportedPythonSyntax("if/elif chains are limited to 20 branches")
                condition = self._condition(statement.test, assigned, types, integer_values, uses_boolean_string)
                rendered = [" " * indent + keyword + " " + condition]
                rendered.extend(render_body(statement.body, indent + 2))
                if statement.orelse:
                    if len(statement.orelse) == 1 and isinstance(statement.orelse[0], ast.If):
                        rendered.extend(render_if(statement.orelse[0], indent, depth + 1, "elsif", False))
                    else:
                        rendered.append(" " * indent + "else")
                        rendered.extend(render_body(statement.orelse, indent + 2))
                if close_end:
                    rendered.append(" " * indent + "end")
                return rendered

            def render_for(statement: ast.For) -> list[str]:
                if not isinstance(statement.target, ast.Name):
                    raise UnsupportedPythonSyntax("range() loop targets must be simple variable names")
                name = statement.target.id
                if (not re.fullmatch(r"[a-z_][A-Za-z0-9_]*", name)
                        or name in _RUBY_RESERVED or name in _RUBY_BUILTINS):
                    raise UnsupportedPythonSyntax(f"Loop variable '{name}' is not a supported Ruby local variable")
                if name in assigned:
                    raise UnsupportedPythonSyntax("range() loop variables cannot shadow assigned variables")
                if statement.orelse:
                    raise UnsupportedPythonSyntax("for/else statements are not supported")
                if (not isinstance(statement.iter, ast.Call) or not isinstance(statement.iter.func, ast.Name)
                        or statement.iter.func.id != "range"):
                    raise UnsupportedPythonSyntax("Only range() loops are supported")
                call = statement.iter
                if "range" in assigned:
                    raise UnsupportedPythonSyntax("Shadowing the range() builtin is not supported")
                if call.keywords or len(call.args) not in {1, 2, 3}:
                    raise UnsupportedPythonSyntax("range() supports one, two, or three positional integer arguments")
                rendered_args: list[str] = []
                values: list[int] = []
                for argument in call.args:
                    expression, value_type = self._expr(argument, assigned, types, integer_values, uses_boolean_string)
                    if value_type != "int":
                        raise UnsupportedPythonSyntax("range() arguments must be integers, not booleans or strings")
                    rendered_args.append(expression)
                    values.append(self._int_value(argument, integer_values))
                if len(values) == 1:
                    start_expr, start_value = "0", 0
                    stop_expr, stop_value = rendered_args[0], values[0]
                    step_expr, step_value = "1", 1
                elif len(values) == 2:
                    start_expr, start_value = rendered_args[0], values[0]
                    stop_expr, stop_value = rendered_args[1], values[1]
                    step_expr, step_value = "1", 1
                else:
                    start_expr, start_value = rendered_args[0], values[0]
                    stop_expr, stop_value = rendered_args[1], values[1]
                    step_expr, step_value = rendered_args[2], values[2]
                if step_value == 0:
                    raise UnsupportedPythonSyntax("range() step cannot be zero")
                actual_range = range(start_value, stop_value, step_value)
                count = len(actual_range)
                if count > 10_000:
                    raise UnsupportedPythonSyntax("range() loops are limited to 10000 actual iterations")
                if not statement.body:
                    raise UnsupportedPythonSyntax("Empty range() loop bodies are not supported")
                assigned.add(name)
                types[name] = "int"
                integer_values[name] = start_value
                validation_values = list(actual_range) if count else [start_value]
                for loop_value in validation_values:
                    integer_values[name] = loop_value
                    for child in statement.body:
                        if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
                            call_node = child.value
                            if not isinstance(call_node.func, ast.Name) or call_node.func.id != "print":
                                raise UnsupportedPythonSyntax("range() loop bodies may contain only print() statements")
                            if call_node.keywords or len(call_node.args) > 32:
                                raise UnsupportedPythonSyntax("print() supports at most 32 positional arguments and no keywords")
                            for argument in call_node.args:
                                self._expr(argument, assigned, types, integer_values, uses_boolean_string)
                        elif isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant) and isinstance(child.value.value, str):
                            continue
                        else:
                            raise UnsupportedPythonSyntax("range() loop bodies may contain only print() statements")
                body = render_body(statement.body, 2)
                if count == 0:
                    assigned.remove(name)
                    types.pop(name, None)
                    integer_values.pop(name, None)
                    return []
                last_value = actual_range[-1]
                next_value = last_value + step_value
                if not _RUBY_INT_MIN <= next_value <= _RUBY_INT_MAX:
                    raise UnsupportedPythonSyntax("range() loop counter could overflow the signed 32-bit Ruby integer range")
                operator = "<" if step_value > 0 else ">"
                rendered = [f"{name} = {start_expr}", f"while {name} {operator} {stop_expr}"]
                rendered.extend(body)
                rendered.append(f"  {name} += {step_expr}")
                rendered.append("end")
                rendered.append(f"{name} = {last_value}")
                integer_values[name] = last_value
                loop_variables.add(name)
                return rendered

            for node in tree.body:
                if isinstance(node, ast.Assign):
                    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                        raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                    name = node.targets[0].id
                    if name in _RUBY_BUILTINS:
                        raise UnsupportedPythonSyntax(f"Variable name '{name}' conflicts with a supported builtin")
                    if not re.fullmatch(r"[a-z_][A-Za-z0-9_]*", name) or name in _RUBY_RESERVED:
                        raise UnsupportedPythonSyntax(f"Variable name '{name}' is not a supported Ruby local variable")
                    expression, value_type = self._expr(node.value, assigned, types, integer_values, uses_boolean_string)
                    statements.append(f"{name} = {expression}")
                    assigned.add(name)
                    types[name] = value_type
                    if value_type == "int":
                        integer_values[name] = self._int_value(node.value, integer_values)
                    else:
                        integer_values.pop(name, None)
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    statements.append(render_print(node.value))
                elif isinstance(node, ast.If):
                    statements.extend(render_if(node))
                elif isinstance(node, ast.For):
                    statements.extend(render_for(node))
                elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    continue
                else:
                    raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")
            unused = sorted(assigned - referenced - loop_variables)
            if unused:
                raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
            helper = (
                "def polymigrate_string(value)\n"
                "  return 'True' if value == true\n"
                "  return 'False' if value == false\n"
                "  value.to_s\n"
                "end\n"
                if uses_boolean_string[0] else ""
            )
            source = helper + ("\n" if helper else "") + "\n".join(statements) + "\n"
            relative = PurePosixPath(unit.relative_path)
            artifacts.append(GeneratedArtifact(relative.with_suffix(".rb").as_posix(), source))
        return artifacts
