"""Deterministic translator for a deliberately small Python-to-Rust subset.

Supports simple assignments, integer expressions (+, -, *), string/integer
literals, unary +/- on integers, bounded positional print(), integer abs(), and simple if/else
conditions with bounded comparisons. Unsupported syntax is rejected. Integer
arithmetic is limited to signed i32.
"""
from __future__ import annotations

import ast
import re

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_RUST_KEYWORDS = {
    "as", "async", "await", "break", "const", "continue", "crate", "dyn",
    "else", "enum", "extern", "false", "fn", "for", "if", "impl", "in",
    "let", "loop", "match", "mod", "move", "mut", "pub", "ref", "return",
    "self", "Self", "static", "struct", "super", "trait", "true", "type",
    "unsafe", "use", "where", "while", "abstract", "become", "box", "do",
    "final", "macro", "override", "priv", "typeof", "unsized", "virtual", "yield",
}


def _rust_string_literal(value: str) -> str:
    parts = ['"']
    escapes = {
        '"': '\\"',
        '\\': '\\\\',
        '\n': '\\n',
        '\r': '\\r',
        '\t': '\\t',
        '\0': '\\0',
    }
    for char in value:
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise UnsupportedPythonSyntax("Lone Unicode surrogates cannot be represented in Rust UTF-8 source")
        if char in escapes:
            parts.append(escapes[char])
        elif codepoint < 0x20 or codepoint == 0x7F:
            parts.append(f"\\u{{{codepoint:x}}}")
        else:
            parts.append(char)
    parts.append('"')
    return "".join(parts)

class UnsupportedPythonSyntax(ValueError):
    """Raised when syntax is outside the supported translation subset."""


