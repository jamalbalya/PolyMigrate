"""Bounded source inventory with Python AST hints and heuristic structure extraction for other languages."""
from __future__ import annotations
import ast
import hashlib
import os
import re
from pathlib import Path
from typing import Iterable
from polymigrate.migration.pipeline import SourceProject, SourceUnit

try:
    from tree_sitter_language_pack import LanguageRegistry as _TreeSitterRegistry, get_parser as _get_tree_sitter_parser
    _TREE_SITTER_REGISTRY = _TreeSitterRegistry.new()
except Exception:  # Optional parser extra must never break the standard-library fallback.
    _TREE_SITTER_REGISTRY = None
    _get_tree_sitter_parser = None

# Minimal direct grammar fallback for environments that install individual
# Tree-sitter grammars without the optional language-pack dependency.
try:
    import tree_sitter as _tree_sitter
    import tree_sitter_go as _tree_sitter_go
except Exception:
    _tree_sitter = None
    _tree_sitter_go = None


def _direct_tree_sitter_parser(language_id: str):
    if language_id != "go" or _tree_sitter is None or _tree_sitter_go is None:
        return None
    try:
        language = _tree_sitter.Language(_tree_sitter_go.language())
        return _tree_sitter.Parser(language)
    except Exception:
        return None

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


