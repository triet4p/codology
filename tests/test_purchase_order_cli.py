"""Subprocess checks for the independent purchase-order CLI consumer.

Every CLI run is a real subprocess over a file-backed SQLite fixture; each API
envelope is paired with a read from a connection that is independent of the
engine and the host adapters.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from examples.conditional_approval import wiring

ROOT = Path(__file__).resolve().parents[1]
AWAITING = "AWAITING_APPROVAL"
COMMITTED = "COMMITTED"
REQUEST_KEY = "tenant-a:alice:approve:PO-1:001"
REASON = "approved after budget check"

type Json = dict[str, Json] | list[Json] | str | int | float | bool | None


def _cli(database: Path, command: str, *arguments: str) -> Json:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "examples.purchase_order_cli",
            command,
            "--db",
            str(database),
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return cast(Json, json.loads(completed.stdout))


def _at(document: Json, *path: str) -> Json:
    current = document
    for key in path:
        assert isinstance(current, dict), f"{path} stops at a non-object value"
        current = current[key]
    return current


def _items(value: Json) -> list[dict[str, Json]]:
    assert isinstance(value, list), f"expected a list, got {type(value)!r}"
    rows: list[dict[str, Json]] = []
    for item in value:
        assert isinstance(item, dict), "expected an object in the list"
        rows.append(item)
    return rows


def _text(value: Json) -> str:
    assert isinstance(value, str), f"expected a string, got {type(value)!r}"
    return value


def _rows(path: Path, statement: str, values: Sequence[object] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(statement, tuple(values)).fetchall()
    finally:
        connection.close()


def _invoke(database: Path) -> Json:
    return _cli(
        database,
        "invoke",
        "--order",
        "PO-1",
        "--budget",
        "B-1",
        "--reason",
        REASON,
        "--request-key",
        REQUEST_KEY,
    )


def _approve(database: Path, execution_id: str, callback_key: str, fingerprint: str) -> Json:
    return _cli(
        database,
        "approve",
        "--as",
        "approver",
        "--execution-id",
        execution_id,
        "--callback-key",
        callback_key,
        "--fingerprint",
        fingerprint,
        "--reason",
        "budget confirmed",
    )


def _resume(database: Path, execution_id: str, callback_key: str) -> Json:
    return _cli(
        database,
        "resume",
        "--execution-id",
        execution_id,
        "--callback-key",
        callback_key,
    )


def _pending(database: Path) -> tuple[Json, str, str, str]:
    payload = _invoke(database)
    execution_id = _text(_at(payload, "result", "execution", "execution_id"))
    callback_key = _text(_at(payload, "result", "execution", "required_approval", "callback_key"))
    fingerprint = _text(
        _at(payload, "result", "execution", "required_approval", "intent_fingerprint")
    )
    return payload, execution_id, callback_key, fingerprint


def test_query_reports_only_rows_the_host_grant_covers(tmp_path: Path) -> None:
    database = wiring.install(tmp_path / "orders.sqlite3", amount=120_000)
    payload = _cli(database, "query", "--resource", "orders", "--status", "PENDING")
    rows = _items(_at(payload, "page", "rows"))
    assert [_text(row["id"]) for row in rows] == ["PO-1"]
    assert _at(payload, "page", "count") == 1
    assert _at(payload, "definition", "identity") == "procurement.purchase_order"
    assert _at(payload, "definition", "version") == "1.0.0"
    # The foreign-tenant row exists but the engine's tenant/scope policy hides it.
    assert [row[0] for row in _rows(database, "SELECT id FROM purchase_orders ORDER BY id")] == [
        "PO-1",
        "PO-9",
    ]

    budgets = _items(_at(_cli(database, "query", "--resource", "budgets"), "page", "rows"))
    assert [_text(row["id"]) for row in budgets] == ["B-1"]


def test_invoke_takes_refs_from_rows_and_waits_without_business_writes(
    tmp_path: Path,
) -> None:
    database = wiring.install(tmp_path / "pending.sqlite3", amount=120_000)
    payload = _invoke(database)
    assert _at(payload, "result", "attempt", "code") == AWAITING
    assert _at(payload, "action", "version") == "2.0.0"
    assert _at(payload, "refs", "order", "instance_version") == 1
    assert _at(payload, "refs", "budget", "instance_version") == 1
    approval = _at(payload, "result", "execution", "required_approval")
    assert isinstance(approval, dict)
    assert _text(approval["callback_key"])
    assert _text(approval["intent_fingerprint"])
    assert _at(payload, "next", "command") == "approve"
    assert _at(payload, "next", "callback_key") == approval["callback_key"]

    assert _rows(database, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(database, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [(0, 1)]
    assert _rows(database, "SELECT COUNT(*) FROM outbox") == [(0,)]
    assert _rows(database, "SELECT status FROM request_ledger") == [(AWAITING,)]


def test_wrong_caller_is_denied_and_the_execution_stays_pending(tmp_path: Path) -> None:
    database = wiring.install(tmp_path / "denied.sqlite3", amount=120_000)
    _, execution_id, callback_key, fingerprint = _pending(database)
    denied = _cli(
        database,
        "approve",
        "--as",
        "outsider",
        "--execution-id",
        execution_id,
        "--callback-key",
        callback_key,
        "--fingerprint",
        fingerprint,
        "--reason",
        "not my call",
    )
    assert _at(denied, "result", "attempt", "code") == "DENIED"
    assert _at(denied, "result", "decision") is None
    reconciled = _cli(database, "reconcile", "--execution-id", execution_id)
    assert _at(reconciled, "result", "execution", "status") == AWAITING
    assert _rows(database, "SELECT COUNT(*) FROM approval_decisions") == [(0,)]
    assert _rows(database, "SELECT COUNT(*) FROM approval_audit") == [(1,)]

    approved = _approve(database, execution_id, callback_key, fingerprint)
    assert _at(approved, "result", "attempt", "reason") == "APPROVED"
    assert _at(approved, "result", "decision", "decision") == "APPROVE"
    assert _at(approved, "next", "command") == "resume"
    assert _rows(database, "SELECT status FROM request_ledger") == [(AWAITING,)]
    assert _rows(database, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(database, "SELECT COUNT(*) FROM outbox") == [(0,)]


def test_approve_resume_commits_and_relay_delivers_once(tmp_path: Path) -> None:
    database = wiring.install(tmp_path / "commit.sqlite3", amount=120_000)
    _, execution_id, callback_key, fingerprint = _pending(database)
    _approve(database, execution_id, callback_key, fingerprint)
    assert _rows(database, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [(0, 1)]
    assert _rows(database, "SELECT COUNT(*) FROM approval_decisions") == [(1,)]

    finished = _resume(database, execution_id, callback_key)
    assert _at(finished, "result", "attempt", "code") == COMMITTED
    assert _at(finished, "result", "execution", "execution_id") == execution_id
    assert _rows(database, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("APPROVED", 2)
    ]
    assert _rows(database, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [
        (120_000, 2)
    ]
    assert _rows(database, "SELECT status FROM request_ledger") == [(COMMITTED,)]
    assert _rows(database, "SELECT COUNT(*) FROM outbox") == [(1,)]
    assert _rows(database, "SELECT COUNT(*) FROM approval_resume_outcomes") == [(1,)]

    relayed = _cli(database, "relay", "--execution-id", execution_id)
    deliveries = _items(_at(relayed, "deliveries"))
    assert [delivery["status"] for delivery in deliveries] == ["DELIVERED"]
    effects = _items(_at(relayed, "effects"))
    assert [effect["status"] for effect in effects] == ["DELIVERED"]
    again = _cli(database, "relay")
    assert _items(_at(again, "deliveries")) == []
    assert _rows(database, "SELECT COUNT(*) FROM local_notifications") == [(1,)]
    assert _rows(database, "SELECT COUNT(*) FROM notification_inbox") == [(1,)]
    assert _rows(database, "SELECT status, attempts FROM effect_delivery") == [("DELIVERED", 1)]


def test_replay_and_reconcile_keep_the_original_key_without_extra_writes(
    tmp_path: Path,
) -> None:
    database = wiring.install(tmp_path / "replay.sqlite3", amount=120_000)
    first = _invoke(database)
    execution_id = _text(_at(first, "result", "execution", "execution_id"))
    replay = _invoke(database)
    assert _at(replay, "result", "attempt", "code") == AWAITING
    assert _at(replay, "result", "execution", "deduplicated") is True
    assert _at(replay, "result", "execution", "execution_id") == execution_id
    assert _rows(database, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(database, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [(0, 1)]
    assert _rows(database, "SELECT COUNT(*) FROM request_ledger") == [(1,)]

    callback_key = _text(_at(first, "result", "execution", "required_approval", "callback_key"))
    fingerprint = _text(
        _at(first, "result", "execution", "required_approval", "intent_fingerprint")
    )
    _approve(database, execution_id, callback_key, fingerprint)
    _resume(database, execution_id, callback_key)

    reconciled = _cli(database, "reconcile", "--request-key", REQUEST_KEY)
    assert _at(reconciled, "lookup", "by") == "request_key"
    assert _at(reconciled, "result", "execution", "status") == COMMITTED
    assert _at(reconciled, "result", "execution", "deduplicated") is True
    assert _at(reconciled, "result", "execution", "execution_id") == execution_id
    assert _rows(database, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("APPROVED", 2)
    ]
    assert _rows(database, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [
        (120_000, 2)
    ]
    assert _rows(database, "SELECT COUNT(*) FROM outbox") == [(1,)]
    assert _rows(database, "SELECT COUNT(*) FROM request_ledger") == [(1,)]
    assert _rows(database, "SELECT COUNT(*) FROM approval_decisions") == [(1,)]
    assert _rows(database, "SELECT COUNT(*) FROM approval_resume_outcomes") == [(1,)]


def test_unconfirmed_commit_guides_reconcile_with_the_original_id(tmp_path: Path) -> None:
    database = wiring.install(tmp_path / "lost-ack.sqlite3", amount=120_000)
    _, execution_id, callback_key, fingerprint = _pending(database)
    _approve(database, execution_id, callback_key, fingerprint)

    uncertain = _cli(
        database,
        "resume",
        "--execution-id",
        execution_id,
        "--callback-key",
        callback_key,
        "--simulate-lost-ack",
        "after",
    )
    assert _at(uncertain, "result", "attempt", "code") == "UNKNOWN"
    assert _at(uncertain, "next", "command") == "reconcile"
    assert _at(uncertain, "next", "execution_id") == execution_id
    note = _text(_at(uncertain, "next", "note"))
    assert "original" in note and "do not mint a new request key" in note

    reconciled = _cli(database, "reconcile", "--execution-id", execution_id)
    assert _at(reconciled, "result", "execution", "status") == COMMITTED
    retry = _resume(database, execution_id, callback_key)
    assert _at(retry, "result", "attempt", "code") == COMMITTED
    assert _at(retry, "result", "execution", "deduplicated") is True
    assert _rows(database, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [
        (120_000, 2)
    ]
    assert _rows(database, "SELECT COUNT(*) FROM outbox") == [(1,)]
    assert _rows(database, "SELECT COUNT(*) FROM approval_resume_outcomes") == [(1,)]
