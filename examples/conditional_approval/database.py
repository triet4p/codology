"""Host-owned SQLite fixture for the conditional-approval example.

One file holds the orders, the Finance budget, the request ledger, callback
audit rows and the outbox. The relay tables are installed by the wiring layer.
Only this fixture writes raw SQL; the consumer reads and writes exclusively
through engine ports.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

TENANT = "tenant-a"
FOREIGN_TENANT = "tenant-b"
SCOPE = "team-1"

SCHEMA = """
CREATE TABLE purchase_orders (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    amount INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE budgets (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL,
    scope TEXT NOT NULL,
    ceiling INTEGER NOT NULL,
    reserved INTEGER NOT NULL,
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


def build_database(
    path: Path,
    *,
    amount: int = 120_000,
    status: str = "PENDING",
    ceiling: int = 1_000_000,
) -> Path:
    """Create a fresh seeded database, replacing any file at ``path``."""
    target = Path(path)
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target)) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO purchase_orders "
            "(id, tenant, scope, status, amount, created_at, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ("PO-1", TENANT, SCOPE, status, amount, 1, 1),
                ("PO-9", FOREIGN_TENANT, SCOPE, "PENDING", 150_000, 2, 1),
            ),
        )
        connection.executemany(
            "INSERT INTO budgets (id, tenant, scope, ceiling, reserved, version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                ("B-1", TENANT, SCOPE, ceiling, 0, 1),
                ("B-9", FOREIGN_TENANT, SCOPE, 1_000_000, 0, 1),
            ),
        )
        connection.commit()
    return target


def update_amount(path: Path, amount: int, *, key: str = "PO-1") -> None:
    """Change world state through the host fixture, outside the engine gate."""
    with closing(sqlite3.connect(Path(path), timeout=5)) as connection:
        connection.execute("UPDATE purchase_orders SET amount = ? WHERE id = ?", (amount, key))
        connection.commit()


def count_rows(path: Path, table: str) -> int:
    """Read a durable count from a connection independent of the engine."""
    with closing(sqlite3.connect(Path(path))) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


__all__ = [
    "FOREIGN_TENANT",
    "SCHEMA",
    "SCOPE",
    "TENANT",
    "build_database",
    "count_rows",
    "update_amount",
]
