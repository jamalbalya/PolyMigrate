"""Deterministic JavaScript-to-Python translator for a deliberately narrow scalar subset.

Supported statements: const/let/var scalar declarations, same-type reassignment of
existing let/var bindings, console.log() with scalar expressions, and bounded-shape
if/else branches with scalar comparisons and print-only bodies. Unsupported syntax
is rejected rather than guessed; source text is parsed and never executed.
"""
from __future__ import annotations

import ast
import keyword
import re
from pathlib import PurePosixPath
from typing import Any

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_MAX_SAFE_INTEGER = 2**53 - 1
_RESERVED_NAMES = set(keyword.kwlist) | {
    "print", "str", "int", "bool", "len", "abs", "range", "None", "True", "False",
    "console", "await", "break", "case", "catch", "class", "continue", "debugger",
    "default", "delete", "do", "else", "export", "extends", "finally", "for",
    "function", "if", "import", "in", "instanceof", "new", "return", "super",
    "switch", "this", "throw", "try", "typeof", "var", "void", "while", "with",
    "yield", "enum", "implements", "interface", "package", "private", "protected",
    "public", "null", "true", "false", "const", "let", "static",
}
_TOKEN = re.compile(
    r"(?P<SPACE>[ \t\r]+)|(?P<NEWLINE>\n+)|(?P<COMMENT>//[^\n]*|/\*[\s\S]*?\*/)|"
    r"""(?P<STRING>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|"""
    r"(?P<NUMBER>0|[1-9][0-9]*)|"
    r"(?P<IDENT>[A-Za-z_$][A-Za-z0-9_$]*)|"
    r"(?P<OP>===|!==|==|!=|&&|\|\||[{}();,:.+\-*=/<>!])"
)


class UnsupportedJavaScriptSyntax(ValueError):
    """Raised when JavaScript syntax is outside the explicitly supported subset."""


