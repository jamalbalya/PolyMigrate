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
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "target", "vendor", "tests", "test", "__tests__", "spec", "specs"}
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
    observed_imports: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "language": self.language,
            "imports_checked": self.imports_checked,
            "declared_dependencies": list(self.declared_dependencies),
            "observed_imports": list(self.observed_imports),
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



def _java_dependencies(root: Path) -> tuple[set[str], set[str], list[str]]:
    """Inventory Java imports and Maven/Gradle coordinates without guessing mappings."""
    files, warnings = _files(root, {".java"})
    imports: set[str] = set()
    local_packages: set[str] = set()
    for path in files:
        text = _read(path)
        if text is None:
            warnings.append(f"Could not read {path.relative_to(root).as_posix()}.")
            continue
        clean = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        clean = re.sub(r"(?m)^\s*//.*$", "", clean)
        local_packages.update(
            match.group(1) for match in re.finditer(
                r"(?m)^\s*package\s+([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\s*;", clean
            )
        )
        for match in re.finditer(
            r"(?m)^\s*import\s+(?:static\s+)?([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)(?:\.\*)?\s*;",
            clean,
        ):
            imports.add(match.group(1))

    external = {
        item for item in imports
        if not item.startswith(("java.", "javax.", "jdk."))
        and not any(item == package or item.startswith(package + ".") for package in local_packages)
    }
    declared: set[str] = set()
    manifests = [root / "pom.xml", root / "build.gradle", root / "build.gradle.kts"]
    present = [path for path in manifests if path.is_file() and not path.is_symlink()]
    for path in present:
        text = _read(path) or ""
        if path.name == "pom.xml":
            try:
                xml_root = ET.fromstring(text)
                for node in xml_root.iter():
                    if node.tag.rsplit("}", 1)[-1] == "dependency":
                        values = {}
                        for child in node:
                            values[child.tag.rsplit("}", 1)[-1]] = (child.text or "").strip()
                        if values.get("groupId") and values.get("artifactId"):
                            declared.add(f"{values['groupId']}:{values['artifactId']}")
            except ET.ParseError:
                warnings.append("pom.xml could not be parsed for Java dependency declarations.")
        else:
            coordinates = re.findall(
                r"""(?m)\b(?:implementation|api|compileOnly|runtimeOnly|testImplementation|testRuntimeOnly|compile)\s*\(?\s*['"]([^'"]+:[^'"]+:[^'"]+)['"]""",
                text,
            )
            declared.update(":".join(coordinate.split(":")[:2]) for coordinate in coordinates)

    if external and not present:
        warnings.extend(
            f"Missing Java dependency manifest for external import: {item}"
            for item in sorted(external)
        )
    elif external and present:
        warnings.append(
            "Java import-to-Maven/Gradle coordinate mapping is ambiguous; dependency wiring remains unverified until a real build and integration test proves it."
        )
    return imports, declared, warnings


