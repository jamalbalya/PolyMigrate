"""Deterministic translator for a deliberately small Python-to-C11 subset."""
from __future__ import annotations

import ast
import json
import re
from pathlib import PurePosixPath

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1
_BUILTINS = {"print", "abs", "printf", "main", "range"}
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

    def _while_condition_value(self, node: ast.expr, assigned: set[str], types: dict[str, str],
                               integer_values: dict[str, int]) -> bool:
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
            raise UnsupportedPythonSyntax("C while conditions must be one integer comparison")
        _, left_type = self._expr(node.left, assigned, types, integer_values)
        _, right_type = self._expr(node.comparators[0], assigned, types, integer_values)
        if left_type != "int" or right_type != "int":
            raise UnsupportedPythonSyntax("C while conditions support only integer comparisons")
        left = self._int_value(node.left, integer_values)
        right = self._int_value(node.comparators[0], integer_values)
        operator_node = node.ops[0]
        if isinstance(operator_node, ast.Eq):
            return left == right
        if isinstance(operator_node, ast.NotEq):
            return left != right
        if isinstance(operator_node, ast.Lt):
            return left < right
        if isinstance(operator_node, ast.LtE):
            return left <= right
        if isinstance(operator_node, ast.Gt):
            return left > right
        if isinstance(operator_node, ast.GtE):
            return left >= right
        raise UnsupportedPythonSyntax("C while conditions support only simple integer comparisons")

    def _augmented_assignment(self, node: ast.AugAssign, assigned: set[str], types: dict[str, str],
                              integer_values: dict[str, int]) -> str:
        if not isinstance(node.target, ast.Name):
            raise UnsupportedPythonSyntax("C augmented assignments must target one existing integer variable")
        name = node.target.id
        if name not in assigned or types.get(name) != "int":
            raise UnsupportedPythonSyntax("C augmented assignments require an existing integer variable")
        operators = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*"}
        operator = operators.get(type(node.op))
        if operator is None:
            raise UnsupportedPythonSyntax("C supports only integer +=, -=, and *= augmented assignments")
        expression, value_type = self._expr(node.value, assigned, types, integer_values)
        if value_type != "int":
            raise UnsupportedPythonSyntax("C augmented assignments must remain integer-valued")
        combined = ast.BinOp(
            left=ast.Name(id=name, ctx=ast.Load()), op=node.op, right=node.value
        )
        integer_values[name] = self._int_value(combined, integer_values)
        return f"{name} {operator}= {expression};"

    def _while_statement(self, node: ast.While, assigned: set[str], types: dict[str, str],
                         integer_values: dict[str, int]) -> list[str]:
        if node.orelse:
            raise UnsupportedPythonSyntax("while/else statements are not supported in C")
        if not node.body:
            raise UnsupportedPythonSyntax("Empty C while bodies are not supported")
        modified_names: set[str] = set()
        condition_names = {
            item.id for item in ast.walk(node.test)
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
        }
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                    raise UnsupportedPythonSyntax("C while assignments must target one existing integer variable")
                name = statement.targets[0].id
                if name not in assigned or types.get(name) != "int":
                    raise UnsupportedPythonSyntax("C while bodies may only update existing integer variables")
                modified_names.add(name)
            elif isinstance(statement, ast.AugAssign):
                if not isinstance(statement.target, ast.Name):
                    raise UnsupportedPythonSyntax("C while augmented assignments must target one existing integer variable")
                name = statement.target.id
                if (name not in assigned or types.get(name) != "int"
                        or not isinstance(statement.op, (ast.Add, ast.Sub, ast.Mult))):
                    raise UnsupportedPythonSyntax("C while loops support only integer +=/-=/*= updates to existing variables")
                modified_names.add(name)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                if not isinstance(statement.value.func, ast.Name) or statement.value.func.id != "print":
                    raise UnsupportedPythonSyntax("C while bodies may contain only print() or integer assignments")
            elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                  and isinstance(statement.value.value, str)):
                continue
            else:
                raise UnsupportedPythonSyntax("C while bodies may contain only print() or integer assignments")

        facts = dict(integer_values)
        initial_condition = self._while_condition_value(node.test, assigned, types, facts)
        if initial_condition and not condition_names.intersection(modified_names):
            raise UnsupportedPythonSyntax("C while loop does not update its condition variables and cannot be proven to terminate")

        def render_body(values: dict[str, int]) -> list[str]:
            rendered: list[str] = []
            local_values = dict(values)
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    name = statement.targets[0].id
                    expression, value_type = self._expr(statement.value, assigned, types, local_values)
                    if value_type != "int":
                        raise UnsupportedPythonSyntax("C while assignments must remain integer-valued")
                    local_values[name] = self._int_value(statement.value, local_values)
                    rendered.append(f"{name} = {expression};")
                elif isinstance(statement, ast.AugAssign):
                    rendered.append(self._augmented_assignment(statement, assigned, types, local_values))
                elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    rendered.extend(self._print(statement.value, assigned, types, local_values))
                elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                      and isinstance(statement.value.value, str)):
                    continue
            if not rendered:
                raise UnsupportedPythonSyntax("C while bodies must contain at least one print() or integer assignment")
            return rendered

        rendered_body = render_body(integer_values)
        iterations = 0
        while self._while_condition_value(node.test, assigned, types, facts):
            if iterations >= 10_000:
                raise UnsupportedPythonSyntax("C while loop could not be proven to terminate within 10000 iterations")
            previous_facts = dict(facts)
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    name = statement.targets[0].id
                    _, value_type = self._expr(statement.value, assigned, types, facts)
                    if value_type != "int":
                        raise UnsupportedPythonSyntax("C while assignments must remain integer-valued")
                    facts[name] = self._int_value(statement.value, facts)
                elif isinstance(statement, ast.AugAssign):
                    self._augmented_assignment(statement, assigned, types, facts)
                elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    self._print(statement.value, assigned, types, facts)
            iterations += 1
            if facts == previous_facts and self._while_condition_value(node.test, assigned, types, facts):
                raise UnsupportedPythonSyntax("C while loop made no progress toward termination")
        integer_values.clear()
        integer_values.update(facts)
        condition = self._condition(node.test, assigned, types, integer_values)
        rendered = [f"while ({condition}) {{"]
        rendered.extend("    " + line for line in rendered_body)
        rendered.append("}")
        return rendered

    def _for_statement(self, node: ast.For, assigned: set[str], types: dict[str, str],
                       integer_values: dict[str, int], loop_variables: set[str]) -> list[str]:
        if not isinstance(node.target, ast.Name):
            raise UnsupportedPythonSyntax("range() loop targets must be simple variable names")
        name = node.target.id
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                or name in _RESERVED or name in _BUILTINS
                or name.startswith("__")
                or (name.startswith("_") and len(name) > 1 and name[1].isupper())):
            raise UnsupportedPythonSyntax(f"Loop variable '{name}' is not a supported C identifier")
        if name in assigned:
            raise UnsupportedPythonSyntax("range() loop variables cannot shadow assigned variables")
        if node.orelse:
            raise UnsupportedPythonSyntax("for/else statements are not supported in C")
        if (not isinstance(node.iter, ast.Call) or not isinstance(node.iter.func, ast.Name)
                or node.iter.func.id != "range"):
            raise UnsupportedPythonSyntax("Only range() loops are supported in C")
        call = node.iter
        if call.keywords or len(call.args) not in {1, 2, 3}:
            raise UnsupportedPythonSyntax("range() supports one, two, or three positional integer arguments")
        rendered_args: list[str] = []
        values: list[int] = []
        for argument in call.args:
            expression, value_type = self._expr(argument, assigned, types, integer_values)
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
        if not node.body:
            raise UnsupportedPythonSyntax("Empty range() loop bodies are not supported in C")

        facts_before_loop = dict(integer_values)
        assigned.add(name)
        types[name] = "int"
        rendered_body: list[str] | None = None
        validation_values = list(actual_range) if count else [start_value]
        for loop_value in validation_values:
            integer_values[name] = loop_value
            body_lines: list[str] = []
            for statement in node.body:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    body_lines.extend(self._print(statement.value, assigned, types, integer_values))
                elif isinstance(statement, ast.Assign):
                    if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                        raise UnsupportedPythonSyntax("C range() assignments must target one existing integer variable")
                    target = statement.targets[0].id
                    if target == name:
                        raise UnsupportedPythonSyntax("C range() loop index reassignment is not supported")
                    if target not in assigned or types.get(target) != "int":
                        raise UnsupportedPythonSyntax("C range() assignments must target existing integer variables")
                    expression, value_type = self._expr(statement.value, assigned, types, integer_values)
                    if value_type != "int":
                        raise UnsupportedPythonSyntax("C range() assignments must remain integer-valued")
                    integer_values[target] = self._int_value(statement.value, integer_values)
                    body_lines.append(f"{target} = {expression};")
                elif isinstance(statement, ast.AugAssign):
                    if not isinstance(statement.target, ast.Name):
                        raise UnsupportedPythonSyntax("C range() augmented assignments must target one existing integer variable")
                    if statement.target.id == name:
                        raise UnsupportedPythonSyntax("C range() loop index reassignment is not supported")
                    if types.get(statement.target.id) != "int":
                        raise UnsupportedPythonSyntax("C range() augmented assignments support existing integer variables only")
                    body_lines.append(self._augmented_assignment(
                        statement, assigned, types, integer_values
                    ))
                elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                      and isinstance(statement.value.value, str)):
                    continue
                else:
                    raise UnsupportedPythonSyntax(
                        "C range() loop bodies may contain only print() calls and integer assignments"
                    )
            if not body_lines:
                raise UnsupportedPythonSyntax("Empty range() loop bodies are not supported in C")
            if rendered_body is None:
                rendered_body = body_lines

        if count == 0:
            assigned.discard(name)
            types.pop(name, None)
            integer_values.clear()
            integer_values.update(facts_before_loop)
            integer_values.pop(name, None)
            return []
        last_value = actual_range[-1]
        next_value = last_value + step_value
        if not _INT_MIN <= next_value <= _INT_MAX:
            raise UnsupportedPythonSyntax("range() loop counter could overflow the signed 32-bit C integer range")
        operator = "<" if step_value > 0 else ">"
        rendered = [
            f"int32_t {name} = {start_expr};",
            f"while ({name} {operator} {stop_expr}) {{",
        ]
        rendered.extend("    " + line for line in (rendered_body or []))
        rendered.append(f"    {name} += {step_expr};")
        rendered.append("}")
        rendered.append(f"{name} = {last_value};")
        integer_values[name] = last_value
        loop_variables.add(name)
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
        loop_variables: set[str] = set()
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
            "Deterministic Python-to-C supports one file, signed 32-bit integer arithmetic, simple string and boolean values, abs(), positional print(), print-only if/elif/else chains with bounded scalar conditions, bounded range() loops with print calls and existing-integer assignments/augmented assignments, and statically simulated while loops that update existing integer variables.",
            "Conditional assignments, string concatenation, str(), nested control flow, while/else, imports, functions, classes, collections, and full-project migration are not supported by this subset.",
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
            elif isinstance(node, ast.While):
                statements.extend(self._while_statement(node, assigned, types, integer_values))
            elif isinstance(node, ast.For):
                statements.extend(self._for_statement(node, assigned, types, integer_values, loop_variables))
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")

        unused = sorted(assigned - referenced - loop_variables)
        if unused:
            raise UnsupportedPythonSyntax("Assigned variable(s) are never used: " + ", ".join(unused))
        includes = "#include <inttypes.h>\n#include <stdbool.h>\n#include <stdint.h>\n#include <stdio.h>\n#include <string.h>\n"
        if uses_abs:
            includes += "#include <stdlib.h>\n"
        body = "\n".join("    " + statement for statement in statements)
        source = includes + "\nint main(void) {\n" + body + ("\n" if body else "") + "    return 0;\n}\n"
        return [GeneratedArtifact(PurePosixPath(unit.relative_path).with_suffix(".c").as_posix(), source)]
