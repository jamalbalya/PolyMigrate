"""Persistent, evidence-gated migration knowledge store."""
from __future__ import annotations
import hashlib
from contextlib import contextmanager
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from polymigrate.security.redaction import redact_payload

@dataclass(frozen=True)
class KnowledgeRecord:
    record_id: str
    problem_fingerprint: str
    source_language: str
    target_language: str
    toolchain_fingerprint: str
    project_scope: str
    solution: dict[str, Any]
    validation_evidence: tuple[dict[str, Any], ...]
    verified: bool
    shareable: bool = False

def fingerprint_payload(payload: Any) -> str:
    """Create a stable SHA-256 fingerprint without storing the payload itself."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

class MigrationKnowledgeStore:
    """SQLite store; cross-project reuse is opt-in and verified records only."""
    REQUIRED_VERIFICATION_GATES = frozenset({
        "target_build", "unit_tests", "integration_tests", "e2e_tests",
        "behavior_comparison", "security_review", "dependency_wiring", "dependency_integration",
    })

    @classmethod
    def _has_verified_evidence(cls, evidence: tuple[dict[str, Any], ...]) -> bool:
        statuses: dict[str, list[str]] = {}
        for item in evidence:
            if not isinstance(item, dict):
                return False
            gate, status = item.get("gate"), item.get("status")
            if isinstance(gate, str) and isinstance(status, str):
                statuses.setdefault(gate, []).append(status.upper())
                if gate in cls.REQUIRED_VERIFICATION_GATES and status.upper() != "PASSED":
                    return False
        return all(
            statuses.get(gate) and all(status == "PASSED" for status in statuses[gate])
            for gate in cls.REQUIRED_VERIFICATION_GATES
        )
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS migration_knowledge (
                    record_id TEXT PRIMARY KEY, problem_fingerprint TEXT NOT NULL,
                    source_language TEXT NOT NULL, target_language TEXT NOT NULL,
                    toolchain_fingerprint TEXT NOT NULL, project_scope TEXT NOT NULL,
                    solution_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
                    shareable INTEGER NOT NULL CHECK (shareable IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_knowledge_lookup
                ON migration_knowledge(problem_fingerprint, source_language, target_language, toolchain_fingerprint, verified)
            """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Commit/rollback transactions and always close the underlying handle."""
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, record: KnowledgeRecord) -> None:
        if not record.record_id.strip() or not record.project_scope.strip():
            raise ValueError("record_id and project_scope are required")
        if not record.problem_fingerprint or not record.toolchain_fingerprint:
            raise ValueError("problem and toolchain fingerprints are required")
        if record.shareable and not record.verified:
            raise ValueError("unverified knowledge cannot be shared across projects")
        if not isinstance(record.solution, dict):
            raise ValueError("knowledge solution must be an object")
        if redact_payload(record.solution) != record.solution:
            raise ValueError("knowledge solution contains recognizable secret material")
        if record.verified and not self._has_verified_evidence(record.validation_evidence):
            raise ValueError("verified knowledge requires PASSED evidence for all required validation gates")
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT verified, shareable FROM migration_knowledge WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()
            # Trust is monotonic: a later unverified draft must never downgrade
            # an already verified record or remove its cross-project shareability.
            if existing is not None:
                if bool(existing["verified"]) and not record.verified:
                    raise ValueError("an unverified record cannot overwrite verified knowledge")
                if bool(existing["shareable"]) and not record.shareable:
                    raise ValueError("a non-shareable record cannot downgrade shareable knowledge")
            connection.execute("""
                INSERT INTO migration_knowledge (
                    record_id, problem_fingerprint, source_language, target_language,
                    toolchain_fingerprint, project_scope, solution_json, evidence_json, verified, shareable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    problem_fingerprint=excluded.problem_fingerprint, source_language=excluded.source_language,
                    target_language=excluded.target_language, toolchain_fingerprint=excluded.toolchain_fingerprint,
                    project_scope=excluded.project_scope, solution_json=excluded.solution_json,
                    evidence_json=excluded.evidence_json, verified=excluded.verified, shareable=excluded.shareable
            """, (record.record_id, record.problem_fingerprint, record.source_language, record.target_language,
                  record.toolchain_fingerprint, record.project_scope, json.dumps(record.solution, sort_keys=True),
                  json.dumps(list(record.validation_evidence), sort_keys=True), int(record.verified), int(record.shareable)))

    def find_reusable(self, *, problem_fingerprint: str, source_language: str, target_language: str,
                      toolchain_fingerprint: str, project_scope: str) -> list[KnowledgeRecord]:
        with self._connection() as connection:
            rows = connection.execute("""
                SELECT * FROM migration_knowledge
                WHERE problem_fingerprint = ? AND source_language = ? AND target_language = ?
                  AND toolchain_fingerprint = ? AND verified = 1 AND (project_scope = ? OR shareable = 1)
                ORDER BY shareable DESC, record_id ASC
            """, (problem_fingerprint, source_language, target_language, toolchain_fingerprint, project_scope)).fetchall()
        records = [KnowledgeRecord(
            record_id=row["record_id"], problem_fingerprint=row["problem_fingerprint"],
            source_language=row["source_language"], target_language=row["target_language"],
            toolchain_fingerprint=row["toolchain_fingerprint"], project_scope=row["project_scope"],
            solution=json.loads(row["solution_json"]), validation_evidence=tuple(json.loads(row["evidence_json"])),
            verified=bool(row["verified"]), shareable=bool(row["shareable"]),
        ) for row in rows]
        # Re-check stored evidence at read time so legacy or manually edited rows cannot bypass the gate.
        return [record for record in records if self._has_verified_evidence(record.validation_evidence)]


    def find_cached_draft(self, *, problem_fingerprint: str, source_language: str,
                          target_language: str, toolchain_fingerprint: str,
                          project_scope: str) -> list[KnowledgeRecord]:
        """Find unverified drafts only within the exact same project scope."""
        with self._connection() as connection:
            rows = connection.execute("""
                SELECT * FROM migration_knowledge
                WHERE problem_fingerprint = ? AND source_language = ? AND target_language = ?
                  AND toolchain_fingerprint = ? AND project_scope = ?
                  AND verified = 0 AND shareable = 0
                ORDER BY record_id ASC
            """, (problem_fingerprint, source_language, target_language,
                  toolchain_fingerprint, project_scope)).fetchall()
        return [KnowledgeRecord(
            record_id=row["record_id"],
            problem_fingerprint=row["problem_fingerprint"],
            source_language=row["source_language"],
            target_language=row["target_language"],
            toolchain_fingerprint=row["toolchain_fingerprint"],
            project_scope=row["project_scope"],
            solution=json.loads(row["solution_json"]),
            validation_evidence=tuple(json.loads(row["evidence_json"])),
            verified=bool(row["verified"]),
            shareable=bool(row["shareable"]),
        ) for row in rows]

    def promote_verified(self, record_id: str, validation_evidence: tuple[dict[str, Any], ...],
                         *, shareable: bool = False) -> KnowledgeRecord:
        """Promote a draft only when every required gate has explicit PASSED evidence."""
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM migration_knowledge WHERE record_id = ?", (record_id,)).fetchone()
        if row is None:
            raise ValueError("knowledge record was not found")
        solution = json.loads(row["solution_json"])
        if isinstance(solution, dict):
            summary = solution.get("summary")
            if isinstance(summary, dict) and summary.get("decision_type") == "candidate":
                summary["implementation_status"] = "VERIFIED_INTEGRATION"
                summary["cache_status"] = "VERIFIED_SHARED" if shareable else "VERIFIED_PROJECT_SCOPED"
        record = KnowledgeRecord(
            record_id=row["record_id"], problem_fingerprint=row["problem_fingerprint"],
            source_language=row["source_language"], target_language=row["target_language"],
            toolchain_fingerprint=row["toolchain_fingerprint"], project_scope=row["project_scope"],
            solution=solution, validation_evidence=tuple(validation_evidence),
            verified=True, shareable=shareable,
        )
        self.save(record)
        return record

    def count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM migration_knowledge").fetchone()[0])
