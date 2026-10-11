"""Bounded inventory of common project manifests for migration context."""
from __future__ import annotations

import os
from pathlib import Path

from polymigrate.security.redaction import redact_text

_IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", "target", "vendor", ".next",
}
_MANIFEST_NAMES = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "go.mod", "go.work", "cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "settings.gradle", "settings.gradle.kts", "gemfile", "gemspec", "composer.json",
    "package.swift", "cmakelists.txt", "makefile", "justfile", "dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "requirements-dev.txt",
}
_MANIFEST_SUFFIXES = {".csproj", ".fsproj", ".vbproj", ".sln", ".gradle"}


def scan_project_manifests(
    project_root: Path, *, max_files: int = 30, max_file_bytes: int = 256_000,
    max_total_bytes: int = 1_000_000, max_scan_entries: int = 50_000,
) -> tuple[list[dict[str, str]], list[str]]:
    """Read a bounded allowlist of manifest files, skipping symlinks and redacting secrets."""
    if min(max_files, max_file_bytes, max_total_bytes, max_scan_entries) < 1:
        raise ValueError("manifest scan limits must be positive")
    root = project_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("project manifest root must be a directory")
    manifests: list[dict[str, str]] = []
    warnings: list[str] = []
    total_bytes = 0
    scanned_entries = 0
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories
            if name not in _IGNORED_DIRS and not (current_path / name).is_symlink()
        )
        scanned_entries += len(directories)
        if scanned_entries > max_scan_entries:
            warnings.append(f"Project manifest scan reached its {max_scan_entries}-entry traversal limit.")
            return manifests, warnings
        for filename in sorted(filenames):
            scanned_entries += 1
            if scanned_entries > max_scan_entries:
                warnings.append(f"Project manifest scan reached its {max_scan_entries}-entry traversal limit.")
                return manifests, warnings
            path = current_path / filename
            if path.is_symlink():
                continue
            if path.name.lower() not in _MANIFEST_NAMES and path.suffix.lower() not in _MANIFEST_SUFFIXES:
                continue
            relative = path.relative_to(root)
            if len(manifests) >= max_files:
                warnings.append(f"Project manifest scan reached its {max_files}-file limit.")
                return manifests, warnings
            try:
                size = path.stat().st_size
                if size > max_file_bytes:
                    warnings.append(f"Skipped oversized project manifest: {relative.as_posix()}")
                    continue
                if total_bytes + size > max_total_bytes:
                    warnings.append(f"Project manifest scan reached its {max_total_bytes}-byte limit.")
                    return manifests, warnings
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                warnings.append(f"Skipped unreadable or non-UTF-8 project manifest: {relative.as_posix()}")
                continue
            safe = redact_text(raw)
            if safe != raw:
                warnings.append(f"Recognizable secret patterns were redacted from manifest context: {relative.as_posix()}")
            manifests.append({"path": relative.as_posix(), "content": safe})
            total_bytes += size
    return manifests, warnings
