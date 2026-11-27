"""Host-owned SQLite fixture for the simulated break-glass runtime slice.

One file holds both business tables, the request ledger, callback decisions
and audit rows, the resume outcomes and the effect outbox. The relay tables are
installed by ``wiring.install``. Only this fixture writes SQL; the handlers and
the public-API driver never build statements. Every read helper opens its own
connection, so tests can observe durable state independently of the engine.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

TENANT = "tenant-a"
SCOPE = "team-1"

SCHEMA = """
CREATE TABLE grant_requests (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    sensitivity TEXT NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE audit_sessions (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE request_ledger (
    tenant TEXT NOT NULL,
    principal TEXT NOT NULL,
    action TEXT NOT NULL,
    request_key TEXT NOT NULL,
    intent_fingerprint TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    action_version TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (tenant, principal, action, request_key)
);
CREATE INDEX ledger_execution ON request_ledger(execution_id);
CREATE TABLE outbox (
    id TEXT PRIMARY KEY,
    dedup_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING'
);
CREATE TABLE approval_decisions (
    callback_key TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    intent_fingerprint TEXT NOT NULL,
    reason TEXT NOT NULL,
    principal TEXT NOT NULL,
    approval TEXT NOT NULL,
    authority_revision TEXT,
    recorded_at TEXT NOT NULL
);
CREATE TABLE approval_audit (
    attempt_id TEXT PRIMARY KEY,
    callback_key TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    principal TEXT NOT NULL,
    code TEXT NOT NULL,
    detail TEXT,
    decision TEXT,
    intent_fingerprint TEXT,
    recorded_at TEXT NOT NULL
);
CREATE TABLE approval_resume_outcomes (
    callback_key TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT,
    recorded_at TEXT NOT NULL
);
"""

_TABLES = frozenset(
    {
        "grant_requests",
        "audit_sessions",
        "request_ledger",
        "outbox",
        "approval_decisions",
        "approval_audit",
        "approval_resume_outcomes",
        "effect_delivery",
        "notification_inbox",
        "local_notifications",
    }
)


def build_database(
    path: Path,
    *,
    duration_minutes: int = 30,
    sensitivity: str = "ROUTINE",
) -> Path:
    """Create a fresh seeded database, replacing any file at ``path``."""
    target = Path(path)
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target)) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO grant_requests "
            "(id, tenant, scope, status, duration_minutes, sensitivity, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (("AGR-1", TENANT, SCOPE, "PENDING", duration_minutes, sensitivity, 1),),
        )
        connection.execute(
            "INSERT INTO audit_sessions (id, tenant, scope, status, version) "
            "VALUES (?, ?, ?, ?, ?)",
            ("AS-1", TENANT, SCOPE, "NEW", 1),
        )
        connection.commit()
    return target


def _rows(path: Path, statement: str, values: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(Path(path), timeout=5)) as connection:
        return [tuple(row) for row in connection.execute(statement, values).fetchall()]


def grant_state(path: Path, key: str = "AGR-1") -> tuple[object, ...] | None:
    """Read one request's status, duration, sensitivity and version."""
    rows = _rows(
        path,
        "SELECT status, duration_minutes, sensitivity, version FROM grant_requests WHERE id = ?",
        (key,),
    )
    return rows[0] if rows else None


def session_state(path: Path, key: str = "AS-1") -> tuple[object, ...] | None:
    """Read one audit session's status and version."""
    rows = _rows(path, "SELECT status, version FROM audit_sessions WHERE id = ?", (key,))
    return rows[0] if rows else None


def ledger_state(path: Path) -> list[tuple[object, ...]]:
    """Read the request ledger as ``(action_version, status, execution_id)`` rows."""
    return _rows(
        path,
        "SELECT action_version, status, execution_id FROM request_ledger ORDER BY execution_id",
    )


def outbox_state(path: Path) -> list[tuple[object, ...]]:
    """Read the outbox as ``(dedup_id, status)`` rows."""
    return _rows(path, "SELECT dedup_id, status FROM outbox ORDER BY id")


def effect_state(path: Path) -> list[tuple[object, ...]]:
    """Read the relay's effect state as ``(status, attempts)`` rows."""
    return _rows(path, "SELECT status, attempts FROM effect_delivery ORDER BY dedup_id")


def count_rows(path: Path, table: str) -> int:
    """Read one durable count from a connection independent of the engine."""
    if table not in _TABLES:
        raise ValueError(f"unknown durable table {table!r}.")
    return cast(int, _rows(path, f"SELECT COUNT(*) FROM {table}")[0][0])


__all__ = [
    "SCHEMA",
    "SCOPE",
    "TENANT",
    "build_database",
    "count_rows",
    "effect_state",
    "grant_state",
    "ledger_state",
    "outbox_state",
    "session_state",
]