class _Parser:
    def __init__(self, source: str, *, allow_type_annotations: bool = False) -> None:
        self.allow_type_annotations = allow_type_annotations
        self.tokens: list[tuple[str, str]] = []
        offset = 0
        while offset < len(source):
            match = _TOKEN.match(source, offset)
            if match is None:
                raise UnsupportedJavaScriptSyntax(
                    f"Unsupported JavaScript token near character {offset}"
                )
            kind = match.lastgroup
            value = match.group()
            offset = match.end()
            if kind in {"SPACE", "COMMENT"}:
                continue
            if kind is not None:
                self.tokens.append((kind, value))
        self.tokens.append(("EOF", ""))
        self.index = 0
        self.types: dict[str, str] = {}
        self.values: dict[str, Any] = {}
        self.constants: set[str] = set()
        self.loop_variables: set[str] = set()
        self.dynamic_references: set[str] = set()
        self.output: list[str] = []

    def _peek(self, value: str | None = None) -> bool:
        kind, token = self.tokens[self.index]
        return token == value if value is not None else kind == "EOF"

    def _take(self, value: str | None = None) -> tuple[str, str]:
        item = self.tokens[self.index]
        if value is not None and item[1] != value:
            raise UnsupportedJavaScriptSyntax(f"Expected {value!r}, found {item[1]!r}")
        self.index += 1
        return item

    def _separators(self) -> None:
        while self.tokens[self.index][0] == "NEWLINE" or self._peek(";"):
            self.index += 1

    def _identifier(self) -> str:
        kind, name = self._take()
        if kind != "IDENT" or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise UnsupportedJavaScriptSyntax("Only ordinary ASCII identifiers are supported")
        if name in _RESERVED_NAMES:
            raise UnsupportedJavaScriptSyntax(f"Identifier {name!r} conflicts with Python syntax or builtins")
        return name

    def _statement_end(self) -> None:
        if self._peek(";"):
            self.index += 1
        if self.tokens[self.index][0] not in {"NEWLINE", "EOF"} and not self._peek("}"):
            raise UnsupportedJavaScriptSyntax(
                f"Expected a statement boundary, found {self.tokens[self.index][1]!r}"
            )

    def _block(self) -> list[str]:
        self._take("{")
        self._separators()
        body: list[str] = []
        while not self._peek("}"):
            if self._peek():
                raise UnsupportedJavaScriptSyntax("Unclosed JavaScript block")
            kind, value = self.tokens[self.index]
            if kind != "IDENT" or value != "console":
                raise UnsupportedJavaScriptSyntax("Conditional bodies may contain console.log() statements only")
            start = len(self.output)
            self._statement()
            body.extend(self.output[start:])
            del self.output[start:]
            self._separators()
        self._take("}")
        return body

    def _for_statement(self) -> None:
        self._take("for")
        self._take("(")
        if not self._peek("let"):
            raise UnsupportedJavaScriptSyntax("Only for-loops with a let integer initializer are supported")
        self._take("let")
        name = self._identifier()
        if name in self.types:
            raise UnsupportedJavaScriptSyntax(f"Loop variable {name!r} shadows an existing binding")
        self._take("=")
        start_expr, start_type, start_value = self._expression()
        if start_type != "int":
            raise UnsupportedJavaScriptSyntax("For-loop start must be a statically known integer")
        self._take(";")
        condition_name = self._identifier()
        if condition_name != name:
            raise UnsupportedJavaScriptSyntax("For-loop condition must compare its loop variable")
        operator = self._take()[1]
        if operator not in {"<", "<=", ">", ">="}:
            raise UnsupportedJavaScriptSyntax("For-loop condition must use <, <=, >, or >=")
        bound_expr, bound_type, bound_value = self._expression()
        if bound_type != "int":
            raise UnsupportedJavaScriptSyntax("For-loop bound must be a statically known integer")
        self._take(";")
        increment_name = self._identifier()
        if increment_name != name:
            raise UnsupportedJavaScriptSyntax("For-loop increment must update its loop variable")
        if self._peek("+"):
            self._take("+")
            self._take("+")
            step = 1
        elif self._peek("-"):
            self._take("-")
            self._take("-")
            step = -1
        else:
            raise UnsupportedJavaScriptSyntax("For-loop increment must be i++ or i--")
        if operator in {"<", "<="} and step != 1:
            raise UnsupportedJavaScriptSyntax("Ascending loop conditions require i++")
        if operator in {">", ">="} and step != -1:
            raise UnsupportedJavaScriptSyntax("Descending loop conditions require i--")
        self._take(")")

        stop = bound_value
        if operator == "<=":
            stop += 1
        elif operator == ">=":
            stop -= 1
        iteration_count = len(range(start_value, stop, step))
        if iteration_count > 10_000:
            raise UnsupportedJavaScriptSyntax("For-loop exceeds the 10,000-iteration safety limit")

        self.types[name] = "int"
        self.values[name] = start_value
        self.loop_variables.add(name)
        body = self._block()
        # A loop variable is dynamic. It may be logged directly, but arithmetic
        # involving it is rejected unless a future analysis proves bounds.
        self.types.pop(name, None)
        self.values.pop(name, None)
        self.loop_variables.discard(name)
        self.dynamic_references.clear()
        self.output.append(f"for {name} in range({start_expr}, {stop}, {step}):")
        self.output.extend(f"    {line}" for line in body) if body else self.output.append("    pass")

    def _condition(self) -> tuple[str, str, Any]:
        """Parse scalar truthiness, comparisons, negation, and short-circuit logic."""
        return self._condition_or()

    def _condition_or(self) -> tuple[str, str, Any]:
        left_expr, _left_type, left_value = self._condition_and()
        while self._peek("||"):
            self._take("||")
            right_expr, _right_type, right_value = self._condition_and()
            left_expr = f"({left_expr} or {right_expr})"
            left_value = bool(left_value) or bool(right_value)
        return left_expr, "bool", left_value

    def _condition_and(self) -> tuple[str, str, Any]:
        left_expr, _left_type, left_value = self._condition_not()
        while self._peek("&&"):
            self._take("&&")
            right_expr, _right_type, right_value = self._condition_not()
            left_expr = f"({left_expr} and {right_expr})"
            left_value = bool(left_value) and bool(right_value)
        return left_expr, "bool", left_value

    def _condition_not(self) -> tuple[str, str, Any]:
        if self._peek("!"):
            self._take("!")
            expression, _value_type, value = self._condition_not()
            return f"(not {expression})", "bool", not bool(value)
        left_expr, left_type, left_value = self._expression()
        operators = {"===", "!==", "==", "!=", "<", "<=", ">", ">="}
        if self.tokens[self.index][1] not in operators:
            return left_expr, left_type, left_value
        operator = self._take()[1]
        right_expr, right_type, right_value = self._expression()
        if left_type != right_type:
            raise UnsupportedJavaScriptSyntax("Condition comparisons require operands of the same type")
        if operator in {"<", "<=", ">", ">="} and left_type != "int":
            raise UnsupportedJavaScriptSyntax("Ordering comparisons are supported for integers only")
        py_operator = {"===": "==", "!==": "!=", "==": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}[operator]
        result = {
            "==": left_value == right_value,
            "!=": left_value != right_value,
            "<": left_value < right_value if left_type == "int" else False,
            "<=": left_value <= right_value if left_type == "int" else False,
            ">": left_value > right_value if left_type == "int" else False,
            ">=": left_value >= right_value if left_type == "int" else False,
        }[py_operator]
        return f"({left_expr} {py_operator} {right_expr})", "bool", result

    def _if_statement(self) -> None:
        """Translate a flat if / else-if / else chain with print-only bodies."""
        self._take("if")
        branches: list[tuple[str, list[str]]] = []
        else_body: list[str] | None = None

        while True:
            self._take("(")
            condition, _condition_type, _condition_value = self._condition()
            self._take(")")
            branches.append((condition, self._block()))

            while self.tokens[self.index][0] == "NEWLINE":
                self.index += 1
            if self.tokens[self.index] != ("IDENT", "else"):
                break
            self.index += 1
            while self.tokens[self.index][0] == "NEWLINE":
                self.index += 1
            if self.tokens[self.index] == ("IDENT", "if"):
                self.index += 1
                continue
            else_body = self._block()
            break

        for index, (condition, body) in enumerate(branches):
            keyword = "if" if index == 0 else "elif"
            self.output.append(f"{keyword} {condition}:")
            self.output.extend(f"    {line}" for line in body) if body else self.output.append("    pass")
        if else_body is not None:
            self.output.append("else:")
            self.output.extend(f"    {line}" for line in else_body) if else_body else self.output.append("    pass")

    def parse(self) -> str:
        self._separators()
        while not self._peek():
            self._statement()
            self._separators()
        if not self.output:
            raise UnsupportedJavaScriptSyntax("No supported JavaScript statements were found")
        return "\n".join(self.output) + "\n"

    def _statement(self) -> None:
        kind, value = self.tokens[self.index]
        if kind == "IDENT" and value == "if":
            self._if_statement()
            return

        if kind == "IDENT" and value == "for":
            self._for_statement()
            return

        if kind == "IDENT" and value in {"const", "let", "var"}:
            declaration = value
            self.index += 1
            name = self._identifier()
            if name in self.types:
                raise UnsupportedJavaScriptSyntax(f"Duplicate declaration for {name!r} is not supported")
            declared_type = None
            if self._peek(":"):
                if not self.allow_type_annotations:
                    raise UnsupportedJavaScriptSyntax("Type annotations are only supported in TypeScript mode")
                self._take(":")
                type_kind, type_name = self._take()
                declared_type = {"number": "int", "string": "string", "boolean": "bool"}.get(type_name)
                if type_kind != "IDENT" or declared_type is None:
                    raise UnsupportedJavaScriptSyntax("Only number, string, and boolean type annotations are supported")
            self._take("=")
            expression, value_type, known_value = self._expression()
            if declared_type is not None and declared_type != value_type:
                raise UnsupportedJavaScriptSyntax(f"Type annotation for {name!r} does not match its initializer")
            self.types[name] = value_type
            self.values[name] = known_value
            if declaration == "const":
                self.constants.add(name)
            self.output.append(f"{name} = {expression}")
            self._statement_end()
            return

        if kind == "IDENT" and value == "console":
            self.index += 1
            self._take(".")
            self._take("log")
            self._take("(")
            expressions: list[str] = []
            if not self._peek(")"):
                while True:
                    expression, _value_type, _known_value = self._expression()
                    expressions.append(expression)
                    if not self._peek(","):
                        break
                    self.index += 1
            self._take(")")
            if expressions:
                values = ", ".join(expressions)
                self.output.append(
                    f"print(*[(str(value).lower() if isinstance(value, bool) else value) "
                    f"for value in [{values}]])"
                )
            else:
                self.output.append("print()")
            self._statement_end()
            return

        if kind == "IDENT":
            name = self._identifier()
            if name not in self.types:
                raise UnsupportedJavaScriptSyntax(f"Assignment to undeclared variable {name!r} is not supported")
            if name in self.constants:
                raise UnsupportedJavaScriptSyntax(f"Assignment to const binding {name!r} is not supported")
            self._take("=")
            expression, value_type, known_value = self._expression()
            if value_type != self.types[name]:
                raise UnsupportedJavaScriptSyntax(f"Type-changing assignment to {name!r} is not supported")
            self.values[name] = known_value
            self.output.append(f"{name} = {expression}")
            self._statement_end()
            return

        raise UnsupportedJavaScriptSyntax(f"Unsupported statement starting with {value!r}")

    def _expression(self) -> tuple[str, str, Any]:
        return self._additive()

    def _additive(self) -> tuple[str, str, Any]:
        before_dynamic = set(self.dynamic_references)
        left_expr, left_type, left_value = self._multiplicative()
        while self._peek("+") or self._peek("-"):
            if self.dynamic_references - before_dynamic:
                raise UnsupportedJavaScriptSyntax("Arithmetic on a loop variable is not supported")
            operator = self._take()[1]
            right_expr, right_type, right_value = self._multiplicative()
            if self.dynamic_references - before_dynamic:
                raise UnsupportedJavaScriptSyntax("Arithmetic on a loop variable is not supported")
            if left_type != right_type:
                raise UnsupportedJavaScriptSyntax("Mixed-type arithmetic and JavaScript coercion are not supported")
            if operator == "+" and left_type == "string":
                left_value = left_value + right_value
            elif left_type == "int":
                left_value = left_value + right_value if operator == "+" else left_value - right_value
                self._check_integer(left_value)
            else:
                raise UnsupportedJavaScriptSyntax("Only integer arithmetic and string concatenation are supported")
            left_expr = f"({left_expr} {operator} {right_expr})"
        return left_expr, left_type, left_value

    def _multiplicative(self) -> tuple[str, str, Any]:
        before_dynamic = set(self.dynamic_references)
        left_expr, left_type, left_value = self._unary()
        while self._peek("*"):
            if self.dynamic_references - before_dynamic:
                raise UnsupportedJavaScriptSyntax("Arithmetic on a loop variable is not supported")
            self.index += 1
            right_expr, right_type, right_value = self._unary()
            if self.dynamic_references - before_dynamic:
                raise UnsupportedJavaScriptSyntax("Arithmetic on a loop variable is not supported")
            if left_type != "int" or right_type != "int":
                raise UnsupportedJavaScriptSyntax("Multiplication supports integer operands only")
            left_value *= right_value
            self._check_integer(left_value)
            left_expr = f"({left_expr} * {right_expr})"
        return left_expr, left_type, left_value

    def _unary(self) -> tuple[str, str, Any]:
        if self._peek("+") or self._peek("-"):
            operator = self._take()[1]
            expression, value_type, value = self._unary()
            if value_type != "int":
                raise UnsupportedJavaScriptSyntax("Unary plus/minus supports integers only")
            value = value if operator == "+" else -value
            self._check_integer(value)
            return f"({operator}{expression})", "int", value
        return self._primary()

    @staticmethod
    def _check_integer(value: Any) -> None:
        if type(value) is not int or abs(value) > _MAX_SAFE_INTEGER:
            raise UnsupportedJavaScriptSyntax("Integer expression exceeds JavaScript's safe-integer range")

    def _primary(self) -> tuple[str, str, Any]:
        kind, value = self.tokens[self.index]
        if kind == "NUMBER":
            self.index += 1
            number = int(value)
            self._check_integer(number)
            return value, "int", number
        if kind == "STRING":
            self.index += 1
            if "\\" in value[1:-1]:
                raise UnsupportedJavaScriptSyntax("Escaped string literals are not yet supported")
            try:
                decoded = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                raise UnsupportedJavaScriptSyntax("String escape is outside the supported literal subset") from None
            if not isinstance(decoded, str):
                raise UnsupportedJavaScriptSyntax("Only string literals are supported")
            return repr(decoded), "string", decoded
        if kind == "IDENT" and value in {"true", "false"}:
            self.index += 1
            boolean = value == "true"
            return ("True" if boolean else "False"), "bool", boolean
        if kind == "IDENT":
            name = self._identifier()
            if name not in self.types:
                raise UnsupportedJavaScriptSyntax(f"Variable {name!r} is used before assignment")
            if name in self.loop_variables:
                self.dynamic_references.add(name)
            return name, self.types[name], self.values[name]
        if value == "(":
            self.index += 1
            expression, value_type, known_value = self._expression()
            self._take(")")
            return f"({expression})", value_type, known_value
        raise UnsupportedJavaScriptSyntax(f"Unsupported expression token {value!r}")


