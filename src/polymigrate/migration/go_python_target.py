"""Deterministic Go-to-Python translator for a narrow scalar main-package subset."""
from __future__ import annotations

import ast
import keyword
import re
from pathlib import PurePosixPath
from typing import Any

from polymigrate.migration.pipeline import GeneratedArtifact, SourceProject

_MIN_INT64 = -(2**63)
_MAX_INT64 = 2**63 - 1
_RESERVED_NAMES = set(keyword.kwlist) | {
    "print", "str", "int", "bool", "len", "abs", "range", "None", "True", "False",
    "package", "import", "func", "var", "const", "type", "struct", "interface",
    "map", "chan", "select", "go", "defer", "return", "if", "else", "switch",
    "case", "default", "for", "break", "continue", "fallthrough", "goto", "range",
    "nil", "true", "false", "iota", "string", "int8", "int16", "int32", "int64",
    "uint", "uint8", "uint16", "uint32", "uint64", "uintptr", "byte", "rune",
    "float32", "float64", "complex64", "complex128", "error", "fmt",
}
_TOKEN = re.compile(
    r"(?P<SPACE>[ \t\r]+)|(?P<NEWLINE>\n+)|(?P<COMMENT>//[^\n]*|/\*[\s\S]*?\*/)|"
    r"""(?P<STRING>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|"""
    r"(?P<NUMBER>0|[1-9][0-9]*)|"
    r"(?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)|"
    r"(?P<OP>:=|==|!=|<=|>=|&&|\|\||[{}();,.+\-*=/<>!])"
)


class UnsupportedGoSyntax(ValueError):
    """Raised when Go syntax is outside the explicitly supported subset."""


