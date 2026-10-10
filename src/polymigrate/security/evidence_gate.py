"""Fail-closed aggregation for externally produced security scan evidence.

This module does not run scanners and does not claim that a scanner suite is
comprehensive. It only evaluates whether a declared, required scanner set
produced complete, well-formed evidence and whether that evidence contains
blocking findings. Callers must establish scanner provenance separately.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$")
_SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


@dataclass(frozen=True)
class SecurityEvidenceResult:
    status: str
    required_scanners: tuple[str, ...]
    accepted_scanners: tuple[str, ...]
    missing_scanners: tuple[str, ...]
    errors: tuple[str, ...]
    findings: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope": "external_scanner_evidence_aggregation",
            "required_scanners": list(self.required_scanners),
            "accepted_scanners": list(self.accepted_scanners),
            "missing_scanners": list(self.missing_scanners),
            "errors": list(self.errors),
            "findings": list(self.findings),
            "not_a_comprehensive_audit": True,
            "scanner_provenance_verified": False,
        }


def evaluate_security_evidence(
    evidence: Iterable[Mapping[str, Any]],
    *,
    required_scanners: Iterable[str],
) -> SecurityEvidenceResult:
    """Aggregate scanner evidence without converting missing evidence to PASS.

    Each evidence item must contain scanner_id, scanner_version, complete,
    exit_code, report_sha256, and findings. A finding has severity and rule_id;
    any additional message/path fields are deliberately omitted from the
    returned summary to avoid accidentally echoing secrets from scanner output.
    """
    errors: list[str] = []
    required_values: set[str] = set()
    for index, item in enumerate(required_scanners):
        if not isinstance(item, str) or not item.strip() or not _IDENTIFIER.fullmatch(item.strip()):
            errors.append(f"Required scanner entry {index} is malformed.")
            continue
        required_values.add(item.strip())
    required = tuple(sorted(required_values))
    accepted: set[str] = set()
    missing = set(required)
    findings_out: list[dict[str, Any]] = []
    if not required:
        errors.append("No required security scanners were configured.")

    seen: set[str] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, Mapping):
            errors.append(f"Evidence item {index} is not an object.")
            continue
        scanner = item.get("scanner_id")
        if not isinstance(scanner, str) or not scanner.strip():
            errors.append(f"Evidence item {index} has no scanner_id.")
            continue
        scanner = scanner.strip()
        if not _IDENTIFIER.fullmatch(scanner):
            errors.append(f"Evidence item {index} has a malformed scanner_id.")
            continue
        if scanner not in required:
            errors.append(f"Evidence from unconfigured scanner '{scanner}' was ignored.")
            continue
        if scanner in seen:
            errors.append(f"Duplicate evidence for scanner '{scanner}'.")
            continue
        seen.add(scanner)
        version = item.get("scanner_version")
        if not isinstance(version, str) or not version.strip():
            errors.append(f"Scanner '{scanner}' has no version evidence.")
            continue
        if item.get("complete") is not True:
            errors.append(f"Scanner '{scanner}' did not report a complete scan.")
            continue
        exit_code = item.get("exit_code")
        if isinstance(exit_code, bool) or not isinstance(exit_code, int) or exit_code != 0:
            errors.append(f"Scanner '{scanner}' did not exit successfully.")
            continue
        digest = item.get("report_sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            errors.append(f"Scanner '{scanner}' has no valid report SHA-256.")
            continue
        raw_findings = item.get("findings")
        if not isinstance(raw_findings, list):
            errors.append(f"Scanner '{scanner}' has no findings list.")
            continue
        scanner_findings: list[dict[str, Any]] = []
        malformed = False
        for finding in raw_findings:
            if not isinstance(finding, Mapping):
                malformed = True
                break
            severity = finding.get("severity")
            rule_id = finding.get("rule_id")
            if not isinstance(severity, str) or severity.upper() not in _SEVERITY:
                malformed = True
                break
            if not isinstance(rule_id, str) or not rule_id.strip() or not _IDENTIFIER.fullmatch(rule_id.strip()):
                malformed = True
                break
            scanner_findings.append({"scanner_id": scanner, "severity": severity.upper(), "rule_id": rule_id.strip()})
        if malformed:
            errors.append(f"Scanner '{scanner}' contains malformed finding data.")
            continue
        accepted.add(scanner)
        missing.discard(scanner)
        findings_out.extend(scanner_findings)

    findings_out.sort(key=lambda item: (_SEVERITY[item["severity"]], item["scanner_id"], item["rule_id"]))
    if errors or missing:
        status = "INCOMPLETE"
    elif any(item["severity"] in {"CRITICAL", "HIGH"} for item in findings_out):
        status = "FAILED"
    elif any(item["severity"] == "MEDIUM" for item in findings_out):
        status = "REVIEW_REQUIRED"
    else:
        status = "PASSED"
    return SecurityEvidenceResult(
        status=status,
        required_scanners=required,
        accepted_scanners=tuple(sorted(accepted)),
        missing_scanners=tuple(sorted(missing)),
        errors=tuple(errors),
        findings=tuple(findings_out),
    )
