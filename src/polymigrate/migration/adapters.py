"""Bounded source inventory with Python AST hints and heuristic structure extraction for other languages."""
from __future__ import annotations
import ast
import hashlib
import os
import re
from pathlib import Path
from typing import Iterable
from polymigrate.migration.pipeline import SourceProject, SourceUnit

_IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build", "target", "vendor", ".next"}

_SYMBOL_PATTERNS = {
    "go": re.compile(r"(?m)^\s*(?:func\s+(?:\([^)]*\)\s*)?|type\s+)([A-Za-z_]\w*)"),
    "javascript": re.compile(r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)"),
    "typescript": re.compile(r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)"),
    "java": re.compile(r"\b(?:class|interface|enum|record)\s+([A-Za-z_]\w*)"),
    "kotlin": re.compile(r"\b(?:class|interface|object|fun|typealias)\s+([A-Za-z_]\w*)"),
    "rust": re.compile(r"\b(?:fn|struct|enum|trait|type)\s+([A-Za-z_]\w*)"),
    "csharp": re.compile(r"\b(?:class|interface|enum|record|struct)\s+([A-Za-z_]\w*)"),
    "cpp": re.compile(r"\b(?:class|struct|enum|namespace)\s+([A-Za-z_]\w*)"),
    "c": re.compile(r"\b(?:struct|enum|union|typedef)\s+([A-Za-z_]\w*)"),
    "ruby": re.compile(r"(?m)^\s*(?:class|module|def)\s+([A-Za-z_]\w*[!?=]?)"),
    "php": re.compile(r"\b(?:class|interface|trait|enum|function)\s+([A-Za-z_]\w*)"),
    "swift": re.compile(r"\b(?:class|struct|enum|protocol|func|actor)\s+([A-Za-z_]\w*)"),
}
_IMPORT_PATTERNS = {
    "javascript": re.compile(r"""\b(?:from\s*|import\s*(?:\(\s*)?|require\s*\(\s*)['"]([^'"]+)['"]"""),
    "typescript": re.compile(r"""\b(?:from\s*|import\s*(?:\(\s*)?|require\s*\(\s*)['"]([^'"]+)['"]"""),
    "go": re.compile(r"""(?m)^\s*(?:import\s+)?["']([^"']+)["']"""),
    "rust": re.compile(r"(?m)^\s*(?:use|extern\s+crate)\s+([A-Za-z_]\w*)"),
    "java": re.compile(r"(?m)^\s*import\s+(?:static\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)"),
    "kotlin": re.compile(r"(?m)^\s*import\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)"),
    "csharp": re.compile(r"(?m)^\s*using\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;"),
    "cpp": re.compile(r'(?m)^\s*#\s*include\s*[<"]([^>"]+)[>"]'),
    "c": re.compile(r'(?m)^\s*#\s*include\s*[<"]([^>"]+)[>"]'),
    "ruby": re.compile(r"""(?m)^\s*require(?:_relative)?\s*['"]([^'"]+)['"]"""),
    "php": re.compile(r"(?m)^\s*use\s+([A-Za-z_\\][A-Za-z0-9_\\]*)"),
    "swift": re.compile(r"(?m)^\s*import\s+([A-Za-z_]\w*)"),
}


def _extract_structure(language_id: str, source_text: str) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    """Extract bounded symbol/import hints; Python uses its real AST, other languages use heuristics."""
    symbols: set[str] = set()
    dependencies: set[str] = set()
    warning = None
    if language_id == "python":
        try:
            tree = ast.parse(source_text)
        except SyntaxError:
            return (), (), "Python syntax could not be parsed; source text was retained without AST hints."
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.add(node.name)
            elif isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                dependencies.add(node.module)
    else:
        symbol_pattern = _SYMBOL_PATTERNS.get(language_id)
        import_pattern = _IMPORT_PATTERNS.get(language_id)
        if symbol_pattern:
            symbols.update(match.group(1) for match in symbol_pattern.finditer(source_text))
        if import_pattern:
            dependencies.update(match.group(1) for match in import_pattern.finditer(source_text))
        if symbol_pattern is None:
            warning = f"No structural symbol extractor is configured for {language_id}; only source text is available."
    return tuple(sorted(symbols)[:200]), tuple(sorted(dependencies)[:100]), warning


class InventorySourceAdapter:
    """Read supported UTF-8 source files into a hash-checked project inventory."""
    def __init__(self, language_id: str, extensions: Iterable[str], *, max_file_bytes: int = 1_000_000,
                 max_files: int = 1_000, max_total_bytes: int = 20_000_000,\n                 max_scan_entries: int = 100_000) -> None:
        if not language_id or language_id.strip().lower() != language_id:
            raise ValueError("language_id must be canonical lowercase text")
        if min(max_file_bytes, max_files, max_total_bytes, max_scan_entries) < 1:
            raise ValueError("source inventory limits must be positive")
        normalized = tuple(sorted({ext.lower() for ext in extensions}))
        if not normalized or any(not ext.startswith(".") or "/" in ext or "\\" in ext for ext in normalized):
            raise ValueError("extensions must be non-empty file suffixes")
        self.language_id = language_id
        self.extensions = frozenset(normalized)
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes

    def analyze(self, source_root: Path) -> SourceProject:
        root = source_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Source root must be a directory")
        units: list[SourceUnit] = []
        warnings: list[str] = []
        total_bytes = 0
        scanned_entries = 0
        for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(
                name for name in directories
                if name not in _IGNORED_DIRS and not (current_path / name).is_symlink()
            )
            for filename in sorted(filenames):
                scanned_entries += 1
                if scanned_entries > self.max_scan_entries:
                    raise ValueError(f"Source inventory traversal exceeds configured limit ({self.max_scan_entries} entries)")
                path = current_path / filename
                relative = path.relative_to(root)
                if path.is_symlink() or path.suffix.lower() not in self.extensions:
                    continue
                try:
                    size = path.stat().st_size
                    if len(units) >= self.max_files:
                        raise ValueError(f"Source file count exceeds configured limit ({self.max_files})")
                    if total_bytes + size > self.max_total_bytes:
                        raise ValueError(f"Source inventory exceeds configured total size limit ({self.max_total_bytes} bytes)")
                    if size > self.max_file_bytes:
                        warnings.append(f"Skipped oversized source file: {relative.as_posix()}")
                        continue
                    text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                warnings.append(f"Skipped unreadable or non-UTF-8 source file: {relative.as_posix()}")
                continue
            symbols, dependencies, structure_warning = _extract_structure(self.language_id, text)
            if structure_warning:
                warnings.append(f"{relative.as_posix()}: {structure_warning}")
            units.append(SourceUnit(
                relative_path=relative.as_posix(),
                source_text=text,
                content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                symbols=symbols,
                dependencies=dependencies,
            ))
            total_bytes += size
        if not units:
            raise ValueError(f"No readable {self.language_id} source files found in {root}")
        warnings.append("Inventory mode detects files by extension; it does not fully parse semantics, frameworks, or dependencies.")
        return SourceProject(root, self.language_id, tuple(units), {"warnings": warnings, "inventory_mode": "extension-based"})
