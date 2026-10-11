"""Deterministic translator for a deliberately small Python-to-Go subset.

Supported:
- Integer and string literals
- Simple variable assignments
- print() with up to 32 positional arguments
- Binary +, -, and * expressions
- Unary + and - on integers
- Simple if/else conditions with safe comparisons and print-only branches

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
            if type(node.value) is bool:
                return ("true" if node.value else "false"), "bool"
            if node.value is None:
                raise UnsupportedPythonSyntax("None literals are not supported")
            if type(node.value) is int:
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

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str":
            if "str" in assigned:
                raise UnsupportedPythonSyntax("Shadowing the str() builtin is not supported")
            if len(node.args) != 1 or node.keywords:
                raise UnsupportedPythonSyntax("str() must have exactly one positional argument")
            expression, value_type = self._expr(node.args[0], assigned)
            if value_type == "string":
                return expression, "string"
            if value_type == "int":
                return f"fmt.Sprint({expression})", "string"
            if value_type == "bool":
                return f'map[bool]string{{true: "True", false: "False"}}[{expression}]', "string"
            raise UnsupportedPythonSyntax("str() supports only integer, string, and boolean values")

        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult)
        ):
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.right, assigned)
            if left_type != right_type:
                raise UnsupportedPythonSyntax(
                    "Mixed or unknown operand types are not supported"
                )
            if left_type == "bool":
                raise UnsupportedPythonSyntax("Boolean arithmetic is not supported")
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

    def _range_spec(
        self, node: ast.For, assigned: set[str]
    ) -> tuple[str, str, int, int, str, int]:
        call = node.iter
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "range":
            raise UnsupportedPythonSyntax("Only range() loops are supported")
        if "range" in assigned:
            raise UnsupportedPythonSyntax("Shadowing the range() builtin is not supported")
        if call.keywords or len(call.args) not in {1, 2, 3}:
            raise UnsupportedPythonSyntax("range() supports one, two, or three positional arguments")
        if len(call.args) == 1:
            start_expression, start_value = "0", 0
            stop_node = call.args[0]
            stop_expression, stop_type = self._expr(stop_node, assigned)
            if stop_type != "int":
                raise UnsupportedPythonSyntax("range() bounds must be integers")
            stop_value = self._checked_integer_value(stop_node, self._int_values)
            step_expression, step_value = "1", 1
        else:
            start_node, stop_node = call.args[:2]
            start_expression, start_type = self._expr(start_node, assigned)
            stop_expression, stop_type = self._expr(stop_node, assigned)
            if start_type != "int" or stop_type != "int":
                raise UnsupportedPythonSyntax("range() bounds must be integers")
            start_value = self._checked_integer_value(start_node, self._int_values)
            stop_value = self._checked_integer_value(stop_node, self._int_values)
            if len(call.args) == 3:
                step_node = call.args[2]
                step_expression, step_type = self._expr(step_node, assigned)
                if step_type != "int":
                    raise UnsupportedPythonSyntax("range() step must be an integer")
                step_value = self._checked_integer_value(step_node, self._int_values)
            else:
                step_expression, step_value = "1", 1
        if step_value == 0:
            raise UnsupportedPythonSyntax("range() step cannot be zero")
        if step_value > 0:
            iterations = max(0, (stop_value - start_value + step_value - 1) // step_value)
        else:
            stride = -step_value
            iterations = max(0, (start_value - stop_value + stride - 1) // stride)
        if iterations > 10_000:
            raise UnsupportedPythonSyntax("range() exceeds the 10000-iteration static limit")
        # The generated loop increments after the final body execution. Reject a
        # post-loop value outside the target's exact integer range rather than
        # allowing overflow or loss of JavaScript integer precision.
        post_value = start_value + iterations * step_value
        minimum, maximum = -(2**31), 2**31 - 1
        if not minimum <= post_value <= maximum:
            raise UnsupportedPythonSyntax("range() step would overflow the target integer range")
        return start_expression, stop_expression, start_value, stop_value, step_expression, step_value

    def _condition(self, node: ast.expr, assigned: set[str]) -> str:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"!({self._condition(node.operand, assigned)})"
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            operator = "&&" if isinstance(node.op, ast.And) else "||"
            return "(" + f" {operator} ".join(self._condition(item, assigned) for item in node.values) + ")"
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise UnsupportedPythonSyntax("Chained comparisons are not supported in conditions")
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.comparators[0], assigned)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Comparisons require operands of the same known type")
            operators = {
                ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<",
                ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            }
            operator = operators.get(type(node.ops[0]))
            if operator is None:
                raise UnsupportedPythonSyntax("Only ==, !=, <, <=, >, and >= comparisons are supported")
            if left_type == "bool" and operator not in {"==", "!="}:
                raise UnsupportedPythonSyntax("Boolean ordering comparisons are not supported")
            if left_type == "string" and operator not in {"==", "!="}:
                raise UnsupportedPythonSyntax("String ordering comparisons are not supported")
            return f"({left} {operator} {right})"
        if isinstance(node, ast.Name):
            value, value_type = self._expr(node, assigned)
            if value_type == "bool":
                return value
            if value_type == "int":
                return f"({value} != 0)"
            if value_type == "string":
                return f'({value} != "")'
        if isinstance(node, ast.Constant) and type(node.value) is bool:
            return "true" if node.value else "false"
        raise UnsupportedPythonSyntax(f"Unsupported condition syntax: {type(node).__name__}")

    def _print_expression(self, expression: str, value_type: str) -> str:
        if value_type == "bool":
            return f'fmt.Println(map[bool]string{{true: "True", false: "False"}}[{expression}])'
        return f"fmt.Println({expression})"

    def _render_print_call(self, call: ast.Call, assigned: set[str]) -> str:
        if call.keywords:
            raise UnsupportedPythonSyntax("print() keyword arguments such as sep/end are not supported")
        if len(call.args) > 32:
            raise UnsupportedPythonSyntax("print() is limited to 32 positional arguments")
        if len(call.args) == 1:
            expression, value_type = self._expr(call.args[0], assigned)
            return self._print_expression(expression, value_type)
        values = []
        for argument in call.args:
            expression, value_type = self._expr(argument, assigned)
            if value_type == "bool":
                expression = f'map[bool]string{{true: "True", false: "False"}}[{expression}]'
            values.append(expression)
        return "fmt.Println(" + ", ".join(values) + ")"

    def _print_statement(self, node: ast.stmt, assigned: set[str]) -> str:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            raise UnsupportedPythonSyntax("Control-flow bodies may contain only print() statements")
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id != "print":
            raise UnsupportedPythonSyntax("Only calls to print() are supported in conditional bodies")
        return self._render_print_call(call, assigned)

    def _if_statement(self, node: ast.If, assigned: set[str]) -> str:
        """Render a bounded if/elif/else chain; branch bodies remain print-only."""
        rendered: list[str] = []
        cursor = node
        depth = 0
        while True:
            depth += 1
            if depth > 20:
                raise UnsupportedPythonSyntax("Conditional chains are limited to 20 branches")
            condition = self._condition(cursor.test, assigned)
            if not cursor.body:
                raise UnsupportedPythonSyntax("Empty conditional bodies are not supported")
            body = [self._print_statement(statement, assigned) for statement in cursor.body]
            prefix = f"if {condition} {{" if depth == 1 else f"}} else if {condition} {{"
            rendered.append(prefix)
            rendered.extend("\t" + line for line in body)
            if cursor.orelse and len(cursor.orelse) == 1 and isinstance(cursor.orelse[0], ast.If):
                cursor = cursor.orelse[0]
                continue
            if cursor.orelse:
                alternative = [self._print_statement(statement, assigned) for statement in cursor.orelse]
                rendered.append("} else {")
                rendered.extend("\t" + line for line in alternative)
                rendered.append("}")
            else:
                rendered.append("}")
            break
        return "\n".join(rendered)

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
                statements.append(self._render_print_call(call, assigned))
                used_fmt = True

            elif isinstance(node, ast.For):
                if not isinstance(node.target, ast.Name):
                    raise UnsupportedPythonSyntax("range() loop targets must be simple variable names")
                name = node.target.id
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in _GO_KEYWORDS or name in {"_", "print", "fmt"}:
                    raise UnsupportedPythonSyntax(f"Loop variable '{name}' is not supported in Go")
                if name in assigned:
                    raise UnsupportedPythonSyntax("range() loop variables cannot shadow assigned variables")
                if node.orelse:
                    raise UnsupportedPythonSyntax("for/else statements are not supported")
                if not node.body:
                    raise UnsupportedPythonSyntax("Empty loop bodies are not supported")
                start_expression, stop_expression, _, _, step_expression, step_value = self._range_spec(node, assigned)
                assigned.add(name)
                self._types[name] = "int"
                body = [self._print_statement(statement, assigned) for statement in node.body]
                assigned.remove(name)
                self._types.pop(name, None)
                self._int_values.pop(name, None)
                operator = "<" if step_value > 0 else ">"
                increment = f"{name}++" if step_value == 1 else f"{name}--" if step_value == -1 else f"{name} += {step_expression}"
                rendered = [f"for {name} := {start_expression}; {name} {operator} {stop_expression}; {increment} {{",
                            *("\t" + line for line in body), "}"]
                statements.append("\n".join(rendered))
                used_fmt = True
            elif isinstance(node, ast.If):
                statements.append(self._if_statement(node, assigned))
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