class JavaScriptToPythonTargetAdapter:
    """Translate a constrained JavaScript scalar subset to standalone Python files."""

    language_id = "python"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict[str, Any]) -> list[GeneratedArtifact]:
        if project.language_id != "javascript":
            raise ValueError("JavaScript-to-Python adapter requires a JavaScript source project")
        if not project.units:
            raise ValueError("No JavaScript source units were supplied")
        self.warnings = [
            "Deterministic JavaScript-to-Python subset only: functions, modules/imports, objects, arrays, while-loops, nested control flow, async code, and dynamic coercion are unsupported; if/else branches may contain console.log() only, and bounded for-loops may log scalar values.",
            "Generated output is limited to the explicitly supported scalar cases; project-level behavior is not implied.",
        ]
        artifacts: list[GeneratedArtifact] = []
        for unit in project.units:
            suffix = PurePosixPath(unit.relative_path).suffix.lower()
            if suffix not in {".js", ".mjs", ".cjs"}:
                raise UnsupportedJavaScriptSyntax(f"Unsupported JavaScript source extension: {suffix or '(none)'}")
            output_path = str(PurePosixPath(unit.relative_path).with_suffix(".py"))
            generated = _Parser(unit.source_text).parse()
            artifacts.append(GeneratedArtifact(output_path, generated))
        return artifacts
