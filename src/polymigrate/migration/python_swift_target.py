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

    def _checked_int(self, node: ast.expr, values: dict[str, int]) -> int:
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
            operand = self._checked_int(node.operand, values)
            value = operand if isinstance(node.op, ast.UAdd) else -operand
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
            left = self._checked_int(node.left, values)
            right = self._checked_int(node.right, values)
            value = left + right if isinstance(node.op, ast.Add) else left - right if isinstance(node.op, ast.Sub) else left * right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "abs" and len(node.args) == 1 and not node.keywords):
            value = abs(self._checked_int(node.args[0], values))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "len" and len(node.args) == 1 and not node.keywords):
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                value = len(argument.value)
            elif isinstance(argument, ast.Name) and argument.id in self._string_values:
                value = len(self._string_values[argument.id])
            else:
                raise UnsupportedPythonSyntax("len() result cannot be proven statically safe for integer arithmetic")
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

    def _condition(self, node: ast.expr, assigned: set[str]) -> str:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"!({self._condition(node.operand, assigned)})"
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            operator = " && " if isinstance(node.op, ast.And) else " || "
            return "(" + operator.join(self._condition(item, assigned) for item in node.values) + ")"
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise UnsupportedPythonSyntax("Chained comparisons are not supported in Swift conditions")
            left, left_type = self._expr(node.left, assigned)
            right, right_type = self._expr(node.comparators[0], assigned)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Swift comparisons require operands of the same inferred type")
            operator_node = node.ops[0]
            operators = {
                ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<",
                ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            }
            operator = operators.get(type(operator_node))
            if operator is None:
                raise UnsupportedPythonSyntax("Only simple equality and ordering comparisons are supported in Swift")
            if left_type == "string":
                if not isinstance(operator_node, (ast.Eq, ast.NotEq)):
                    raise UnsupportedPythonSyntax("String ordering comparisons are not supported in Swift")
                # Swift String equality uses Unicode canonical equivalence, while Python
                # compares code-point sequences. Compare Unicode scalars to preserve Python semantics.
                comparison = f"({left}).unicodeScalars.elementsEqual(({right}).unicodeScalars)"
                return f"({comparison})" if isinstance(operator_node, ast.Eq) else f"(!{comparison})"
            if left_type == "bool" and not isinstance(operator_node, (ast.Eq, ast.NotEq)):
                raise UnsupportedPythonSyntax("Boolean ordering comparisons are not supported in Swift")
            return f"({left} {operator} {right})"
        expression, value_type = self._expr(node, assigned)
        if value_type == "bool":
            return expression
        if value_type == "int":
            return f"({expression} != 0)"
        if value_type == "string":
            return f"!({expression}).isEmpty"
        raise UnsupportedPythonSyntax("Condition type is not supported in Swift")

    def _for_statement(self, node: ast.For, assigned: set[str]) -> list[str]:
        if not isinstance(node.target, ast.Name):
            raise UnsupportedPythonSyntax("range() loop targets must be simple variable names in Swift")
        name = node.target.id
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                or name in _SWIFT_KEYWORDS or name in {"print", "abs", "str", "len", "range"}
                or name.startswith("__")):
            raise UnsupportedPythonSyntax(f"Loop variable '{name}' is not supported in Swift")
        if name in assigned:
            raise UnsupportedPythonSyntax("range() loop variables cannot shadow assigned variables in Swift")
        if node.orelse:
            raise UnsupportedPythonSyntax("for/else statements are not supported in Swift")
        if not isinstance(node.iter, ast.Call) or not isinstance(node.iter.func, ast.Name) or node.iter.func.id != "range":
            raise UnsupportedPythonSyntax("Swift supports only statically bounded for i in range(...) loops")
        if "range" in assigned:
            raise UnsupportedPythonSyntax("Shadowing the range() builtin is not supported in Swift")
        call = node.iter
        if call.keywords or not 1 <= len(call.args) <= 3:
            raise UnsupportedPythonSyntax("range() must have one to three positional integer arguments in Swift")
        if len(call.args) == 1:
            start_node, stop_node, step_node = ast.Constant(value=0), call.args[0], ast.Constant(value=1)
        elif len(call.args) == 2:
            start_node, stop_node, step_node = call.args[0], call.args[1], ast.Constant(value=1)
        else:
            start_node, stop_node, step_node = call.args
        start_value = self._checked_int(start_node, self._int_values)
        stop_value = self._checked_int(stop_node, self._int_values)
        step_value = self._checked_int(step_node, self._int_values)
        if step_value == 0:
            raise UnsupportedPythonSyntax("range() step cannot be zero")
        values_range = range(start_value, stop_value, step_value)
        if len(values_range) > 10_000:
            raise UnsupportedPythonSyntax("Swift range loops are limited to 10000 iterations")
        values = list(values_range)
        minimum, maximum = -(2**31), 2**31 - 1
        if values and not minimum <= values[-1] + step_value <= maximum:
            raise UnsupportedPythonSyntax("Swift range loop increment could overflow signed Int32")
        start_expression, _ = self._expr(start_node, assigned)
        stop_expression, _ = self._expr(stop_node, assigned)
        step_expression, _ = self._expr(step_node, assigned)

        assigned.add(name)
        self._types[name] = "int"
        rendered_body: list[str] | None = None
        # Check every reachable iteration value so expressions such as i + 1
        # cannot overflow only on a later loop iteration.
        for loop_value in (values if values else [0]):
            self._int_values[name] = loop_value
            body: list[str] = []
            for statement in node.body:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    body.extend("    " + line for line in self._print_call(statement.value, assigned))
                elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                      and isinstance(statement.value.value, str)):
                    continue
                else:
                    raise UnsupportedPythonSyntax(
                        "Swift range-loop bodies may contain only print() calls; assignments and nested control flow are rejected"
                    )
            if not body:
                raise UnsupportedPythonSyntax("Empty range-loop bodies are not supported in Swift")
            if rendered_body is None:
                rendered_body = body
        assigned.remove(name)
        self._types.pop(name, None)
        self._int_values.pop(name, None)

        assert rendered_body is not None
        return [
            f"for {name} in stride(from: Int32({start_expression}), to: Int32({stop_expression}), by: Int({step_expression})) {{",
            *rendered_body,
            "}",
        ]

    def _static_string_value(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return self._string_values.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._static_string_value(node.left)
            right = self._static_string_value(node.right)
            return left + right if left is not None and right is not None else None
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "str" and len(node.args) == 1 and not node.keywords):
            argument = node.args[0]
            if isinstance(argument, ast.Constant):
                if isinstance(argument.value, str):
                    return argument.value
                if type(argument.value) is bool:
                    return "True" if argument.value else "False"
                if type(argument.value) is int:
                    return str(self._checked_int(argument, self._int_values))
            if isinstance(argument, ast.Name):
                value_type = self._types.get(argument.id)
                if value_type == "string":
                    return self._string_values.get(argument.id)
                if value_type == "int" and argument.id in self._int_values:
                    return str(self._int_values[argument.id])
                if value_type == "bool" and argument.id in self._bool_values:
                    return "True" if self._bool_values[argument.id] else "False"
            if isinstance(argument, (ast.UnaryOp, ast.BinOp, ast.Call)):
                try:
                    value = self._checked_int(argument, self._int_values)
                    return str(value)
                except UnsupportedPythonSyntax:
                    return None
        return None

    def _if_statement(self, node: ast.If, assigned: set[str], *, depth: int = 1,
                      keyword: str = "if", close_end: bool = True,
                      base_ints: dict[str, int] | None = None,
                      base_strings: dict[str, str] | None = None,
                      base_bools: dict[str, bool] | None = None,
                      modified_names: set[str] | None = None,
                      branch_facts: list[tuple[dict[str, int], dict[str, str], dict[str, bool]]] | None = None) -> list[str]:
        root_call = base_ints is None
        if base_ints is None:
            base_ints = dict(self._int_values)
        if base_strings is None:
            base_strings = dict(self._string_values)
        if base_bools is None:
            base_bools = dict(self._bool_values)
        if modified_names is None:
            modified_names = set()
        if branch_facts is None:
            branch_facts = []
        if depth > 20:
            raise UnsupportedPythonSyntax("if/elif chains are limited to 20 branches in Swift")

        self._int_values = dict(base_ints)
        self._string_values = dict(base_strings)
        self._bool_values = dict(base_bools)
        condition = self._condition(node.test, assigned)
        rendered = [f"{keyword} {condition} {{"]

        def snapshot() -> tuple[dict[str, int], dict[str, str], dict[str, bool]]:
            return dict(self._int_values), dict(self._string_values), dict(self._bool_values)

        def render_branch(statements: list[ast.stmt]) -> list[str]:
            lines: list[str] = []
            for statement in statements:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    lines.extend("    " + line for line in self._print_call(statement.value, assigned))
                elif isinstance(statement, ast.Assign):
                    if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                        raise UnsupportedPythonSyntax("Swift conditional assignments must target one existing variable")
                    target = statement.targets[0].id
                    if target not in assigned:
                        raise UnsupportedPythonSyntax("Swift conditional assignments must target existing variables")
                    expression, value_type = self._expr(statement.value, assigned)
                    if value_type != self._types.get(target):
                        raise UnsupportedPythonSyntax("Swift conditional assignments must preserve the variable type")
                    if value_type == "int":
                        self._int_values[target] = self._checked_int(statement.value, self._int_values)
                    elif value_type == "string":
                        static_value = self._static_string_value(statement.value)
                        if static_value is None:
                            self._string_values.pop(target, None)
                        else:
                            self._string_values[target] = static_value
                    elif value_type == "bool":
                        if isinstance(statement.value, ast.Constant) and type(statement.value.value) is bool:
                            self._bool_values[target] = statement.value.value
                        elif isinstance(statement.value, ast.Name) and statement.value.id in self._bool_values:
                            self._bool_values[target] = self._bool_values[statement.value.id]
                        else:
                            self._bool_values.pop(target, None)
                    modified_names.add(target)
                    lines.append(f"    {target} = {expression}")
                elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                      and isinstance(statement.value.value, str)):
                    continue
                else:
                    raise UnsupportedPythonSyntax(
                        "Swift conditional bodies may contain only print() calls and same-type assignments to existing variables"
                    )
            if not lines:
                raise UnsupportedPythonSyntax("Empty conditional bodies are not supported in Swift")
            return lines

        rendered.extend(render_branch(node.body))
        branch_facts.append(snapshot())
        if node.orelse:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                rendered.extend(self._if_statement(
                    node.orelse[0], assigned, depth=depth + 1, keyword="} else if",
                    close_end=False, base_ints=base_ints, base_strings=base_strings,
                    base_bools=base_bools, modified_names=modified_names, branch_facts=branch_facts,
                ))
            else:
                self._int_values = dict(base_ints)
                self._string_values = dict(base_strings)
                self._bool_values = dict(base_bools)
                rendered.append("} else {")
                rendered.extend(render_branch(node.orelse))
                branch_facts.append(snapshot())
        else:
            branch_facts.append((dict(base_ints), dict(base_strings), dict(base_bools)))

        if close_end:
            rendered.append("}")

        if root_call:
            self._int_values = dict(base_ints)
            self._string_values = dict(base_strings)
            self._bool_values = dict(base_bools)
            for name in modified_names:
                value_type = self._types.get(name)
                if value_type == "int":
                    values = [facts[0].get(name) for facts in branch_facts]
                    if values and values[0] is not None and all(value == values[0] for value in values):
                        self._int_values[name] = values[0]
                    else:
                        self._int_values.pop(name, None)
                elif value_type == "string":
                    values = [facts[1].get(name) for facts in branch_facts]
                    if values and values[0] is not None and all(value == values[0] for value in values):
                        self._string_values[name] = values[0]
                    else:
                        self._string_values.pop(name, None)
                elif value_type == "bool":
                    values = [facts[2].get(name) for facts in branch_facts]
                    if values and values[0] is not None and all(value == values[0] for value in values):
                        self._bool_values[name] = values[0]
                    else:
                        self._bool_values.pop(name, None)
        return rendered

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
            terminator = '" "' if index < len(call.args) - 1 else '""'
            lines.append(f"print({expression}, terminator: {terminator})")
        lines.append('print("")')
        return lines

    def generate(self, project: SourceProject, context: dict) -> list[GeneratedArtifact]:
        self.warnings = [
            "Deterministic Python-to-Swift translation supports one file and a strict expression/assignment/print subset only.",
            "Functions, imports, collections, nested control flow, assignments inside loops, project dependencies, and full-project migration are unsupported.",
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
        assignment_counts: dict[str, int] = {}
        for statement in ast.walk(tree):
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
                target_name = statement.targets[0].id
                assignment_counts[target_name] = assignment_counts.get(target_name, 0) + 1
        for node_index, node in enumerate(tree.body):
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
                    declaration = "var" if assignment_counts.get(name, 1) > 1 else "let"
                    statements.append(f"{declaration} {name}: {swift_types[inferred_type]} = {expression}")
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
            elif isinstance(node, ast.For):
                loop_name = node.target.id if isinstance(node.target, ast.Name) else None
                if loop_name and any(
                    isinstance(child, ast.Name) and child.id == loop_name and isinstance(child.ctx, ast.Load)
                    for following in tree.body[node_index + 1:] for child in ast.walk(following)
                ):
                    raise UnsupportedPythonSyntax("Use of a Swift range-loop variable after its loop is not supported")
                statements.extend(self._for_statement(node, assigned))
            elif isinstance(node, ast.If):
                statements.extend(self._if_statement(node, assigned))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                statements.extend(self._print_call(node.value, assigned))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}; Swift subset only supports assignments, print-only conditionals, and bounded print-only range loops")
        unused = sorted(assigned - referenced_names)
        if unused:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
        self._types = {}
        self._int_values = {}
        self._string_values = {}
        self._bool_values = {}
        content = "\n".join(statements) + "\n"
        return [GeneratedArtifact("main.swift", content)]