def java_candidate_jar_imports(
    root: Path, coordinate: str, imports: tuple[str, ...] | set[str], *, test_sources: bool = False
) -> set[str]:
    """Prove imported Java classes exist and are used from a declared project-local system-scope JAR."""
    if root.is_symlink() or ":" not in coordinate:
        return set()
    try:
        resolved_root = root.expanduser().resolve(strict=True)
    except OSError:
        return set()
    if not resolved_root.is_dir():
        return set()
    pom = resolved_root / "pom.xml"
    if pom.is_symlink() or not pom.is_file():
        return set()
    try:
        if pom.stat().st_size > 1_000_000:
            return set()
    except OSError:
        return set()
    pom_text = _read(pom)
    if pom_text is None or "<!DOCTYPE" in pom_text.upper() or "<!ENTITY" in pom_text.upper():
        return set()
    try:
        xml_root = ET.fromstring(pom_text)
    except ET.ParseError:
        return set()

    system_path = None
    wanted_group, wanted_artifact = coordinate.split(":", 1)
    for node in xml_root.iter():
        if node.tag.rsplit("}", 1)[-1] != "dependency":
            continue
        values = {
            child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
            for child in node
        }
        if (
            values.get("groupId") == wanted_group
            and values.get("artifactId") == wanted_artifact
            and values.get("scope", "compile") == "system"
            and values.get("systemPath")
        ):
            system_path = values["systemPath"]
            break
    if not system_path:
        return set()

    prefixes = ("$" + "{project.basedir}/", "$" + "{basedir}/")
    relative_text = next(
        (system_path[len(prefix):] for prefix in prefixes if system_path.startswith(prefix)),
        system_path,
    )
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts or "$" in relative_text:
        return set()
    jar_path = resolved_root
    for part in relative.parts:
        jar_path = jar_path / part
        if jar_path.is_symlink():
            return set()
    try:
        resolved_jar = jar_path.resolve(strict=True)
        if (
            resolved_root not in resolved_jar.parents
            or not resolved_jar.is_file()
            or resolved_jar.suffix.lower() != ".jar"
            or resolved_jar.stat().st_size > 50_000_000
        ):
            return set()
        with zipfile.ZipFile(resolved_jar) as archive:
            infos = archive.infolist()
            if len(infos) > 100_000:
                return set()
            classes = {
                item.filename[:-6].replace("/", ".")
                for item in infos
                if item.filename.endswith(".class")
                and not item.filename.startswith("META-INF/")
                and not item.filename.endswith("module-info.class")
            }
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return set()

    test_dirs = {"test", "tests", "integration", "e2e", "spec", "__tests__"}
    source_paths: list[Path] = []
    if test_sources:
        ignored_dirs = {".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "target"}
        scanned_files = 0
        total_bytes = 0
        for current, directories, filenames in os.walk(resolved_root, topdown=True, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(
                name for name in directories
                if name not in ignored_dirs and not (current_path / name).is_symlink()
            )
            for filename in sorted(filenames):
                path = current_path / filename
                if path.is_symlink() or path.suffix.lower() != ".java":
                    continue
                relative_path = path.relative_to(resolved_root)
                is_test = (
                    any(part.lower() in test_dirs for part in relative_path.parts[:-1])
                    or filename.lower().startswith("test_")
                    or filename.lower().endswith("_test.java")
                )
                if is_test:
                    try:
                        size = path.stat().st_size
                    except OSError:
                        return set()
                    if size > 1_000_000:
                        return set()
                    scanned_files += 1
                    total_bytes += size
                    if scanned_files > 10_000 or total_bytes > 20_000_000:
                        return set()
                    source_paths.append(path)
    else:
        source_paths, scan_warnings = _files(resolved_root, {".java"})
        if scan_warnings:
            return set()

    matched: set[str] = set()
    import_pattern = r"(?m)^\s*import\s+(?:static\s+)?([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\s*;"
    for path in source_paths:
        source = _read(path)
        if source is None:
            continue
        clean = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        clean = re.sub(r"(?m)^\s*//.*$", "", clean)
        file_imports = set(re.findall(import_pattern, clean))
        code = re.sub(import_pattern, "", clean)
        code = re.sub(r"(?m)^\s*package\s+[A-Za-z_$][A-Za-z0-9_$.]*\s*;", "", code)
        code = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', "", code)
        for item in imports:
            if item not in classes or item not in file_imports:
                continue
            simple_name = item.rsplit(".", 1)[-1]
            if re.search(r"\b" + re.escape(simple_name) + r"\b", code):
                matched.add(item)
    return matched


def _kotlin_dependencies(root: Path) -> tuple[set[str], set[str], list[str]]:
    files, warnings = _files(root, {".kt", ".kts"})
    imports: set[str] = set()
    for path in files:
        text = _read(path)
        if text is None:
            warnings.append(f"Could not read {path.relative_to(root).as_posix()}.")
            continue
        imports.update(re.findall(r"(?m)^\s*import\s+([A-Za-z_][A-Za-z0-9_.]*(?:\.\*)?)", text))
    manifests = [root / name for name in ("build.gradle", "build.gradle.kts", "pom.xml")]
    present = [path for path in manifests if path.is_file() and not path.is_symlink()]
    declared: set[str] = set()
    for path in present:
        text = _read(path) or ""
        if path.name == "pom.xml":
            try:
                xml_root = ET.fromstring(text)
                for node in xml_root.iter():
                    if node.tag.rsplit("}", 1)[-1] == "dependency":
                        values = {}
                        for child in node:
                            values[child.tag.rsplit("}", 1)[-1]] = (child.text or "").strip()
                        if values.get("groupId") and values.get("artifactId"):
                            declared.add(f"{values['groupId']}:{values['artifactId']}")
            except ET.ParseError:
                warnings.append("pom.xml could not be parsed for Kotlin dependency declarations.")
        else:
            declared.update(re.findall(
                r"""(?m)\b(?:implementation|api|compileOnly|runtimeOnly|testImplementation|kapt)\s*\(?\s*['"]([^'"]+)['"]""",
                text,
            ))
    external = {item for item in imports if not item.startswith(("java.", "javax.", "kotlin."))}
    if external and not present:
        warnings.extend(f"Missing Kotlin dependency manifest for import: {item}" for item in sorted(external))
    elif external:
        warnings.append("Kotlin import-to-coordinate mapping is ambiguous; dependency wiring remains unverified until a real build proves it.")
    return imports, declared, warnings


_RUBY_STDLIB = {
    "base64", "benchmark", "bigdecimal", "cgi", "csv", "date", "digest", "erb", "etc",
    "fcntl", "fileutils", "find", "forwardable", "ipaddr", "json", "logger", "matrix",
    "monitor", "net/http", "net/https", "open-uri", "optparse", "ostruct", "pathname",
    "pp", "prettyprint", "prime", "psych", "readline", "resolv", "securerandom", "set",
    "shellwords", "singleton", "socket", "stringio", "tempfile", "time", "timeout",
    "tmpdir", "tsort", "uri", "weakref", "yaml", "zlib",
}


def _rust_dependencies(root: Path) -> tuple[set[str], set[str], list[str]]:
    """Check Rust crate imports against Cargo dependency tables; this is static evidence only."""
    files, warnings = _files(root, {".rs"})
    imports: set[str] = set()
    local_modules: set[str] = set()
    for path in files:
        if path.name == "mod.rs":
            local_modules.add(path.parent.name)
        elif path.stem not in {"lib", "main"}:
            local_modules.add(path.stem)
        text = _read(path)
        if text is None:
            warnings.append(f"Could not read {path.relative_to(root).as_posix()}.")
            continue
        clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)
        imports.update(re.findall(
            r"(?m)^\s*(?:pub\s+)?use\s+([A-Za-z_][A-Za-z0-9_]*)(?:::|(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*;)",
            clean,
        ))
        imports.update(re.findall(
            r"(?m)^\s*extern\s+crate\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", clean
        ))
    declared: set[str] = set()
    manifest = root / "Cargo.toml"
    if not manifest.is_file() or manifest.is_symlink():
        if files:
            warnings.append("Missing Cargo.toml manifest: Cargo.toml")
    else:
        try:
            if manifest.stat().st_size > 1_000_000:
                raise ValueError("Cargo.toml exceeds the manifest size limit.")
            data = tomllib.loads(_read(manifest) or "")
            def collect_dependency_tables(value: Any) -> None:
                if not isinstance(value, dict):
                    return
                for key in ("dependencies", "dev-dependencies", "build-dependencies"):
                    table = value.get(key)
                    if isinstance(table, dict):
                        declared.update(name for name in table if isinstance(name, str))
                for nested in value.values():
                    if isinstance(nested, dict):
                        collect_dependency_tables(nested)
            collect_dependency_tables(data)
        except (OSError, ValueError, UnicodeError, tomllib.TOMLDecodeError, RecursionError):
            warnings.append("Cargo.toml could not be parsed for dependency declarations.")
    builtin = {"std", "core", "alloc", "crate", "self", "super"}
    normalize = lambda value: value.replace("-", "_").casefold()
    external = {item for item in imports if item not in builtin and item not in local_modules}
    declared_normalized = {normalize(item) for item in declared}
    missing = {item for item in external if normalize(item) not in declared_normalized}
    warnings.extend(f"Missing Cargo.toml dependency declaration: {item}" for item in sorted(missing))
    return imports, declared, warnings

def _ruby_dependencies(root: Path) -> tuple[set[str], set[str], list[str]]:
    files, warnings = _files(root, {".rb"})
    imports: set[str] = set()
    for path in files:
        text = _read(path)
        if text is None:
            warnings.append(f"Could not read {path.relative_to(root).as_posix()}.")
            continue
        imports.update(re.findall(r"""(?m)^\s*require(?:_relative)?\s*\(?\s*['"]([^'"]+)['"]""", text))
    declared: set[str] = set()
    for name in ("Gemfile", "gems.rb"):
        path = root / name
        if path.is_file() and not path.is_symlink():
            text = _read(path)
            if text is None:
                warnings.append(f"{name} could not be read for gem declarations.")
                continue
            declared.update(re.findall(r"""\bgem\s*\(?\s*['"]([^'"]+)['"]""", text))
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.lower())
    missing = {
        item for item in imports
        if item not in _RUBY_STDLIB
        and not any(normalize(item.split("/", 1)[0]) == normalize(gem) for gem in declared)
    }
    if missing and not declared:
        warnings.extend(f"Missing Gemfile declaration for Ruby require: {item}" for item in sorted(missing))
    elif missing:
        warnings.append("Some Ruby require names could not be mapped confidently to declared gems; dependency wiring remains unverified.")
    return imports, declared, warnings


