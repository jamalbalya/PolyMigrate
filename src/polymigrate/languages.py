"""Extensible language metadata registry; metadata is not a code generator."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    id: str
    display_name: str
    extensions: tuple[str, ...]


class LanguageRegistry:
    def __init__(self, languages: tuple[Language, ...] | None = None) -> None:
        defaults = languages or (
            Language("python", "Python", (".py", ".pyi")),
            Language("go", "Go", (".go",)),
            Language("javascript", "JavaScript", (".js", ".mjs", ".cjs", ".jsx")),
            Language("typescript", "TypeScript", (".ts", ".mts", ".cts", ".tsx")),
            Language("java", "Java", (".java",)),
            Language("rust", "Rust", (".rs",)),
            Language("csharp", "C#", (".cs",)),
            Language("cpp", "C++", (".cc", ".cpp", ".cxx", ".hpp", ".h")),
            Language("c", "C", (".c", ".h")),
            Language("kotlin", "Kotlin", (".kt", ".kts")),
            Language("ruby", "Ruby", (".rb",)),
            Language("php", "PHP", (".php",)),
            Language("swift", "Swift", (".swift",)),
        )
        self._languages: dict[str, Language] = {}
        for language in defaults:
            self.register(language)

    def register(self, language: Language) -> None:
        normalized = language.id.strip().lower()
        if not normalized or normalized != language.id:
            raise ValueError("Language id must be non-empty lowercase canonical text")
        if normalized in self._languages:
            raise ValueError(f"Language already registered: {normalized}")
        self._languages[normalized] = language

    def get(self, language_id: str) -> Language:
        try:
            return self._languages[language_id.strip().lower()]
        except KeyError as exc:
            supported = ", ".join(sorted(self._languages))
            raise ValueError(f"Unsupported language '{language_id}'. Supported languages: {supported}") from exc

    def all(self) -> tuple[Language, ...]:
        return tuple(self._languages[key] for key in sorted(self._languages))
