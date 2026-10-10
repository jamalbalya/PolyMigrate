"""Bounded heuristic security scan for generated migration output.

This is defense-in-depth, not a complete security audit or proof of safety.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from polymigrate.security.redaction import redact_text

_IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    "dist", "build", "target", "vendor", ".next",
}
_MAX_FILES = 10_000
_MAX_FILE_BYTES = 1_000_000
_MAX_TOTAL_BYTES = 50_000_000

# Rule IDs and patterns are deliberately stable so callers can baseline findings.
_RULES: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    ("SECRET_PRIVATE_KEY", "HIGH", "Private key material appears in generated output.",
     re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("SECRET_TOKEN_LITERAL", "HIGH", "A recognizable API token or credential appears in generated output.",
     re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
    ("PY_DYNAMIC_EVAL", "HIGH", "Dynamic code evaluation can execute untrusted input.",
     re.compile(r"(?m)\b(?:eval|exec)\s*\(")),
    ("PY_UNSAFE_DESERIALIZATION", "HIGH", "Unsafe pickle deserialization can execute code.",
     re.compile(r"(?m)\bpickle\.(?:loads?|Unpickler)\b")),
    ("SUBPROCESS_SHELL_TRUE", "HIGH", "Subprocess invocation enables shell interpretation.",
     re.compile(r"(?is)subprocess\.(?:run|Popen|call|check_call|check_output)\s*\([^)]{0,200}\bshell\s*=\s*True")),
    ("OS_SYSTEM_COMMAND", "HIGH", "OS-level shell command execution was detected.",
     re.compile(r"(?m)\bos\.system\s*\(")),
    ("UNSAFE_YAML_LOAD", "MEDIUM", "YAML loading may construct arbitrary objects; use a safe loader for untrusted input.",
     re.compile(r"(?m)\byaml\.load\s*\(")),
    ("TLS_VERIFY_DISABLED", "MEDIUM", "TLS certificate verification appears to be disabled.",
     re.compile(r"(?i)\bverify\s*=\s*False\b")),
    ("WEAK_HASH", "LOW", "A legacy hash function may be used for security-sensitive data.",
     re.compile(r"(?i)\b(?:md5|sha1)\s*\(")),
    ("JS_DYNAMIC_CODE", "HIGH", "Dynamic JavaScript code construction can execute untrusted input.",
     re.compile(r"(?m)\b(?:eval|Function)\s*\(")),
    ("JS_INSECURE_INNERHTML", "MEDIUM", "innerHTML can introduce DOM injection when populated with untrusted data.",
     re.compile(r"(?m)\.innerHTML\s*=")),
    ("JS_CHILD_PROCESS", "MEDIUM", "Child-process execution is security-sensitive when arguments contain untrusted input.",
     re.compile(r"(?m)\b(?:exec|execSync|spawn|spawnSync)\s*\(")),
    ("GO_COMMAND_EXEC", "MEDIUM", "Go command execution requires validation of executable and arguments.",
     re.compile(r"(?m)\bexec\.Command(?:Context)?\s*\(")),
    ("JVM_RUNTIME_EXEC", "HIGH", "JVM Runtime.exec can execute operating-system commands.",
     re.compile(r"(?m)\bRuntime\.getRuntime\(\)\.exec\s*\(")),
    ("JVM_UNSAFE_DESERIALIZATION", "HIGH", "Java object deserialization can instantiate attacker-controlled object graphs.",
     re.compile(r"(?m)\bObjectInputStream\b|\.readObject\s*\(")),
    ("CSHARP_PROCESS_START", "MEDIUM", "Process.Start can execute operating-system commands.",
     re.compile(r"(?m)\bProcess\.Start\s*\(")),
    ("CSHARP_BINARY_FORMATTER", "HIGH", "BinaryFormatter is unsafe for untrusted serialized data.",
     re.compile(r"(?m)\bBinaryFormatter\b")),
    ("RUBY_DYNAMIC_EVAL", "HIGH", "Ruby dynamic evaluation can execute untrusted source text.",
     re.compile(r"(?m)\b(?:eval|class_eval|instance_eval)\s*\(")),
    ("RUBY_SHELL_COMMAND", "MEDIUM", "Ruby shell/process execution is security-sensitive when inputs are untrusted.",
     re.compile(r"(?m)\b(?:system|exec|spawn|IO\.popen)\s*\(")),
    ("PHP_DYNAMIC_EVAL", "HIGH", "PHP dynamic evaluation can execute untrusted source text.",
     re.compile(r"(?m)\b(?:eval|assert)\s*\(")),
    ("PHP_SHELL_EXEC", "HIGH", "PHP shell execution can execute operating-system commands.",
     re.compile(r"(?m)\b(?:shell_exec|passthru|system|exec|popen|proc_open)\s*\(")),
    ("PHP_UNSAFE_DESERIALIZATION", "HIGH", "PHP unserialize can instantiate attacker-controlled object graphs.",
     re.compile(r"(?m)\bunserialize\s*\(")),
    ("NATIVE_SYSTEM_COMMAND", "HIGH", "Native system() calls execute shell commands.",
     re.compile(r"(?m)\bsystem\s*\(")),
    ("MANIFEST_LIFECYCLE_HOOK", "HIGH", "A dependency manifest contains an executable lifecycle or build hook.",
     re.compile(r"(?i)(?:\"(?:preinstall|postinstall|prepare|install)\"\s*:|<exec\b|<plugin\b|build\.rs|execute_process\s*\()")),
)
_RULES_BY_EXTENSION: dict[str, set[str]] = {
    ".py": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "PY_DYNAMIC_EVAL", "PY_UNSAFE_DESERIALIZATION",
            "SUBPROCESS_SHELL_TRUE", "OS_SYSTEM_COMMAND", "UNSAFE_YAML_LOAD", "TLS_VERIFY_DISABLED", "WEAK_HASH"},
    ".js": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "JS_DYNAMIC_CODE", "JS_INSECURE_INNERHTML", "JS_CHILD_PROCESS", "WEAK_HASH"},
    ".jsx": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "JS_DYNAMIC_CODE", "JS_INSECURE_INNERHTML", "JS_CHILD_PROCESS", "WEAK_HASH"},
    ".ts": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "JS_DYNAMIC_CODE", "JS_INSECURE_INNERHTML", "JS_CHILD_PROCESS", "WEAK_HASH"},
    ".tsx": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "JS_DYNAMIC_CODE", "JS_INSECURE_INNERHTML", "JS_CHILD_PROCESS", "WEAK_HASH"},
    ".go": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "GO_COMMAND_EXEC", "WEAK_HASH"},
    ".java": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "JVM_RUNTIME_EXEC", "JVM_UNSAFE_DESERIALIZATION", "WEAK_HASH"},
    ".cs": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "CSHARP_PROCESS_START", "CSHARP_BINARY_FORMATTER", "WEAK_HASH"},
    ".rb": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "RUBY_DYNAMIC_EVAL", "RUBY_SHELL_COMMAND", "WEAK_HASH"},
    ".php": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "PHP_DYNAMIC_EVAL", "PHP_SHELL_EXEC", "PHP_UNSAFE_DESERIALIZATION", "WEAK_HASH"},
    ".rs": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "WEAK_HASH"},
    ".toml": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "MANIFEST_LIFECYCLE_HOOK"},
    ".json": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "MANIFEST_LIFECYCLE_HOOK"},
    ".xml": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "MANIFEST_LIFECYCLE_HOOK"},
    ".yaml": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL"},
    ".yml": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL"},
    ".properties": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL"},
    ".c": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "NATIVE_SYSTEM_COMMAND", "WEAK_HASH"},
    ".h": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "NATIVE_SYSTEM_COMMAND", "WEAK_HASH"},
    ".cc": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "NATIVE_SYSTEM_COMMAND", "WEAK_HASH"},
    ".cpp": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "NATIVE_SYSTEM_COMMAND", "WEAK_HASH"},
    ".hpp": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "NATIVE_SYSTEM_COMMAND", "WEAK_HASH"},
    ".swift": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "WEAK_HASH"},
    ".kt": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "JVM_RUNTIME_EXEC", "JVM_UNSAFE_DESERIALIZATION", "WEAK_HASH"},
    ".kts": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "MANIFEST_LIFECYCLE_HOOK", "JVM_RUNTIME_EXEC", "JVM_UNSAFE_DESERIALIZATION"},
    ".scala": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "WEAK_HASH"},
    ".sql": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL"},
    ".sh": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "OS_SYSTEM_COMMAND"},
    ".bash": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL", "OS_SYSTEM_COMMAND"},
    ".ps1": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL"},
    ".env": {"SECRET_PRIVATE_KEY", "SECRET_TOKEN_LITERAL"},
}
_ALL_RULES = {rule_id: (severity, description, pattern) for rule_id, severity, description, pattern in _RULES}


@dataclass(frozen=True)
class SecurityFinding:
    rule_id: str
    severity: str
    path: str
    line: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id, "severity": self.severity,
            "path": self.path, "line": self.line, "message": self.message,
        }


@dataclass(frozen=True)
class StaticSecurityReview:
    status: str
    files_scanned: int
    bytes_scanned: int
    findings: tuple[SecurityFinding, ...]
    warnings: tuple[str, ...]
    scope: str = "bounded_static_heuristics"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope": self.scope,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "findings": [finding.to_dict() for finding in self.findings],
            "warnings": list(self.warnings),
            "not_a_comprehensive_audit": True,
        }


def review_generated_output(root: Path) -> StaticSecurityReview:
    """Scan regular files with bounded heuristics; never execute generated content."""
    if root.is_symlink():
        return StaticSecurityReview("BLOCKED", 0, 0, (), ("Review root must not be a symlink.",))
    try:
        resolved = root.expanduser().resolve(strict=True)
    except OSError:
        return StaticSecurityReview("BLOCKED", 0, 0, (), ("Review root does not exist.",))
    if not resolved.is_dir():
        return StaticSecurityReview("BLOCKED", 0, 0, (), ("Review root is not a directory.",))

    findings: list[SecurityFinding] = []
    warnings: list[str] = []
    files_scanned = 0
    bytes_scanned = 0
    truncated = False
    for current, directories, filenames in os.walk(resolved, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories
            if name not in _IGNORED_DIRS and not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink() or not path.is_file():
                continue
            files_scanned += 1
            if files_scanned > _MAX_FILES:
                truncated = True
                warnings.append(f"Scan stopped at the {_MAX_FILES}-file limit.")
                break
            try:
                size = path.stat().st_size
                if size > _MAX_FILE_BYTES or bytes_scanned + size > _MAX_TOTAL_BYTES:
                    truncated = True
                    warnings.append(f"Scan stopped at a file or total byte limit; remaining output was not reviewed.")
                    break
                raw = path.read_bytes()
                text = raw.decode("utf-8", errors="replace")
            except OSError:
                truncated = True
                warnings.append("A file could not be read; review coverage is incomplete.")
                continue
            bytes_scanned += len(raw)
            suffix = path.suffix.lower()
            basename = path.name.lower()
            rule_ids = set(_RULES_BY_EXTENSION.get(suffix, set()))
            if basename in {"package.json", "composer.json", "cargo.toml", "pom.xml", "pyproject.toml", "build.gradle", "build.gradle.kts", "go.mod", "gemfile", "requirements.txt", "package.swift", "cmakelists.txt"}:
                rule_ids.add("MANIFEST_LIFECYCLE_HOOK")
            relative = path.relative_to(resolved).as_posix()
            for rule_id in sorted(rule_ids):
                severity, description, pattern = _ALL_RULES[rule_id]
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    findings.append(SecurityFinding(rule_id, severity, relative, line, description))
                    if len(findings) >= 500:
                        truncated = True
                        warnings.append("Finding list was capped at 500; additional findings may exist.")
                        break
                if len(findings) >= 500:
                    break
            # Redaction detector is a separate generic heuristic for credential patterns.
            redacted = redact_text(text)
            if redacted != text and not any(f.path == relative and f.rule_id.startswith("SECRET_") for f in findings):
                findings.append(SecurityFinding(
                    "REDACTION_PATTERN", "MEDIUM", relative, 1,
                    "The file contains a recognizable sensitive-data pattern; review it without exposing the value.",
                ))
            if truncated:
                break
        if truncated:
            break
    findings.sort(key=lambda item: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(item.severity, 3), item.path, item.line, item.rule_id))
    if truncated:
        status = "INCOMPLETE"
    elif any(item.severity == "HIGH" for item in findings):
        status = "FAILED"
    elif any(item.severity == "MEDIUM" for item in findings):
        status = "REVIEW_REQUIRED"
    else:
        status = "PASSED"
    warnings.append("This bounded heuristic scan is not a comprehensive security audit and cannot prove generated code is safe.")
    return StaticSecurityReview(status, min(files_scanned, _MAX_FILES), bytes_scanned, tuple(findings), tuple(warnings))
