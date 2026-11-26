"""Local relay: committed outbox only, separate effect state, durable dedup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from resume_support import (
    APPROVE_PERMISSION,
    OLD_GRAPH,
    RESERVE_PERMISSION,
    ROOT_KEY,
    TENANT,
    case,
    database,
    deployment,
    grants,
    parameters,
    principal,
    provider,
    resume_case,
    sqlite,
)

from codology import (
    EFFECT_READ_PERMISSION,
    EffectReadDenied,
    PermanentDelivery,
    Principal,
    TransientDelivery,
    bind_action,
    deliver_committed,
    read_effect_status,
    snapshot,
)
from codology.engine import invoke
from codology.ledger import serialize
from codology.relay import OutboxMessage
from codology.relay_adapter import (
    SQLiteLocalReceiver,
    SQLiteRelayStore,
    create_relay_schema,
)


class _Once:
    """Return a deterministic injected failure on one call, then stay silent."""

    def __init__(self, failure: Exception) -> None:
        self.failure: Exception | None = failure

    def __call__(self, message: OutboxMessage) -> Exception | None:
        failure, self.failure = self.failure, None
        return failure


def _rows(path: Path, statement: str, values: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Read durable state through a connection independent of the relay."""
    connection = sqlite3.connect(path)
    try:
        return connection.execute(statement, values).fetchall()
    finally:
        connection.close()


def _business(path: Path) -> tuple[object, ...]:
    return (
        _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'"),
        _rows(path, "SELECT reserved, version FROM budgets WHERE id = 'B-1'"),
        _rows(path, "SELECT status, execution_id FROM request_ledger"),
        _rows(path, "SELECT COUNT(*) FROM approval_resume_outcomes"),
    )


def _reader(tenant: str = TENANT) -> Principal:
    return Principal("alice", tenant, frozenset({EFFECT_READ_PERMISSION}))


def _direct_commit(path: Path, request_key: str):
    pro = sqlite(path)
    return invoke(
        linked=OLD_GRAPH,
        action=ROOT_KEY,
        bound=bind_action(snapshot(OLD_GRAPH), deployment(), ROOT_KEY),
        provider=pro,
        principal=principal(APPROVE_PERMISSION, RESERVE_PERMISSION),
        grants=grants(),
        parameters=parameters(provider(path)),
        request_key=request_key,
    )


def _installed(path: Path) -> tuple[SQLiteRelayStore, SQLiteLocalReceiver]:
    create_relay_schema(path)
    return SQLiteRelayStore(path), SQLiteLocalReceiver(path)


def test_relay_delivers_committed_effect_once_and_keeps_execution_committed(
    tmp_path: Path,
) -> None:
    path = database(tmp_path, amount=50_000)
    result = _direct_commit(path, "tenant-a:alice:approve:PO-1:relay-success")
    assert result.execution is not None
    execution_id = result.execution.execution_id

    store, receiver = _installed(path)
    before = _business(path)
    assert _rows(path, "SELECT status FROM outbox") == [("PENDING",)]
    with pytest.raises(EffectReadDenied):
        read_effect_status(store, Principal("alice", TENANT, frozenset()), execution_id)
    pending = read_effect_status(store, _reader(), execution_id)
    assert len(pending) == 1 and pending[0].status == "PENDING"

    first = deliver_committed(store, receiver)
    assert len(first) == 1
    assert first[0].status == "DELIVERED" and first[0].recorded and not first[0].replayed
    assert first[0].dedup_id == _rows(path, "SELECT dedup_id FROM outbox")[0][0]
    assert _rows(path, "SELECT status FROM outbox") == [("DELIVERED",)]
    assert _rows(path, "SELECT attempts FROM effect_delivery") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM notification_inbox") == [(1,)]
    assert _business(path) == before
    assert before[2] == [("COMMITTED", execution_id)]

    states = read_effect_status(SQLiteRelayStore(path), _reader(), execution_id)
    assert len(states) == 1
    assert states[0].status == "DELIVERED" and states[0].attempts == 1
    assert states[0].dedup_id == first[0].dedup_id

    again = deliver_committed(SQLiteRelayStore(path), SQLiteLocalReceiver(path))
    assert again == ()
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]


def test_relay_retries_a_transient_failure_with_the_same_dedup_id(tmp_path: Path) -> None:
    path = database(tmp_path, amount=50_000)
    result = _direct_commit(path, "tenant-a:alice:approve:PO-1:relay-transient")
    assert result.execution is not None
    execution_id = result.execution.execution_id

    create_relay_schema(path)
    store = SQLiteRelayStore(path)
    before = _business(path)
    receiver = SQLiteLocalReceiver(
        path, before_write=_Once(TransientDelivery("warehouse temporarily unavailable"))
    )
    first = deliver_committed(store, receiver)
    assert len(first) == 1 and first[0].status == "PENDING_RETRY" and first[0].recorded
    assert _rows(path, "SELECT status FROM outbox") == [("PENDING_RETRY",)]
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(0,)]
    assert _business(path) == before
    states = read_effect_status(store, _reader(), execution_id)
    assert len(states) == 1 and states[0].status == "PENDING_RETRY" and states[0].attempts == 1

    stored_dedup = _rows(path, "SELECT dedup_id FROM outbox")[0][0]
    second = deliver_committed(SQLiteRelayStore(path), SQLiteLocalReceiver(path))
    assert len(second) == 1
    assert second[0].status == "DELIVERED" and second[0].dedup_id == stored_dedup
    assert not second[0].replayed
    assert _rows(path, "SELECT status FROM outbox") == [("DELIVERED",)]
    assert _rows(path, "SELECT attempts FROM effect_delivery") == [(2,)]
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]
    assert _business(path) == before