class _Parser:
    def __init__(self, source: str) -> None:
        self.tokens: list[tuple[str, str]] = []
        offset = 0
        while offset < len(source):
            match = _TOKEN.match(source, offset)
            if match is None:
                raise UnsupportedGoSyntax(f"Unsupported Go token near character {offset}")
            kind, value = match.lastgroup, match.group()
            offset = match.end()
            if kind in {"SPACE", "COMMENT"}:
                continue
            if kind is not None:
                self.tokens.append((kind, value))
        self.tokens.append(("EOF", ""))
        self.index = 0
        self.types: dict[str, str] = {}
        self.values: dict[str, Any] = {}
        self.reads: set[str] = set()
        self.output: list[str] = []
        self.imported_fmt = False
        self.used_fmt = False

    def _peek(self, value: str | None = None) -> bool:
        kind, token = self.tokens[self.index]
        return token == value if value is not None else kind == "EOF"

    def _take(self, value: str | None = None) -> tuple[str, str]:
        item = self.tokens[self.index]
        if value is not None and item[1] != value:
            raise UnsupportedGoSyntax(f"Expected {value!r}, found {item[1]!r}")
        self.index += 1
        return item

    def _separators(self) -> None:
        while self.tokens[self.index][0] == "NEWLINE" or self._peek(";"):
            self.index += 1

    def _identifier(self) -> str:
        kind, name = self._take()
        if kind != "IDENT" or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise UnsupportedGoSyntax("Only ordinary ASCII Go identifiers are supported")
        if name in _RESERVED_NAMES or name == "_":
            raise UnsupportedGoSyntax(f"Identifier {name!r} is outside the supported subset")
        return name

    def _statement_end(self) -> None:
        if self._peek(";"):
            self.index += 1
        if self.tokens[self.index][0] not in {"NEWLINE", "EOF"} and not self._peek("}"):
            raise UnsupportedGoSyntax(
                f"Expected a statement boundary, found {self.tokens[self.index][1]!r}"
            )

    def parse(self) -> str:
        self._separators()
        self._take("package")
        package_name = self._take()
        if package_name != ("IDENT", "main"):
            raise UnsupportedGoSyntax("Only package main is supported")
        self._statement_end()
        self._separators()

        if self._peek("import"):
            self._take("import")
            kind, literal = self._take()
            if kind != "STRING" or literal not in {'"fmt"', "'fmt'"}:
                raise UnsupportedGoSyntax('Only the single import "fmt" is supported')
            self.imported_fmt = True
            self._statement_end()
            self._separators()

        self._take("func")
        self._take("main")
        self._take("(")
        self._take(")")
        self._take("{")
        self._separators()
        while not self._peek("}"):
            if self._peek():
                raise UnsupportedGoSyntax("Unclosed main function")
            self._statement()
            self._separators()
        self._take("}")
        self._separators()
        if not self._peek():
            raise UnsupportedGoSyntax("Only a single func main() entry point is supported")
        if self.used_fmt and not self.imported_fmt:
            raise UnsupportedGoSyntax('fmt.Println requires import "fmt"')
        if self.imported_fmt and not self.used_fmt:
            raise UnsupportedGoSyntax('Go rejects an unused fmt import')
        unused = sorted(set(self.types) - self.reads)
        if unused:
            raise UnsupportedGoSyntax(f"Go local variables must be used; unused: {', '.join(unused)}")
        if not self.output:
            self.output.append("pass")
        return "\n".join(self.output) + "\n"

    def _statement(self) -> None:
        kind, value = self.tokens[self.index]
        if kind == "IDENT" and value == "fmt":
            self._take("fmt")
            self._take(".")
            self._take("Println")
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
            self.used_fmt = True
            self._statement_end()
            return

        if kind == "IDENT" and value == "var":
            self._take("var")
            name = self._identifier()
            if name in self.types:
                raise UnsupportedGoSyntax(f"Duplicate declaration for {name!r} is not supported")
            type_kind, declared_type = self._take()
            if type_kind != "IDENT" or declared_type not in {"int", "string", "bool"}:
                raise UnsupportedGoSyntax("Only int, string, and bool var declarations are supported")
            self._take("=")
            expression, value_type, known_value = self._expression()
            if value_type != declared_type:
                raise UnsupportedGoSyntax(f"Declared type for {name!r} does not match its initializer")
            self.types[name] = value_type
            self.values[name] = known_value
            self.output.append(f"{name} = {expression}")
            self._statement_end()
            return

        if kind == "IDENT":
            name = self._identifier()
            if self._peek(":="):
                if name in self.types:
                    raise UnsupportedGoSyntax(f"Short declaration redeclares {name!r}")
                self._take(":=")
                expression, value_type, known_value = self._expression()
                self.types[name] = value_type
                self.values[name] = known_value
                self.output.append(f"{name} = {expression}")
                self._statement_end()
                return
            if name not in self.types:
                raise UnsupportedGoSyntax(f"Assignment to undeclared variable {name!r} is not supported")
            self._take("=")
            expression, value_type, known_value = self._expression()
            if value_type != self.types[name]:
                raise UnsupportedGoSyntax(f"Type-changing assignment to {name!r} is not supported")
            self.values[name] = known_value
            self.output.append(f"{name} = {expression}")
            self._statement_end()
            return

        raise UnsupportedGoSyntax(f"Unsupported statement starting with {value!r}")

    def _expression(self) -> tuple[str, str, Any]:
        return self._additive()

    def _additive(self) -> tuple[str, str, Any]:
        left_expr, left_type, left_value = self._multiplicative()
        while self._peek("+") or self._peek("-"):
            operator = self._take()[1]
            right_expr, right_type, right_value = self._multiplicative()
            if left_type != right_type:
                raise UnsupportedGoSyntax("Mixed-type arithmetic and Go coercion are not supported")
            if operator == "+" and left_type == "string":
                left_value = left_value + right_value
            elif left_type == "int":
                left_value = left_value + right_value if operator == "+" else left_value - right_value
                self._check_integer(left_value)
            else:
                raise UnsupportedGoSyntax("Only integer arithmetic and string concatenation are supported")
            left_expr = f"({left_expr} {operator} {right_expr})"
        return left_expr, left_type, left_value

    def _multiplicative(self) -> tuple[str, str, Any]:
        left_expr, left_type, left_value = self._unary()
        while self._peek("*"):
            self.index += 1
            right_expr, right_type, right_value = self._unary()
            if left_type != "int" or right_type != "int":
                raise UnsupportedGoSyntax("Multiplication supports integer operands only")
            left_value *= right_value
            self._check_integer(left_value)
            left_expr = f"({left_expr} * {right_expr})"
        return left_expr, left_type, left_value

    def _unary(self) -> tuple[str, str, Any]:
        if self._peek("+") or self._peek("-"):
            operator = self._take()[1]
            expression, value_type, value = self._unary()
            if value_type != "int":
                raise UnsupportedGoSyntax("Unary plus/minus supports integers only")
            value = value if operator == "+" else -value
            self._check_integer(value)
            return f"({operator}{expression})", "int", value
        return self._primary()

    @staticmethod
    def _check_integer(value: Any) -> None:
        if type(value) is not int or not _MIN_INT64 <= value <= _MAX_INT64:
            raise UnsupportedGoSyntax("Integer expression exceeds signed 64-bit Go int range")

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
                raise UnsupportedGoSyntax("Escaped string literals are not yet supported")
            try:
                decoded = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                raise UnsupportedGoSyntax("Unsupported Go string literal") from None
            if not isinstance(decoded, str):
                raise UnsupportedGoSyntax("Only string literals are supported")
            return repr(decoded), "string", decoded
        if kind == "IDENT" and value in {"true", "false"}:
            self.index += 1
            boolean = value == "true"
            return ("True" if boolean else "False"), "bool", boolean
        if kind == "IDENT":
            name = self._identifier()
            if name not in self.types:
                raise UnsupportedGoSyntax(f"Variable {name!r} is used before assignment")
            self.reads.add(name)
            return name, self.types[name], self.values[name]
        if value == "(":
            self.index += 1
            expression, value_type, known_value = self._expression()
            self._take(")")
            return f"({expression})", value_type, known_value
        raise UnsupportedGoSyntax(f"Unsupported expression token {value!r}")


class GoToPythonTargetAdapter:
    """Translate a single Go main.go scalar subset to Python."""

    language_id = "python"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def generate(self, project: SourceProject, context: dict[str, Any]) -> list[GeneratedArtifact]:
        if project.language_id != "go":
            raise ValueError("Go-to-Python adapter requires a Go source project")
        if len(project.units) != 1 or project.units[0].relative_path != "main.go":
            raise UnsupportedGoSyntax("Go-to-Python subset currently requires one root main.go file")
        self.warnings = [
            "Deterministic Go-to-Python subset only: a single package main/main.go file with scalar declarations, assignments, integer arithmetic, string concatenation, booleans, and fmt.Println is supported.",
            "Imports other than fmt, functions other than main, control flow, collections, structs, methods, concurrency, and full-project migration are unsupported.",
        ]
        generated = _Parser(project.units[0].source_text).parse()
        return [GeneratedArtifact("main.py", generated)]
