"""Execute a small allowlist of locally discovered scanners without shell interpolation.

Scanner availability is environment-dependent. Missing tools or incomplete reports
remain INCOMPLETE; this module never treats an absent scanner as a clean scan.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import replace
import subprocess
from pathlib import Path
from typing import Any

from polymigrate.security.evidence_gate import SecurityEvidenceResult, evaluate_security_evidence

_RUNNER_ID = "polymigrate_local_scanner_runner_v1"
_RULES_PATH = Path(__file__).with_name("semgrep_rules.yml")
_BASE_SCANNERS = ("semgrep", "gitleaks", "osv-scanner")
_PROFILES: dict[str, tuple[str, ...]] = {
    "python": (*_BASE_SCANNERS, "bandit"),
    "go": (*_BASE_SCANNERS, "gosec"),
    "javascript": _BASE_SCANNERS,
    "typescript": _BASE_SCANNERS,
    "java": _BASE_SCANNERS,
    "kotlin": _BASE_SCANNERS,
    "rust": _BASE_SCANNERS,
    "csharp": _BASE_SCANNERS,
    "c": _BASE_SCANNERS,
    "cpp": _BASE_SCANNERS,
    "ruby": _BASE_SCANNERS,
    "php": _BASE_SCANNERS,
    "swift": _BASE_SCANNERS,
}
_MAX_BINARY_BYTES = 300_000_000
_MAX_RULES_BYTES = 5_000_000
_VERSION_TIMEOUT_SECONDS = 10
_SCAN_TIMEOUT_SECONDS = 120
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _binary_sha256(path: Path) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_BINARY_BYTES:
        raise ValueError("scanner executable is not a regular file within the size limit")
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rules_sha256() -> str:
    """Hash the bundled Semgrep rules only if the path is a bounded regular file."""
    if _RULES_PATH.is_symlink():
        raise ValueError("Semgrep rules path must not be a symlink")
    resolved = _RULES_PATH.resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > _MAX_RULES_BYTES:
        raise ValueError("Semgrep rules file is not a regular file within the size limit")
    return _binary_sha256(resolved)


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
    if scanner_id == "gitleaks":
        return [
            executable, "dir", "--no-banner", "--no-color", "--redact=100",
            "--report-format=json", "--report-path=-", str(root),
        ]
    if scanner_id == "osv-scanner":
        return [executable, "scan", "source", "--format", "json", "--recursive", str(root)]
    raise ValueError("scanner is not allowlisted")


def _finding_severity(scanner_id: str, value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    severity = value.upper()
    if scanner_id == "semgrep":
        return {"ERROR": "HIGH", "WARNING": "MEDIUM", "INFO": "LOW"}.get(severity)
    if scanner_id in {"gitleaks", "osv-scanner"}:
        # Any discovered secret or known vulnerable dependency is a blocking finding.
        return "HIGH"
    if severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}:
        return severity
    return None


def _parse_report(scanner_id: str, payload: Any) -> tuple[list[dict[str, str]], bool]:
    if scanner_id == "gitleaks":
        if not isinstance(payload, list):
            return [], False
        findings: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("RuleID"), str) or not item["RuleID"].strip():
                return [], False
            findings.append({"severity": "HIGH", "rule_id": "GITLEAKS:" + item["RuleID"]})
        return findings, True
    if not isinstance(payload, dict):
        return [], False
    if scanner_id == "osv-scanner":
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            return [], False
        findings: list[dict[str, str]] = []
        for result in raw_results:
            if not isinstance(result, dict) or not isinstance(result.get("packages"), list):
                return [], False
            for package in result["packages"]:
                if not isinstance(package, dict):
                    return [], False
                vulnerabilities = package.get("vulnerabilities", [])
                if not isinstance(vulnerabilities, list):
                    return [], False
                for vulnerability in vulnerabilities:
                    if not isinstance(vulnerability, dict) or not isinstance(vulnerability.get("id"), str):
                        return [], False
                    vulnerability_id = vulnerability["id"].strip()
                    if not vulnerability_id:
                        return [], False
                    findings.append({"severity": "HIGH", "rule_id": "OSV:" + vulnerability_id})
        return findings, True
    if scanner_id == "semgrep":
        if not isinstance(payload.get("errors"), list) or payload["errors"]:
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
        if not isinstance(payload.get("errors"), list) or payload["errors"]:
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
        if (not isinstance(payload.get("Errors"), list) or payload["Errors"]
                or not isinstance(payload.get("GolangErrors"), list) or payload["GolangErrors"]):
            return [], False
        raw = payload.get("Issues")
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


def run_local_security_scanners(root: Path, language: str) -> SecurityEvidenceResult:
    """Run required locally installed scanners and record execution evidence.

    Semgrep uses a repository-bundled rules file and does not request a remote ruleset.
    Scanner binary hashes and the Semgrep rules hash must match operator-managed pins;
    missing or mismatched pins keep scanner provenance unverified. The scanner set is
    intentionally limited and does not establish a comprehensive audit.
    Gitleaks checks for exposed secrets, OSV-Scanner checks lockfiles/manifests for known dependency vulnerabilities, and Bandit/gosec provide language-specific checks for Python/Go.
    """
    if root.is_symlink() or not root.is_dir():
        return evaluate_security_evidence(
            (), required_scanners=_PROFILES.get(language, ("semgrep",))
        )
    root = root.resolve()
    required = _PROFILES.get(language, ("semgrep",))
    evidence: list[dict[str, Any]] = []
    trusted_scanners: set[str] = set()
    provenance_warnings: list[str] = []
    for scanner_id in required:
        executable = shutil.which(scanner_id)
        if not executable:
            continue
        try:
            binary_digest = _binary_sha256(Path(executable))
            rule_digest = None
            if scanner_id == "semgrep":
                try:
                    rule_digest = _rules_sha256()
                except (OSError, ValueError):
                    provenance_warnings.append(
                        "Bundled Semgrep rules file is missing, symlinked, or exceeds the size limit."
                    )
                    continue
            pin_variable = "POLYMIGRATE_TRUSTED_SCANNER_SHA256_" + scanner_id.upper().replace("-", "_")
            expected_digest = os.environ.get(pin_variable, "").strip()
            binary_trusted = False
            if not expected_digest or not _SHA256.fullmatch(expected_digest):
                provenance_warnings.append(
                    f"Scanner '{scanner_id}' was executed but its binary SHA-256 is not pinned in {pin_variable}."
                )
            elif expected_digest.lower() != binary_digest:
                provenance_warnings.append(
                    f"Scanner '{scanner_id}' binary SHA-256 does not match {pin_variable}; provenance is unverified."
                )
            else:
                binary_trusted = True
            rules_trusted = scanner_id != "semgrep"
            if scanner_id == "semgrep":
                rules_pin = os.environ.get("POLYMIGRATE_TRUSTED_SEMGREP_RULES_SHA256", "").strip()
                if not rules_pin or not _SHA256.fullmatch(rules_pin):
                    provenance_warnings.append(
                        "Bundled Semgrep rules SHA-256 is not pinned in POLYMIGRATE_TRUSTED_SEMGREP_RULES_SHA256."
                    )
                elif rules_pin.lower() != rule_digest:
                    provenance_warnings.append(
                        "Bundled Semgrep rules SHA-256 does not match POLYMIGRATE_TRUSTED_SEMGREP_RULES_SHA256; provenance is unverified."
                    )
                else:
                    rules_trusted = True
            if binary_trusted and rules_trusted:
                trusted_scanners.add(scanner_id)
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
            if scanner_id in {"bandit", "gosec"}:
                complete = report_valid and scan_result.returncode in {0, 1}
            elif scanner_id in {"gitleaks", "osv-scanner"}:
                complete = report_valid and (
                    scan_result.returncode == 0
                    or (scan_result.returncode == 1 and bool(findings))
                )
            else:
                complete = report_valid and scan_result.returncode == 0
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
                **({"rules_sha256": rule_digest} if rule_digest is not None else {}),
                "runner_id": _RUNNER_ID,
                "findings": findings,
            })
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    result = evaluate_security_evidence(
        evidence, required_scanners=required, execution_provenance_recorded=True
    )
    provenance_verified = (
        result.scanner_execution_recorded and trusted_scanners == set(required)
    )
    if not provenance_verified and not provenance_warnings:
        provenance_warnings.append(
            "Scanner execution evidence is incomplete; binary provenance cannot be verified."
        )
    return replace(
        result,
        scanner_provenance_verified=provenance_verified,
        provenance_warnings=tuple(provenance_warnings),
    )