def test_relay_marks_a_permanent_failure_without_retrying(tmp_path: Path) -> None:
    path = database(tmp_path, amount=50_000)
    result = _direct_commit(path, "tenant-a:alice:approve:PO-1:relay-permanent")
    assert result.execution is not None
    execution_id = result.execution.execution_id

    store, _ = _installed(path)
    before = _business(path)
    receiver = SQLiteLocalReceiver(
        path, before_write=lambda message: PermanentDelivery("warehouse address is invalid")
    )
    failed = deliver_committed(store, receiver)
    assert len(failed) == 1 and failed[0].status == "FAILED" and failed[0].recorded
    assert _rows(path, "SELECT status FROM outbox") == [("FAILED",)]
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(0,)]
    assert _business(path) == before

    states = read_effect_status(store, _reader(), execution_id)
    assert len(states) == 1 and states[0].status == "FAILED" and states[0].attempts == 1
    assert deliver_committed(store, SQLiteLocalReceiver(path)) == ()
    assert _rows(path, "SELECT attempts FROM effect_delivery") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(0,)]


def test_lost_ack_after_durable_receiver_write_replays_one_local_notification(
    tmp_path: Path,
) -> None:
    target = case(tmp_path)
    committed = resume_case(target)
    assert committed.attempt.code == "COMMITTED"
    execution_id = target.execution_id

    create_relay_schema(target.path)
    before = _business(target.path)
    assert before[2] == [("COMMITTED", execution_id)]
    first_receiver = SQLiteLocalReceiver(
        target.path, after_write=_Once(TransientDelivery("receiver acknowledgement lost"))
    )
    first = deliver_committed(SQLiteRelayStore(target.path), first_receiver)
    assert len(first) == 1 and first[0].status == "PENDING_RETRY"
    assert _rows(target.path, "SELECT status FROM outbox") == [("PENDING_RETRY",)]
    assert _rows(target.path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]

    second = deliver_committed(SQLiteRelayStore(target.path), SQLiteLocalReceiver(target.path))
    assert len(second) == 1
    assert second[0].status == "DELIVERED" and second[0].replayed and second[0].recorded
    assert second[0].dedup_id == first[0].dedup_id
    assert _rows(target.path, "SELECT status FROM outbox") == [("DELIVERED",)]
    assert _rows(target.path, "SELECT attempts FROM effect_delivery") == [(2,)]
    assert _rows(target.path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]
    assert _rows(target.path, "SELECT COUNT(*) FROM notification_inbox") == [(1,)]
    assert _business(target.path) == before
    assert _rows(target.path, "SELECT COUNT(*) FROM approval_resume_outcomes") == [(1,)]


def test_relay_ignores_waiting_executions_and_uncommitted_outbox_rows(tmp_path: Path) -> None:
    target = case(tmp_path)
    execution_id = target.execution_id
    create_relay_schema(target.path)
    before = _business(target.path)

    store = SQLiteRelayStore(target.path)
    assert deliver_committed(store, SQLiteLocalReceiver(target.path)) == ()
    assert read_effect_status(store, _reader(), execution_id) == ()
    assert _rows(target.path, "SELECT status FROM request_ledger") == [("AWAITING_APPROVAL",)]
    assert _rows(target.path, "SELECT COUNT(*) FROM outbox") == [(0,)]

    connection = sqlite3.connect(target.path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        document = {
            "id": "uncommitted:effect",
            "effect": {"identity": "procurement.warehouse_order_approved", "version": "1.0.0"},
            "execution_id": execution_id,
            "action": {"identity": ROOT_KEY.identity, "version": ROOT_KEY.version},
            "approver": None,
            "dedup_id": "uncommitted-dedup",
            "payload": {"order": "PO-1"},
        }
        connection.execute(
            "INSERT INTO outbox (id, dedup_id, payload, status) VALUES (?, ?, ?, 'PENDING')",
            ("uncommitted:effect", "uncommitted-dedup", serialize(document)),
        )
        assert deliver_committed(store, SQLiteLocalReceiver(target.path)) == ()
    finally:
        connection.rollback()
        connection.close()

    assert deliver_committed(store, SQLiteLocalReceiver(target.path)) == ()
    assert _rows(target.path, "SELECT COUNT(*) FROM local_notifications") == [(0,)]
    assert _business(target.path) == before


def test_effect_state_gate_is_tenant_scoped_and_dedup_conflict_fails_closed(
    tmp_path: Path,
) -> None:
    path = database(tmp_path, amount=50_000)
    result = _direct_commit(path, "tenant-a:alice:approve:PO-1:relay-conflict")
    assert result.execution is not None
    execution_id = result.execution.execution_id

    store, _ = _installed(path)
    dedup_id = str(_rows(path, "SELECT dedup_id FROM outbox")[0][0])
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO notification_inbox (dedup_id, id, document) VALUES (?, ?, ?)",
            (dedup_id, "notice:old", serialize({"dedup_id": "different"})),
        )
        connection.commit()
    finally:
        connection.close()

    assert read_effect_status(store, _reader("other-tenant"), execution_id) == ()
    deliveries = deliver_committed(store, SQLiteLocalReceiver(path))
    assert len(deliveries) == 1 and deliveries[0].status == "FAILED"
    assert _rows(path, "SELECT status FROM outbox") == [("FAILED",)]
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(0,)]
    states = read_effect_status(store, _reader(), execution_id)
    assert len(states) == 1 and states[0].status == "FAILED"