class PythonToRustTargetAdapter:
    """Translate a constrained subset of one Python file into a minimal Cargo project."""

    language_id = "rust"

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self._types: dict[str, str] = {}
        self._int_values: dict[str, int] = {}

    @staticmethod
    def _checked_integer_value(node: ast.expr, values: dict[str, int]) -> int:
        minimum, maximum = -(2**31), 2**31 - 1
        if isinstance(node, ast.Constant) and type(node.value) is int:
            value = node.value
        elif isinstance(node, ast.Name) and node.id in values:
            value = values[node.id]
        elif (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
              and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
              and node.operand.value == 2**31):
            value = minimum
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = PythonToRustTargetAdapter._checked_integer_value(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "abs" and len(node.args) == 1 and not node.keywords:
            value = abs(PythonToRustTargetAdapter._checked_integer_value(node.args[0], values))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = PythonToRustTargetAdapter._checked_integer_value(node.left, values)
            right = PythonToRustTargetAdapter._checked_integer_value(node.right, values)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            else:
                value = left * right
        else:
            raise UnsupportedPythonSyntax("Integer expression cannot be proven safe for Rust i32")
        if not minimum <= value <= maximum:
            raise UnsupportedPythonSyntax("Integer literal or arithmetic result exceeds the signed Rust i32 range")
        return value

    def _expr(self, node: ast.expr, assigned: set[str]) -> tuple[str, str]:
        if isinstance(node, ast.Constant):
            if type(node.value) is bool:
                return ("true" if node.value else "false"), "bool"
            if type(node.value) is int:
                self._checked_integer_value(node, self._int_values)
                return str(node.value), "int"
            if isinstance(node.value, str):
                return _rust_string_literal(node.value), "string"
            raise UnsupportedPythonSyntax("Only integer and string literals are supported")
        if isinstance(node, ast.Name):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", node.id) or node.id in _RUST_KEYWORDS:
                raise UnsupportedPythonSyntax(f"Variable name '{node.id}' is not supported in Rust")
            if node.id not in assigned:
                raise UnsupportedPythonSyntax(f"Variable '{node.id}' is used before assignment")
            return node.id, self._types[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "abs":
            if "abs" in assigned:
                raise UnsupportedPythonSyntax("Shadowing the abs() builtin is not supported")
            if len(node.args) != 1 or node.keywords:
                raise UnsupportedPythonSyntax("abs() must have exactly one positional argument")
            expression, value_type = self._expr(node.args[0], assigned)
            if value_type != "int":
                raise UnsupportedPythonSyntax("abs() supports only integer values")
            self._checked_integer_value(node, self._int_values)
            return f"({expression} as i32).abs()", "int"

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str":
            if "str" in assigned:
                raise UnsupportedPythonSyntax("Shadowing the str() builtin is not supported")
            if len(node.args) != 1 or node.keywords:
                raise UnsupportedPythonSyntax("str() must have exactly one positional argument")
            expression, value_type = self._expr(node.args[0], assigned)
            if value_type == "string":
                return expression, "string"
            if value_type == "int":
                return f'format!("{{}}", {expression})', "string"
            if value_type == "bool":
                return f'(if {expression} {{ "True" }} else {{ "False" }}).to_string()', "string"
            raise UnsupportedPythonSyntax("str() supports only integer, string, and boolean values")
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.right, assigned)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Mixed or unknown operand types are not supported")
            if left_type == "bool":
                raise UnsupportedPythonSyntax("Boolean arithmetic is not supported")
            if left_type != "int":
                raise UnsupportedPythonSyntax("Only integer arithmetic is supported in the Rust subset")
            self._checked_integer_value(node, self._int_values)
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}[type(node.op)]
            return f"({left} {op} {right})", "int"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"!({self._condition(node.operand, assigned)})", "bool"

        if (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
                and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int
                and node.operand.value == 2**31):
            return "-2147483648", "int"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            if (isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant)
                    and type(node.operand.value) is int and node.operand.value == 0):
                return "0", "int"
            value, value_type = self._expr(node.operand, assigned)
            if value_type != "int":
                raise UnsupportedPythonSyntax("Unary + and - are supported only for integers")
            self._checked_integer_value(node, self._int_values)
            sign = "+" if isinstance(node.op, ast.UAdd) else "-"
            return sign + value, "int"
        raise UnsupportedPythonSyntax(f"Unsupported expression syntax: {type(node).__name__}")

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
            return f'println!("{{}}", if {expression} {{ "True" }} else {{ "False" }});'
        return f'println!("{{}}", {expression});'

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
                expression = f'if {expression} {{ "True" }} else {{ "False" }}'
            values.append(expression)
        if not values:
            return "println!();"
        placeholders = " ".join("{}" for _ in values)
        return 'println!("' + placeholders + '", ' + ", ".join(values) + ");"

    def _print_statement(self, node: ast.stmt, assigned: set[str]) -> str:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            raise UnsupportedPythonSyntax("Control-flow bodies may contain only print() statements")
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id != "print":
            raise UnsupportedPythonSyntax("Only calls to print() are supported in conditional bodies")
        return self._render_print_call(call, assigned)

    def _augmented_assignment_statement(self, node: ast.AugAssign, assigned: set[str], *,
                                        update_integer_facts: bool) -> str:
        if not isinstance(node.target, ast.Name) or node.target.id not in assigned:
            raise UnsupportedPythonSyntax("Augmented assignments must target a previously assigned variable")
        name = node.target.id
        operators = {ast.Add: "+=", ast.Sub: "-=", ast.Mult: "*="}
        operator = operators.get(type(node.op))
        if operator is None:
            raise UnsupportedPythonSyntax("Only +=, -=, and *= augmented assignments are supported")
        left_type = self._types[name]
        expression, right_type = self._expr(node.value, assigned)
        if left_type != right_type:
            raise UnsupportedPythonSyntax("Augmented assignment operands must have the same type")
        if left_type == "bool":
            raise UnsupportedPythonSyntax("Boolean augmented arithmetic is not supported")
        if left_type == "string":
            if True or not isinstance(node.op, ast.Add):
                raise UnsupportedPythonSyntax("String augmented assignment supports only += in this target subset")
        if left_type == "int":
            combined = ast.BinOp(left=ast.Name(id=name, ctx=ast.Load()), op=node.op, right=node.value)
            value = self._checked_integer_value(combined, self._int_values)
            if update_integer_facts:
                self._int_values[name] = value
        return f"{name} {operator} {expression};"

    def _branch_statement(self, node: ast.stmt, assigned: set[str], modified: set[str]) -> str:
        """Translate print calls or same-type assignments to pre-existing variables."""
        if isinstance(node, ast.AugAssign):
            statement = self._augmented_assignment_statement(node, assigned, update_integer_facts=False)
            modified.add(node.target.id)
            return statement
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                raise UnsupportedPythonSyntax("Conditional assignments must target one existing variable")
            name = node.targets[0].id
            if name not in assigned:
                raise UnsupportedPythonSyntax("Conditional assignments must target previously assigned variables")
            expression, value_type = self._expr(node.value, assigned)
            if self._types.get(name) != value_type:
                raise UnsupportedPythonSyntax("Conditional assignments cannot change a variable's type")
            if value_type == "int":
                self._checked_integer_value(node.value, self._int_values)
            modified.add(name)
            return f"{name} = {expression};"
        return self._print_statement(node, assigned)

    def _if_statement(self, node: ast.If, assigned: set[str]) -> str:
        """Render a bounded if/elif/else chain with print calls and same-type assignments to existing variables."""
        rendered: list[str] = []
        modified: set[str] = set()
        cursor = node
        depth = 0
        while True:
            depth += 1
            if depth > 20:
                raise UnsupportedPythonSyntax("Conditional chains are limited to 20 branches")
            condition = self._condition(cursor.test, assigned)
            if not cursor.body:
                raise UnsupportedPythonSyntax("Empty conditional bodies are not supported")
            body = [self._branch_statement(statement, assigned, modified) for statement in cursor.body]
            prefix = f"if {condition} {{" if depth == 1 else f"}} else if {condition} {{"
            rendered.append(prefix)
            rendered.extend("    " + line for line in body)
            if cursor.orelse and len(cursor.orelse) == 1 and isinstance(cursor.orelse[0], ast.If):
                cursor = cursor.orelse[0]
                continue
            if cursor.orelse:
                alternative = [self._branch_statement(statement, assigned, modified) for statement in cursor.orelse]
                rendered.append("} else {")
                rendered.extend("    " + line for line in alternative)
                rendered.append("}")
            else:
                rendered.append("}")
            break
        for name in modified:
            self._int_values.pop(name, None)
        return "\n".join(rendered)

    def generate(self, project: SourceProject, context: dict[str, object]) -> list[GeneratedArtifact]:
        del context
        if project.language_id != "python":
            raise ValueError("PythonToRustTargetAdapter requires a Python source project")
        if len(project.units) != 1:
            raise UnsupportedPythonSyntax("This adapter currently accepts exactly one source file")
        self.warnings = [
            "Translation supports only a small documented Python syntax subset.",
            "Generated output must pass build, test, security, and behavior checks.",
        ]
        self._types, self._int_values = {}, {}
        assigned: set[str] = set()
        statements: list[str] = []
        try:
            tree = ast.parse(project.units[0].source_text)
        except (SyntaxError, RecursionError):
            raise UnsupportedPythonSyntax("Python source contains invalid or excessively nested syntax") from None
        has_str_call = any(
            isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "str"
            for item in ast.walk(tree)
        )
        assigns_str = any(
            isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == "str"
            for item in ast.walk(tree)
        )
        if has_str_call and assigns_str:
            raise UnsupportedPythonSyntax("Shadowing the str() builtin is not supported")

        has_abs_call = any(
            isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "abs"
            for item in ast.walk(tree)
        )
        assigns_abs = any(
            isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store) and item.id == "abs"
            for item in ast.walk(tree)
        )
        if has_abs_call and assigns_abs:
            raise UnsupportedPythonSyntax("Shadowing the abs() builtin is not supported")

        referenced_names = {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        for node in tree.body:
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("Only assignments to one simple variable are supported")
                name = node.targets[0].id
                if name == "print":
                    raise UnsupportedPythonSyntax("Variable name 'print' conflicts with the supported print() builtin")
                if name == "_":
                    raise UnsupportedPythonSyntax("The Python underscore placeholder is not supported in Rust")
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in _RUST_KEYWORDS:
                    raise UnsupportedPythonSyntax(f"Variable name '{name}' is not supported in Rust")
                expr, inferred_type = self._expr(node.value, assigned)
                if name in assigned:
                    if self._types[name] != inferred_type:
                        raise UnsupportedPythonSyntax(f"Changing the type of '{name}' is not supported")
                    statements.append(f"{name} = {expr};")
                else:
                    statements.append(f"let mut {name} = {expr};")
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
                statements.append(self._render_print_call(call, assigned))
            elif isinstance(node, ast.AugAssign):
                statements.append(self._augmented_assignment_statement(node, assigned, update_integer_facts=True))

            elif isinstance(node, ast.For):
                if not isinstance(node.target, ast.Name):
                    raise UnsupportedPythonSyntax("range() loop targets must be simple variable names")
                name = node.target.id
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in _RUST_KEYWORDS or name in {"_", "print"}:
                    raise UnsupportedPythonSyntax(f"Loop variable '{name}' is not supported in Rust")
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
                if step_value == 1:
                    rendered = [f"for {name} in {start_expression}..{stop_expression} {{",
                                *("    " + line for line in body), "}"]
                else:
                    operator = "<" if step_value > 0 else ">"
                    rendered = ["{", f"    let mut {name} = {start_expression};",
                                f"    while {name} {operator} {stop_expression} {{",
                                *("        " + line for line in body),
                                f"        {name} += {step_expression};", "    }", "}"]
                statements.append("\n".join(rendered))
            elif isinstance(node, ast.If):
                statements.append(self._if_statement(node, assigned))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")
        unused_names = sorted(assigned - referenced_names)
        if unused_names:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused_names))
        cargo = '[package]\nname = "polymigrate_generated"\nversion = "0.1.0"\nedition = "2021"\n'
        source = "fn main() {\n" + "\n".join("    " + statement for statement in statements) + "\n}\n"
        return [
            GeneratedArtifact("Cargo.toml", cargo),
            GeneratedArtifact("src/main.rs", source),
        ]