def _php_dependencies(root: Path) -> tuple[set[str], set[str], list[str]]:
    files, warnings = _files(root, {".php"})
    imports: set[str] = set()
    for path in files:
        text = _read(path)
        if text is None:
            warnings.append(f"Could not read {path.relative_to(root).as_posix()}.")
            continue
        imports.update(re.findall(r"(?m)^\s*use\s+([A-Za-z_][A-Za-z0-9_\\]*)", text))
    composer = root / "composer.json"
    declared: set[str] = set()
    local_namespaces: tuple[str, ...] = ()
    if composer.is_file() and not composer.is_symlink():
        try:
            data = json.loads(_read(composer) or "")
            if not isinstance(data, dict):
                raise ValueError("manifest must be an object")
            for key in ("require", "require-dev"):
                values = data.get(key, {})
                if isinstance(values, dict):
                    declared.update(name.lower() for name in values if isinstance(name, str))
            autoload = data.get("autoload", {})
            if isinstance(autoload, dict):
                psr4 = autoload.get("psr-4", {})
                if isinstance(psr4, dict):
                    local_namespaces = tuple(name.strip("\\").lower() for name in psr4 if isinstance(name, str))
        except (json.JSONDecodeError, ValueError):
            warnings.append("composer.json could not be parsed for dependency declarations.")
    elif imports:
        warnings.extend(f"Missing composer.json for PHP namespace import: {item}" for item in sorted(imports))
    unresolved = []
    for item in imports:
        namespace = item.strip("\\").lower()
        if any(namespace == prefix or namespace.startswith(prefix + "\\") for prefix in local_namespaces):
            continue
        # Namespace names do not reliably identify Composer package names; do not
        # turn a heuristic coordinate match into verified dependency evidence.
        unresolved.append(item)
    if unresolved and composer.is_file():
        warnings.append("PHP namespace-to-Composer package mapping is ambiguous; dependency wiring remains unverified until a real build/integration test proves it.")
    return imports, declared, warnings


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
    elif language == "kotlin":
        imports, declared, warnings = _kotlin_dependencies(resolved)
    elif language == "java":
        imports, declared, warnings = _java_dependencies(resolved)
    elif language == "ruby":
        imports, declared, warnings = _ruby_dependencies(resolved)
    elif language == "rust":
        imports, declared, warnings = _rust_dependencies(resolved)
    elif language == "php":
        imports, declared, warnings = _php_dependencies(resolved)
    else:
        return DependencyWiringReview(
            "UNVERIFIED", language, 0, (), (),
            (f"No dependency wiring analyzer is configured for {language}.",),
        )
    missing = tuple(sorted(item.split(": ", 1)[1] for item in warnings if item.startswith("Missing ")))
    incomplete = any("could not" in item.lower() or "stopped at" in item.lower() or "could not read" in item.lower() for item in warnings)
    requires_real_proof = any("remains unverified" in item.lower() or "mapping is ambiguous" in item.lower() for item in warnings)
    status = "BLOCKED" if missing else "UNVERIFIED" if incomplete or requires_real_proof else "PASSED"
    warnings.append("Static import/manifest consistency does not prove package availability, API compatibility, successful compilation, or runtime behavior.")
    return DependencyWiringReview(status, language, len(imports), tuple(sorted(declared)), missing, tuple(warnings), tuple(sorted(imports)))
