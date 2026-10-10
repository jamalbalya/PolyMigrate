"""Built-in source inventory adapter; it inventories text source files but does not claim full parsing."""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Iterable
from polymigrate.migration.pipeline import SourceProject, SourceUnit

_IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build"}

class InventorySourceAdapter:
    """Read supported UTF-8 source files into a hash-checked project inventory."""
    def __init__(self, language_id: str, extensions: Iterable[str], *, max_file_bytes: int = 1_000_000) -> None:
        if not language_id or language_id.strip().lower() != language_id:
            raise ValueError("language_id must be canonical lowercase text")
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        normalized = tuple(sorted({ext.lower() for ext in extensions}))
        if not normalized or any(not ext.startswith(".") or "/" in ext or "\\" in ext for ext in normalized):
            raise ValueError("extensions must be non-empty file suffixes")
        self.language_id = language_id
        self.extensions = frozenset(normalized)
        self.max_file_bytes = max_file_bytes

    def analyze(self, source_root: Path) -> SourceProject:
        root = source_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Source root must be a directory")
        units: list[SourceUnit] = []
        warnings: list[str] = []
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root)
            if any(part in _IGNORED_DIRS for part in relative.parts):
                continue
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in self.extensions:
                continue
            try:
                size = path.stat().st_size
                if size > self.max_file_bytes:
                    warnings.append(f"Skipped oversized source file: {relative.as_posix()}")
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                warnings.append(f"Skipped unreadable or non-UTF-8 source file: {relative.as_posix()}")
                continue
            units.append(SourceUnit(
                relative_path=relative.as_posix(),
                source_text=text,
                content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ))
        if not units:
            raise ValueError(f"No readable {self.language_id} source files found in {root}")
        warnings.append("Inventory mode detects files by extension; it does not fully parse semantics, frameworks, or dependencies.")
        return SourceProject(root, self.language_id, tuple(units), {"warnings": warnings, "inventory_mode": "extension-based"})
