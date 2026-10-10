"""Persistent, evidence-gated migration knowledge store."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
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

    def save(self, record: KnowledgeRecord) -> None:
        if not record.record_id.strip() or not record.project_scope.strip():
            raise ValueError("record_id and project_scope are required")
        if not record.problem_fingerprint or not record.toolchain_fingerprint:
            raise ValueError("problem and toolchain fingerprints are required")
        with self._connect() as connection:
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
        with self._connect() as connection:
            rows = connection.execute("""
                SELECT * FROM migration_knowledge
                WHERE problem_fingerprint = ? AND source_language = ? AND target_language = ?
                  AND toolchain_fingerprint = ? AND verified = 1 AND (project_scope = ? OR shareable = 1)
                ORDER BY shareable DESC, record_id ASC
            """, (problem_fingerprint, source_language, target_language, toolchain_fingerprint, project_scope)).fetchall()
        return [KnowledgeRecord(
            record_id=row["record_id"], problem_fingerprint=row["problem_fingerprint"],
            source_language=row["source_language"], target_language=row["target_language"],
            toolchain_fingerprint=row["toolchain_fingerprint"], project_scope=row["project_scope"],
            solution=json.loads(row["solution_json"]), validation_evidence=tuple(json.loads(row["evidence_json"])),
            verified=bool(row["verified"]), shareable=bool(row["shareable"]),
        ) for row in rows]


    def find_cached_draft(self, *, problem_fingerprint: str, source_language: str,
                          target_language: str, toolchain_fingerprint: str,
                          project_scope: str) -> list[KnowledgeRecord]:
        """Find unverified drafts only within the exact same project scope."""
        with self._connect() as connection:
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

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM migration_knowledge").fetchone()[0])
