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
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise UnsupportedPythonSyntax("C# string literals containing lone Unicode surrogates are rejected")
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

    def _condition(self, node: ast.expr, assigned: set[str], types: dict[str, str],
                   integer_values: dict[str, int], uses_boolean_string: list[bool]) -> str:
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return "!(" + self._condition(node.operand, assigned, types, integer_values, uses_boolean_string) + ")"
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            operator = "&&" if isinstance(node.op, ast.And) else "||"
            return "(" + f" {operator} ".join(
                self._condition(item, assigned, types, integer_values, uses_boolean_string)
                for item in node.values
            ) + ")"
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise UnsupportedPythonSyntax("Chained comparisons are not supported in conditions")
            left, left_type = self._expr(node.left, assigned, types, integer_values, uses_boolean_string)
            right, right_type = self._expr(node.comparators[0], assigned, types, integer_values, uses_boolean_string)
            if left_type != right_type:
                raise UnsupportedPythonSyntax("Comparisons require operands of the same known type")
            operator_node = node.ops[0]
            operators = {
                ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<",
                ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=",
            }
            operator = operators.get(type(operator_node))
            if operator is None:
                raise UnsupportedPythonSyntax("Only ==, !=, <, <=, >, and >= comparisons are supported")
            if left_type == "bool" and operator not in {"==", "!="}:
                raise UnsupportedPythonSyntax("Boolean ordering comparisons are not supported")
            if left_type == "string":
                if operator == "==":
                    return f"string.Equals({left}, {right}, StringComparison.Ordinal)"
                if operator == "!=":
                    return f"!string.Equals({left}, {right}, StringComparison.Ordinal)"
                raise UnsupportedPythonSyntax("String ordering comparisons are not supported")
            return f"({left} {operator} {right})"
        expression, value_type = self._expr(node, assigned, types, integer_values, uses_boolean_string)
        if value_type == "bool":
            return expression
        if value_type == "int":
            return f"({expression} != 0)"
        if value_type == "string":
            return f"(!string.IsNullOrEmpty({expression}))"
        raise UnsupportedPythonSyntax("Condition type is not supported")

    def _print_call(self, call: ast.Call, assigned: set[str], types: dict[str, str],
                    integer_values: dict[str, int], uses_boolean_string: list[bool]) -> str:
        if not isinstance(call.func, ast.Name) or call.func.id != "print":
            raise UnsupportedPythonSyntax("Only calls to print() are supported as expression statements")
        if call.keywords or len(call.args) > 32:
            raise UnsupportedPythonSyntax("print() supports at most 32 positional arguments and no keywords")
        expressions = [
            self._expr(arg, assigned, types, integer_values, uses_boolean_string)
            for arg in call.args
        ]
        if not expressions:
            return "Console.WriteLine();"
        uses_boolean_string[0] = True
        values = ", ".join(f"PolymigrateString({expression})" for expression, _ in expressions)
        return f'Console.WriteLine(string.Join(" ", new string[] {{ {values} }}));'

    def _if_statement(self, node: ast.If, assigned: set[str], types: dict[str, str],
                      integer_values: dict[str, int], uses_boolean_string: list[bool]) -> str:
        def render_body(body: list[ast.stmt]) -> list[str]:
            if not body:
                raise UnsupportedPythonSyntax("Empty conditional bodies are not supported")
            rendered: list[str] = []
            for statement in body:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                    rendered.append(self._print_call(
                        statement.value, assigned, types, integer_values, uses_boolean_string
                    ))
                elif (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                      and isinstance(statement.value.value, str)):
                    continue
                else:
                    raise UnsupportedPythonSyntax("C# conditional bodies may contain only print() statements")
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
            condition = self._condition(cursor.test, assigned, types, integer_values, uses_boolean_string)
            keyword = "if" if depth == 1 else "} else if"
            rendered.append(f"{keyword} ({condition}) {{")
            rendered.extend("            " + line for line in render_body(cursor.body))
            if cursor.orelse and len(cursor.orelse) == 1 and isinstance(cursor.orelse[0], ast.If):
                cursor = cursor.orelse[0]
                continue
            if cursor.orelse:
                rendered.append("        } else {")
                rendered.extend("            " + line for line in render_body(cursor.orelse))
            rendered.append("        }")
            break
        return "\n".join(rendered)

    def _for_statement(self, node: ast.For, assigned: set[str], types: dict[str, str],
                       integer_values: dict[str, int], uses_boolean_string: list[bool],
                       referenced_counts: dict[str, int], source_names: set[str],
                       loop_index: int) -> str | None:
        if not isinstance(node.target, ast.Name):
            raise UnsupportedPythonSyntax("range() loop targets must be simple variable names")
        name = node.target.id
        if (not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                or name in _CSHARP_RESERVED or name in _CSHARP_BUILTINS or name.startswith("__")):
            raise UnsupportedPythonSyntax(f"Loop variable '{name}' is not a supported C# identifier")
        if name in assigned:
            raise UnsupportedPythonSyntax("range() loop variables cannot shadow an already assigned variable")
        if node.orelse:
            raise UnsupportedPythonSyntax("for/else statements are not supported")
        if (not isinstance(node.iter, ast.Call) or not isinstance(node.iter.func, ast.Name)
                or node.iter.func.id != "range"):
            raise UnsupportedPythonSyntax("Only range() loops are supported")
        call = node.iter
        if call.keywords or len(call.args) not in {1, 2, 3}:
            raise UnsupportedPythonSyntax("range() supports one, two, or three positional integer arguments")

        rendered_args: list[str] = []
        values: list[int] = []
        for argument in call.args:
            expression, value_type = self._expr(
                argument, assigned, types, integer_values, uses_boolean_string
            )
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
            raise UnsupportedPythonSyntax("Empty range() loop bodies are not supported")

        counter_index = loop_index
        counter_name = f"polymigrateRangeCounter{counter_index}"
        while counter_name in source_names or counter_name in assigned:
            counter_index += 1
            counter_name = f"polymigrateRangeCounter{counter_index}"
        name_loads_inside = sum(
            1 for child in ast.walk(node)
            if isinstance(child, ast.Name) and child.id == name and isinstance(child.ctx, ast.Load)
        )
        referenced_after = referenced_counts.get(name, 0) - name_loads_inside > 0

        loop_name_nodes = [
            child for statement in node.body for child in ast.walk(statement)
            if isinstance(child, ast.Name) and child.id == name and isinstance(child.ctx, ast.Load)
        ]
        for child in loop_name_nodes:
            child.id = counter_name
        assigned.add(counter_name)
        types[counter_name] = "int"
        integer_values[counter_name] = start_value
        validation_values = list(actual_range) if count else [start_value]
        rendered_body: list[str] | None = None
        try:
            for loop_value in validation_values:
                integer_values[counter_name] = loop_value
                body_lines: list[str] = []
                for child in node.body:
                    if isinstance(child, ast.Expr) and isinstance(child.value, ast.Call):
                        body_lines.append(self._print_call(
                            child.value, assigned, types, integer_values, uses_boolean_string
                        ))
                    elif (isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant)
                          and isinstance(child.value.value, str)):
                        continue
                    else:
                        raise UnsupportedPythonSyntax("range() loop bodies may contain only print() statements")
                if not body_lines:
                    raise UnsupportedPythonSyntax("range() loop bodies must contain at least one print() statement")
                if rendered_body is None:
                    rendered_body = body_lines
        finally:
            for child in loop_name_nodes:
                child.id = name
            assigned.discard(counter_name)
            types.pop(counter_name, None)
            integer_values.pop(counter_name, None)

        if count == 0:
            # The loop has no runtime effect. Remove references from its entire
            # AST subtree so unused-variable checks reflect emitted code, not dead code.
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                    referenced_counts[child.id] = referenced_counts.get(child.id, 0) - 1
            return None

        last_value = actual_range[-1]
        next_value = last_value + step_value
        if not _CSHARP_INT_MIN <= next_value <= _CSHARP_INT_MAX:
            raise UnsupportedPythonSyntax("range() loop counter could overflow the signed 32-bit C# integer range")
        operator = "<" if step_value > 0 else ">"
        body = "\n".join("                " + line for line in (rendered_body or []))
        rendered = [
            "{",
            f"            for (int {counter_name} = {start_expr}; {counter_name} {operator} {stop_expr}; {counter_name} += {step_expr}) {{",
            body,
            "            }",
            "        }",
        ]
        if referenced_after:
            rendered.append(f"        int {name} = {last_value};")
            integer_values[name] = last_value
            assigned.add(name)
            types[name] = "int"
        return "\n".join(rendered)

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
        self.warnings = [
            "Deterministic Python-to-C# translation supports single-file assignments, bounded integer/string/boolean expressions, str(), abs(), positional print(), print-only if/elif/else chains, and bounded print-only range() loops.",
            "While loops, branch assignments, nested control flow, functions, imports, classes, collections, and full project migration are not supported by this subset.",
        ]
        assigned: set[str] = set()
        types: dict[str, str] = {}
        integer_values: dict[str, int] = {}
        uses_boolean_string = [False]
        statements: list[str] = []
        referenced_counts: dict[str, int] = {}
        source_names = {reference.id for reference in ast.walk(tree) if isinstance(reference, ast.Name)}
        for reference in ast.walk(tree):
            if isinstance(reference, ast.Name) and isinstance(reference.ctx, ast.Load):
                referenced_counts[reference.id] = referenced_counts.get(reference.id, 0) + 1
        declarations = {"int": "int", "string": "string", "bool": "bool"}

        for statement_index, node in enumerate(tree.body):
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
                statements.append(self._print_call(
                    node.value, assigned, types, integer_values, uses_boolean_string
                ))
            elif isinstance(node, ast.If):
                statements.append(self._if_statement(
                    node, assigned, types, integer_values, uses_boolean_string
                ))
            elif isinstance(node, ast.For):
                loop_statement = self._for_statement(
                    node, assigned, types, integer_values, uses_boolean_string,
                    referenced_counts, source_names, statement_index
                )
                if loop_statement is not None:
                    statements.append(loop_statement)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                continue
            else:
                raise UnsupportedPythonSyntax(f"Unsupported statement syntax: {type(node).__name__}")

        unused = sorted(name for name in assigned if referenced_counts.get(name, 0) <= 0)
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
