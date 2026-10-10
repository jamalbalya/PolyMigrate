"""Static dependency-declaration consistency checks for generated target output.

This does not install packages or prove dependency APIs/builds work.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "target", "vendor"}
_MAX_FILES = 10_000
_MAX_BYTES = 20_000_000
_NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "console", "constants", "crypto",
    "dgram", "diagnostics_channel", "dns", "domain", "events", "fs", "http", "http2",
    "https", "module", "net", "os", "path", "perf_hooks", "process", "punycode",
    "querystring", "readline", "repl", "stream", "string_decoder", "sys", "timers",
    "tls", "trace_events", "tty", "url", "util", "v8", "vm", "wasi", "worker_threads",
    "zlib",
}


@dataclass(frozen=True)
class DependencyWiringReview:
    status: str
    language: str
    imports_checked: int
    declared_dependencies: tuple[str, ...]
    missing_declarations: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "language": self.language,
            "imports_checked": self.imports_checked,
            "declared_dependencies": list(self.declared_dependencies),
            "missing_declarations": list(self.missing_declarations),
            "warnings": list(self.warnings),
            "scope": "static_manifest_import_consistency",
            "does_not_prove_build_or_api_compatibility": True,
        }


def _files(root: Path, suffixes: set[str]) -> tuple[list[Path], list[str]]:
    found: list[Path] = []
    warnings: list[str] = []
    total = 0
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories
            if name not in _IGNORED_DIRS and not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if len(found) >= _MAX_FILES:
                warnings.append(f"Source scan stopped at the {_MAX_FILES}-file limit.")
                return found, warnings
            try:
                size = path.stat().st_size
            except OSError:
                warnings.append("A source file could not be statted; dependency evidence may be incomplete.")
                continue
            if size > 1_000_000 or total + size > _MAX_BYTES:
                warnings.append("Source scan stopped at a file or total byte limit.")
                return found, warnings
            total += size
            found.append(path)
    return found, warnings


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _python_dependencies(root: Path) -> tuple[set[str], set[str], list[str]]:
    files, warnings = _files(root, {".py"})
    imports: set[str] = set()
    for path in files:
        text = _read(path)
        if text is None:
            warnings.append(f"Could not read {path.relative_to(root).as_posix()}.")
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, RecursionError):
            warnings.append(f"Could not statically inspect imports in {path.relative_to(root).as_posix()}.")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split(".", 1)[0])
    declared: set[str] = set()
    for name in ("requirements.txt", "requirements-dev.txt"):
        path = root / name
        if path.is_file() and not path.is_symlink():
            for line in (_read(path) or "").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                match = re.match(r"([A-Za-z0-9_.-]+)", line)
                if match:
                    declared.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and not pyproject.is_symlink():
        try:
            data = tomllib.loads(_read(pyproject) or "")
            project = data.get("project", {})
            if isinstance(project, dict):
                for item in project.get("dependencies", []) if isinstance(project.get("dependencies", []), list) else []:
                    if isinstance(item, str):
                        match = re.match(r"([A-Za-z0-9_.-]+)", item)
                        if match:
                            declared.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
        except (tomllib.TOMLDecodeError, TypeError):
            warnings.append("pyproject.toml could not be parsed for dependency declarations.")
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    third_party = {
        item for item in imports
        if item not in stdlib and item not in {"__future__", "typing_extensions"}
    }
    missing = {
        item for item in third_party
        if re.sub(r"[-_.]+", "-", item).lower() not in declared
    }
    return imports, declared, warnings + [f"Missing target dependency declaration: {item}" for item in sorted(missing)]


def _go_dependencies(root: Path) -> tuple[set[str], set[str], list[str]]:
    files, warnings = _files(root, {".go"})
    imports: set[str] = set()
    for path in files:
        text = _read(path)
        if text is None:
            warnings.append(f"Could not read {path.relative_to(root).as_posix()}.")
            continue
        imports.update(re.findall(r'(?m)^\s*import\s+"([^"]+)"', text))
        for block in re.findall(r"(?s)\bimport\s*\((.*?)\)", text):
            imports.update(re.findall(r'"([^"]+)"', block))
    declared: set[str] = set()
    go_mod = root / "go.mod"
    module_path = ""
    if go_mod.is_file() and not go_mod.is_symlink():
        text = _read(go_mod) or ""
        module_match = re.search(r"(?m)^\s*module\s+(\S+)", text)
        module_path = module_match.group(1) if module_match else ""
        declared.update(re.findall(r"(?m)^\s*require\s+([^\s(]+)\s+", text))
        for block in re.findall(r"(?s)\brequire\s*\((.*?)\)", text):
            declared.update(re.findall(r"(?m)^\s*([^\s()]+)\s+v[^\s]+", block))
    external = {
        item for item in imports
        if "." in item.split("/", 1)[0] and not (module_path and (item == module_path or item.startswith(module_path + "/")))
    }
    missing = external - declared
    return imports, declared, warnings + [f"Missing go.mod dependency declaration: {item}" for item in sorted(missing)]


def _javascript_dependencies(root: Path) -> tuple[set[str], set[str], list[str]]:
    files, warnings = _files(root, {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
    imports: set[str] = set()
    for path in files:
        text = _read(path)
        if text is None:
            warnings.append(f"Could not read {path.relative_to(root).as_posix()}.")
            continue
        for item in re.findall(r"""(?m)(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*)['"]([^'"]+)['"]""", text):
            if item.startswith((".", "/")) or item.startswith("node:"):
                continue
            package = item.split("/")
            imports.add("/".join(package[:2]) if item.startswith("@") and len(package) > 1 else package[0])
    declared: set[str] = set()
    manifest = root / "package.json"
    if manifest.is_file() and not manifest.is_symlink():
        try:
            data = json.loads(_read(manifest) or "")
            if not isinstance(data, dict):
                raise ValueError("manifest must be an object")
            for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                values = data.get(key, {})
                if isinstance(values, dict):
                    declared.update(name for name in values if isinstance(name, str))
        except (json.JSONDecodeError, ValueError):
            warnings.append("package.json could not be parsed for dependency declarations.")
    external = imports - _NODE_BUILTINS
    missing = external - declared
    return imports, declared, warnings + [f"Missing package.json dependency declaration: {item}" for item in sorted(missing)]


def review_dependency_wiring(root: Path, language: str) -> DependencyWiringReview:
    """Compare statically observed imports with allowlisted manifest declarations."""
    if root.is_symlink():
        return DependencyWiringReview("BLOCKED", language, 0, (), (), ("Target root must not be a symlink.",))
    try:
        resolved = root.expanduser().resolve(strict=True)
    except OSError:
        return DependencyWiringReview("BLOCKED", language, 0, (), (), ("Target root does not exist.",))
    if not resolved.is_dir():
        return DependencyWiringReview("BLOCKED", language, 0, (), (), ("Target root is not a directory.",))
    if language == "python":
        imports, declared, warnings = _python_dependencies(resolved)
    elif language == "go":
        imports, declared, warnings = _go_dependencies(resolved)
    elif language in {"javascript", "typescript"}:
        imports, declared, warnings = _javascript_dependencies(resolved)
    else:
        return DependencyWiringReview(
            "UNVERIFIED", language, 0, (), (),
            (f"No dependency wiring analyzer is configured for {language}.",),
        )
    missing = tuple(sorted(item.split(": ", 1)[1] for item in warnings if item.startswith("Missing ")))
    incomplete = any("could not" in item.lower() or "stopped at" in item.lower() or "could not read" in item.lower() for item in warnings)
    status = "BLOCKED" if missing else "UNVERIFIED" if incomplete else "PASSED"
    warnings.append("Static import/manifest consistency does not prove package availability, API compatibility, successful compilation, or runtime behavior.")
    return DependencyWiringReview(status, language, len(imports), tuple(sorted(declared)), missing, tuple(warnings))
