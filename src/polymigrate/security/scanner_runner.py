"""Execute a small allowlist of local security scanners without shell interpolation.

Scanner availability is environment-dependent. Missing tools or incomplete reports
remain INCOMPLETE; this module never treats an absent scanner as a clean scan.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from polymigrate.security.evidence_gate import SecurityEvidenceResult, evaluate_security_evidence

_RUNNER_ID = "polymigrate_trusted_scanner_runner_v1"
_RULES_PATH = Path(__file__).with_name("semgrep_rules.yml")
_PROFILES: dict[str, tuple[str, ...]] = {
    "python": ("semgrep", "bandit"),
    "go": ("semgrep", "gosec"),
    "javascript": ("semgrep",),
    "typescript": ("semgrep",),
    "java": ("semgrep",),
    "kotlin": ("semgrep",),
    "rust": ("semgrep",),
    "csharp": ("semgrep",),
    "c": ("semgrep",),
    "cpp": ("semgrep",),
    "ruby": ("semgrep",),
    "php": ("semgrep",),
    "swift": ("semgrep",),
}
_MAX_BINARY_BYTES = 300_000_000
_VERSION_TIMEOUT_SECONDS = 10
_SCAN_TIMEOUT_SECONDS = 120


def _binary_sha256(path: Path) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_BINARY_BYTES:
        raise ValueError("scanner executable is not a regular file within the size limit")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_args(scanner_id: str, executable: str) -> list[str]:
    return [executable, "-version"] if scanner_id == "gosec" else [executable, "--version"]


def _scan_args(scanner_id: str, executable: str, root: Path) -> list[str]:
    if scanner_id == "semgrep":
        return [
            executable, "scan", "--config", str(_RULES_PATH),
            "--json", "--quiet", "--no-git-ignore", str(root),
        ]
    if scanner_id == "bandit":
        return [executable, "-r", str(root), "-f", "json", "-q"]
    if scanner_id == "gosec":
        return [executable, "-fmt=json", "./..."]
    raise ValueError("scanner is not allowlisted")


def _finding_severity(scanner_id: str, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    severity = value.upper()
    if scanner_id == "semgrep":
        return {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}.get(severity)
    if severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}:
        return severity
    return None


def _parse_report(scanner_id: str, payload: Any) -> tuple[list[dict[str, str]], bool]:
    if not isinstance(payload, dict):
        return [], False
    if scanner_id == "semgrep":
        if payload.get("errors") not in ([], None):
            return [], False
        raw = payload.get("results")
        if not isinstance(raw, list):
            return [], False
        findings = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("check_id"), str):
                return [], False
            extra = item.get("extra")
            severity = _finding_severity(scanner_id, extra.get("severity") if isinstance(extra, dict) else None)
            if severity is None:
                return [], False
            findings.append({"severity": severity, "rule_id": item["check_id"]})
        return findings, True
    if scanner_id == "bandit":
        if payload.get("errors") not in ([], None):
            return [], False
        raw = payload.get("results")
        if not isinstance(raw, list):
            return [], False
        findings = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("test_id"), str):
                return [], False
            severity = _finding_severity(scanner_id, item.get("issue_severity"))
            if severity is None:
                return [], False
            findings.append({"severity": severity, "rule_id": item["test_id"]})
        return findings, True
    if scanner_id == "gosec":
        if payload.get("Errors") not in ([], None) or payload.get("GolangErrors") not in ([], None):
            return [], False
        raw = payload.get("Issues") or []
        if not isinstance(raw, list):
            return [], False
        findings = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("rule_id"), str):
                return [], False
            severity = _finding_severity(scanner_id, item.get("severity"))
            if severity is None:
                return [], False
            findings.append({"severity": severity, "rule_id": item["rule_id"]})
        return findings, True
    return [], False


def run_trusted_security_scanners(root: Path, language: str) -> SecurityEvidenceResult:
    """Run required locally installed scanners from an allowlist and verify provenance.

    Semgrep uses a repository-bundled rules file and does not request a remote ruleset.
    Bandit and gosec are additional required scanners for Python and Go respectively.
    """
    root = root.resolve()
    if root.is_symlink() or not root.is_dir():
        return evaluate_security_evidence(
            (), required_scanners=_PROFILES.get(language, ("semgrep",))
        )
    required = _PROFILES.get(language, ("semgrep",))
    evidence: list[dict[str, Any]] = []
    for scanner_id in required:
        executable = shutil.which(scanner_id)
        if not executable:
            continue
        try:
            binary_digest = _binary_sha256(Path(executable))
            version_result = subprocess.run(
                _version_args(scanner_id, executable), cwd=root, capture_output=True,
                text=True, timeout=_VERSION_TIMEOUT_SECONDS, check=False, shell=False,
                env={**os.environ, "SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"},
            )
            version_text = (version_result.stdout or version_result.stderr or "").strip()
            if version_result.returncode != 0 or not version_text:
                continue
            scan_result = subprocess.run(
                _scan_args(scanner_id, executable, root), cwd=root, capture_output=True,
                text=True, timeout=_SCAN_TIMEOUT_SECONDS, check=False, shell=False,
                env={**os.environ, "SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"},
            )
            raw_report = scan_result.stdout or ""
            try:
                payload = json.loads(raw_report)
            except json.JSONDecodeError:
                payload = None
            findings, report_valid = _parse_report(scanner_id, payload)
            allowed_codes = {0, 1} if scanner_id in {"bandit", "gosec"} else {0}
            complete = report_valid and scan_result.returncode in allowed_codes
            evidence.append({
                "scanner_id": scanner_id,
                "scanner_version": version_text.splitlines()[0][:256],
                "complete": complete,
                # Normalized runner status: zero means the report was complete.
                # tool_exit_code retains the scanner's actual process exit status.
                "exit_code": 0 if complete else scan_result.returncode,
                "tool_exit_code": scan_result.returncode,
                "report_sha256": hashlib.sha256(raw_report.encode("utf-8", errors="replace")).hexdigest(),
                "scanner_binary_sha256": binary_digest,
                "runner_id": _RUNNER_ID,
                "findings": findings,
            })
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return evaluate_security_evidence(evidence, required_scanners=required, provenance_verified=True)
