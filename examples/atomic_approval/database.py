"""File-backed SQLite fixture for the executable approval example.

The schema mirrors the resources enlisted by ``wiring``. One SQLite file holds
the orders, the Finance budget and the request ledger, so the adapter can open
one physical transaction for every write and the ledger row. Seeded rows also
include a second tenant that authorized queries must never expose.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from examples.atomic_approval.wiring import SCOPE, TENANT_A, TENANT_B

SCHEMA = """
CREATE TABLE purchase_orders (
    id TEXT PRIMARY KEY,
    tenant TEXT NOT NULL,
    scope TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_amount INTEGER,
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
"""

_ORDERS = (
    ("PO-1", TENANT_A, SCOPE, "PENDING_APPROVAL", None, 1, 1),
    ("PO-2", TENANT_A, SCOPE, "PENDING_APPROVAL", None, 2, 1),
    ("PO-9", TENANT_B, SCOPE, "PENDING_APPROVAL", None, 3, 1),
)

_BUDGETS = (
    ("B-1", TENANT_A, SCOPE, 100_000, 0, 1),
    ("B-9", TENANT_B, SCOPE, 100_000, 0, 1),
)


def build_database(path: Path) -> Path:
    """Create a fresh seeded database, replacing any file at ``path``."""
    target = Path(path)
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target)) as connection:
        connection.executescript(SCHEMA)
        connection.executemany(
            "INSERT INTO purchase_orders "
            "(id, tenant, scope, status, approved_amount, created_at, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            _ORDERS,
        )
        connection.executemany(
            "INSERT INTO budgets (id, tenant, scope, ceiling, reserved, version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            _BUDGETS,
        )
        connection.commit()
    return target


__all__ = ["SCHEMA", "build_database"]