_TREE_SITTER_SYMBOL_TYPES = {
    "go": {"function_declaration", "method_declaration", "type_spec"},
    "javascript": {"function_declaration", "class_declaration", "method_definition", "variable_declarator"},
    "typescript": {"function_declaration", "class_declaration", "interface_declaration", "type_alias_declaration", "method_definition", "variable_declarator"},
    "java": {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration", "method_declaration", "constructor_declaration"},
    "kotlin": {"class_declaration", "object_declaration", "function_declaration"},
    "rust": {"function_item", "struct_item", "enum_item", "trait_item", "type_item"},
    "csharp": {"class_declaration", "interface_declaration", "struct_declaration", "enum_declaration", "method_declaration", "constructor_declaration"},
    "cpp": {"class_specifier", "struct_specifier", "function_definition", "namespace_definition"},
    "c": {"struct_specifier", "enum_specifier", "function_definition"},
    "ruby": {"class", "module", "method", "singleton_method"},
    "php": {"class_declaration", "interface_declaration", "trait_declaration", "function_definition", "method_declaration"},
    "swift": {"class_declaration", "struct_declaration", "enum_declaration", "protocol_declaration", "function_declaration"},
}
_TREE_SITTER_NAME_TYPES = {"identifier", "type_identifier", "field_identifier", "property_identifier", "constant", "simple_identifier"}


def _offline_tree_sitter_parser(language_id: str):
    """Return an already-installed parser without triggering grammar downloads."""
    parser = None
    if _TREE_SITTER_REGISTRY is not None and _get_tree_sitter_parser is not None:
        try:
            if _TREE_SITTER_REGISTRY.has_parser(language_id):
                parser = _get_tree_sitter_parser(language_id)
        except Exception:
            parser = None
    if parser is None:
        parser = _direct_tree_sitter_parser(language_id)
    if parser is not None:
        if hasattr(parser, "set_max_source_bytes"):
            parser.set_max_source_bytes(1_000_000)
        if hasattr(parser, "set_parse_timeout_ms"):
            parser.set_parse_timeout_ms(250)
    return parser


def _tree_sitter_imports(language_id: str, source_text: str) -> set[str] | None:
    """Extract imports from AST import nodes; None means no offline parser exists."""
    parser = _offline_tree_sitter_parser(language_id)
    if parser is None:
        return None
    try:
        tree = parser.parse(source_text.encode("utf-8"))
    except Exception:
        return set()
    if tree is None:
        return set()
    node_types = {
        "javascript": {"import_statement", "export_statement", "call_expression"},
        "typescript": {"import_statement", "export_statement", "call_expression"},
        "rust": {"use_declaration", "extern_crate_declaration"},
        "java": {"import_declaration"},
        "kotlin": {"import_header"},
        "csharp": {"using_directive"},
        "cpp": {"preproc_include"},
        "c": {"preproc_include"},
        "ruby": {"call"},
        "php": {"namespace_use_declaration"},
        "swift": {"import_declaration"},
    }.get(language_id, set())
    if not node_types:
        return None
    imports: set[str] = set()
    stack = [tree.root_node]
    visited = 0
    while stack and visited < 100_000:
        node = stack.pop()
        visited += 1
        if node.type in node_types and node.text:
            text = node.text.decode("utf-8", errors="replace")
            if language_id in {"javascript", "typescript"}:
                if node.type == "call_expression" and not re.search(r"\b(?:require|import)\s*\(", text):
                    stack.extend(reversed(node.named_children))
                    continue
                match = re.search(r'''["']([^"']+)["']''', text)
                if match:
                    imports.add(match.group(1))
            elif language_id == "go":
                match = re.search(r'''["']([^"']+)["']''', text)
                if match:
                    imports.add(match.group(1))
            elif language_id == "rust":
                match = re.search(r"\b(?:use|extern\s+crate)\s+([A-Za-z_]\w*)", text)
                if match:
                    imports.add(match.group(1))
            elif language_id in {"java", "kotlin"}:
                match = re.search(r"\bimport\s+(?:static\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)", text)
                if match:
                    imports.add(match.group(1))
            elif language_id == "csharp":
                match = re.search(r"\busing\s+(?:static\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;", text)
                if match:
                    imports.add(match.group(1))
            elif language_id in {"c", "cpp"}:
                match = re.search(r'#\s*include\s*[<"]([^>"]+)[>"]', text)
                if match:
                    imports.add(match.group(1))
            elif language_id == "ruby":
                if re.search(r"\b(?:require|require_relative)\b", text):
                    match = re.search(r'''["']([^"']+)["']''', text)
                    if match:
                        imports.add(match.group(1))
            elif language_id == "php":
                match = re.search(r"\buse\s+(.+?);", text)
                if match:
                    value = match.group(1).strip()
                    value = re.sub(r"^(?:function|const)\s+", "", value)
                    imports.add(value.split(" as ", 1)[0].strip())
            elif language_id == "swift":
                match = re.search(r"\bimport\s+(?:class|struct|enum|protocol|func|var|let)\s+([A-Za-z_]\w*)|\bimport\s+([A-Za-z_]\w*)", text)
                if match:
                    imports.add(next(group for group in match.groups() if group))
        stack.extend(reversed(node.named_children))
    return imports


def _tree_sitter_structure(language_id: str, source_text: str) -> tuple[set[str], str | None] | None:
    """Parse with an already-available grammar only; never trigger grammar downloads."""
    try:
        parser = _offline_tree_sitter_parser(language_id)
        if parser is None:
            return None
        tree = parser.parse(source_text.encode("utf-8"))
        if tree is None:
            return set(), "Tree-sitter parsing timed out or exceeded its source limit; heuristic hints were retained."
        root = tree.root_node
        symbols: set[str] = set()
        stack = [root]
        visited = 0
        symbol_types = _TREE_SITTER_SYMBOL_TYPES.get(language_id, set())
        while stack and visited < 100_000:
            node = stack.pop()
            visited += 1
            if node.type in symbol_types:
                name_node = node.child_by_field_name("name")
                if name_node is None:
                    name_node = next((child for child in node.named_children if child.type in _TREE_SITTER_NAME_TYPES), None)
                if name_node is not None and name_node.text:
                    symbols.add(name_node.text.decode("utf-8", errors="replace"))
            stack.extend(reversed(node.named_children))
        warning = None
        if stack:
            warning = "Tree-sitter structure traversal reached its node limit; symbol hints may be incomplete."
        if root.has_error:
            warning = "Tree-sitter reported syntax errors; source text was retained and structure hints may be incomplete."
        return symbols, warning
    except Exception:
        return None


def check_target_syntax(language_id: str, source_text: str) -> str | None:
    """Return a bounded syntax warning when a parser is available; never execute generated code."""
    if language_id == "python":
        try:
            ast.parse(source_text)
        except (SyntaxError, RecursionError):
            return "Python AST reported syntax errors in generated output."
        return None
    result = _tree_sitter_structure(language_id, source_text)
    if result is None:
        return f"No usable offline syntax parser was available for {language_id}; generated syntax was not checked."
    _, warning = result
    if warning and ("syntax errors" in warning or "timed out" in warning or "node limit" in warning):
        return warning
    return None


def _extract_go_imports(source_text: str) -> set[str]:
    """Extract paths only from Go import declarations, not arbitrary string literals."""
    without_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", source_text, flags=re.DOTALL)
    imports: set[str] = set()
    single_pattern = r'''(?m)^\s*import\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?["']([^"']+)["']'''
    block_pattern = r'''(?m)^\s*(?:[A-Za-z_][A-Za-z0-9_]*\s+)?["']([^"']+)["']'''
    for match in re.finditer(single_pattern, without_comments):
        imports.add(match.group(1))
    for block in re.findall(r"(?s)\bimport\s*\((.*?)\)", without_comments):
        for match in re.finditer(block_pattern, block):
            imports.add(match.group(1))
    return imports


def _extract_structure(language_id: str, source_text: str) -> tuple[tuple[str, ...], tuple[str, ...], str | None, str]:
    """Extract bounded symbol/import hints; prefer Python AST or offline Tree-sitter, then fall back to heuristics."""
    symbols: set[str] = set()
    dependencies: set[str] = set()
    warning = None
    if language_id == "python":
        try:
            tree = ast.parse(source_text)
        except (SyntaxError, RecursionError):
            return (), (), "Python syntax could not be parsed safely; source text was retained without AST hints.", "python-ast-failed"
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.add(node.name)
            elif isinstance(node, ast.Import):
                dependencies.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                dependencies.add(node.module)
    else:
        tree_sitter_result = _tree_sitter_structure(language_id, source_text)
        parser_backend = "heuristic"
        if tree_sitter_result is not None:
            tree_symbols, tree_warning = tree_sitter_result
            symbols.update(tree_symbols)
            parser_backend = "tree-sitter"
            warning = tree_warning
        symbol_pattern = _SYMBOL_PATTERNS.get(language_id)
        import_pattern = _IMPORT_PATTERNS.get(language_id)
        # Regex symbol extraction is fallback-only. Combining it with an AST
        # parser can misclassify declarations inside comments and string literals.
        if symbol_pattern and tree_sitter_result is None:
            symbols.update(match.group(1) for match in symbol_pattern.finditer(source_text))
        if language_id == "go":
            dependencies.update(_extract_go_imports(source_text))
        elif language_id in _IMPORT_PATTERNS:
            parsed_imports = _tree_sitter_imports(language_id, source_text)
            if parsed_imports is not None:
                dependencies.update(parsed_imports)
            elif import_pattern:
                dependencies.update(match.group(1) for match in import_pattern.finditer(source_text))
        elif import_pattern:
            dependencies.update(match.group(1) for match in import_pattern.finditer(source_text))
        if symbol_pattern is None:
            warning = f"No structural symbol extractor is configured for {language_id}; only source text is available."
        return tuple(sorted(symbols)[:200]), tuple(sorted(dependencies)[:100]), warning, parser_backend
    return tuple(sorted(symbols)[:200]), tuple(sorted(dependencies)[:100]), warning, "python-ast"


def _extract_references(language_id: str, source_text: str) -> tuple[str, ...]:
    """Extract bounded call-name hints from Python AST or an already-installed Tree-sitter grammar."""
    references: set[str] = set()
    if language_id == "python":
        try:
            tree = ast.parse(source_text)
        except (SyntaxError, RecursionError):
            return ()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                references.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                references.add(node.func.attr)
        return tuple(sorted(references)[:200])

    parser = _offline_tree_sitter_parser(language_id)
    if parser is None:
        return ()
    try:
        tree = parser.parse(source_text.encode("utf-8"))
    except Exception:
        return ()
    if tree is None or tree.root_node.has_error:
        return ()
    call_types = {
        "go": {"call_expression"},
        "javascript": {"call_expression", "new_expression"},
        "typescript": {"call_expression", "new_expression"},
        "java": {"method_invocation", "object_creation_expression"},
        "kotlin": {"call_expression"},
        "rust": {"call_expression"},
        "csharp": {"invocation_expression", "object_creation_expression"},
        "cpp": {"call_expression"},
        "c": {"call_expression"},
        "ruby": {"call", "command"},
        "php": {"function_call_expression", "member_call_expression", "scoped_call_expression"},
        "swift": {"call_expression"},
    }.get(language_id, set())
    stack = [tree.root_node]
    visited = 0
    call_pattern = re.compile(r"([A-Za-z_$][A-Za-z0-9_$]*(?:(?:\\.|::|->)[A-Za-z_$][A-Za-z0-9_$]*)*)\\s*\\(")
    while stack and visited < 100_000:
        node = stack.pop()
        visited += 1
        if node.type in call_types and node.text:
            text = node.text.decode("utf-8", errors="replace")[:4_000]
            match = call_pattern.search(text)
            if match:
                name = re.split(r"\\.|::|->", match.group(1))[-1]
                if name and name not in {"if", "while", "for", "switch", "catch", "sizeof"}:
                    references.add(name)
        stack.extend(reversed(node.named_children))
    return tuple(sorted(references)[:200])


class InventorySourceAdapter:
    """Bounded source inventory with Python AST hints and heuristic structure extraction for other languages."""
    def __init__(self, language_id: str, extensions: Iterable[str], *, max_file_bytes: int = 1_000_000,
                 max_files: int = 1_000, max_total_bytes: int = 20_000_000,
                 max_scan_entries: int = 100_000) -> None:
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
        self.max_scan_entries = max_scan_entries

    def analyze(self, source_root: Path) -> SourceProject:
        root = source_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Source root must be a directory")
        units: list[SourceUnit] = []
        warnings: list[str] = []
        total_bytes = 0
        scanned_entries = 0
        parser_backends: set[str] = set()
        for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(
                name for name in directories
                if name not in _IGNORED_DIRS and not (current_path / name).is_symlink()
            )
            scanned_entries += len(directories)
            if scanned_entries > self.max_scan_entries:
                raise ValueError(f"Source inventory traversal exceeds configured limit ({self.max_scan_entries} entries)")
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
                symbols, dependencies, structure_warning, parser_backend = _extract_structure(self.language_id, text)
                parser_backends.add(parser_backend)
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
        return SourceProject(root, self.language_id, tuple(units), {"warnings": warnings, "inventory_mode": "extension-based", "parser_backends": sorted(parser_backends)})
