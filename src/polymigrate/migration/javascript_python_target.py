"""Deterministic JavaScript-to-Python translator for a deliberately narrow scalar subset.

Supported statements: const/let/var scalar declarations, same-type reassignment of
existing let/var bindings, and console.log() with scalar expressions. Unsupported
syntax is rejected rather than guessed; source text is parsed and never executed.
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
    r"(?P<OP>===|!==|==|!=|&&|\|\||[{}();,.+\-*=/<>!])"
)


class UnsupportedJavaScriptSyntax(ValueError):
    """Raised when JavaScript syntax is outside the explicitly supported subset."""


class _Parser:
    def __init__(self, source: str) -> None:
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
        if self.tokens[self.index][0] not in {"NEWLINE", "EOF"}:
            raise UnsupportedJavaScriptSyntax(
                f"Expected a statement boundary, found {self.tokens[self.index][1]!r}"
            )

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
        if kind == "IDENT" and value in {"const", "let", "var"}:
            declaration = value
            self.index += 1
            name = self._identifier()
            if name in self.types:
                raise UnsupportedJavaScriptSyntax(f"Duplicate declaration for {name!r} is not supported")
            self._take("=")
            expression, value_type, known_value = self._expression()
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
        left_expr, left_type, left_value = self._multiplicative()
        while self._peek("+") or self._peek("-"):
            operator = self._take()[1]
            right_expr, right_type, right_value = self._multiplicative()
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
        left_expr, left_type, left_value = self._unary()
        while self._peek("*"):
            self.index += 1
            right_expr, right_type, right_value = self._unary()
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
            "Deterministic JavaScript-to-Python subset only: functions, modules/imports, objects, arrays, control flow, async code, and dynamic coercion are unsupported.",
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
