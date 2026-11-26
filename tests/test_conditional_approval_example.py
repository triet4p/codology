"""Cross-layer checks for the conditional-approval consumer example.

Every public-API result is paired with a read from a connection that is
independent of the engine, relay and host adapters.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

import pytest

from codology import DefinitionKey, Principal
from codology.decision import DecisionResult
from codology.engine import ActionResult
from codology.relay import EffectReadDenied, PermanentDelivery, TransientDelivery
from examples.conditional_approval import consumer, database, wiring
from examples.conditional_approval import declarations as d
from examples.conditional_approval.__main__ import main

ROOT_KEY = DefinitionKey(d.ROOT, "2.0.0")
NEXT_KEY = DefinitionKey(d.ROOT, "2.1.0")
AWAITING = "AWAITING_APPROVAL"
COMMITTED = "COMMITTED"


def _rows(path: Path, statement: str, values: Sequence[object] = ()) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(statement, tuple(values)).fetchall()
    finally:
        connection.close()


def _host(tmp_path: Path, name: str, **seed: object) -> tuple[Path, wiring.Host]:
    path = wiring.install(tmp_path / name, **seed)
    return path, wiring.open_host(path)


def _invoke(host: wiring.Host) -> ActionResult:
    order = consumer.typed_ref(host, wiring.ORDER_KEY, d.PurchaseOrder, "PO-1")
    budget = consumer.typed_ref(host, wiring.BUDGET_KEY, d.Budget, "B-1")
    return consumer.request_approval(
        host,
        order=order,  # type: ignore[arg-type]
        budget=budget,  # type: ignore[arg-type]
        request_key=wiring.REQUEST_KEY,
        reason=wiring.REASON,
    )


def _replay(host: wiring.Host) -> ActionResult:
    order = consumer.typed_ref(host, wiring.ORDER_KEY, d.PurchaseOrder, "PO-1")
    budget = consumer.typed_ref(host, wiring.BUDGET_KEY, d.Budget, "B-1")
    return consumer.replay_on_new_default(
        host,
        order=order,  # type: ignore[arg-type]
        budget=budget,  # type: ignore[arg-type]
        request_key=wiring.REQUEST_KEY,
        reason=wiring.REASON,
    )


def _approve(host: wiring.Host, result: ActionResult) -> DecisionResult:
    assert result.execution is not None and result.execution.required_approval is not None
    return consumer.decide(host, result.execution.execution_id, result.execution.required_approval)


def _finish(
    host: wiring.Host, result: ActionResult, provider: object | None = None
) -> ActionResult:
    assert result.execution is not None and result.execution.required_approval is not None
    return consumer.resume_execution(
        host,
        result.execution.execution_id,
        result.execution.required_approval.callback_key,
        provider=provider,  # type: ignore[arg-type]
    )


def test_documented_entrypoint_reports_all_scenarios(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(tmp_path / "cli") == 0
    output = capsys.readouterr().out
    assert "ALL CHECKS PASSED" in output
    for label in (
        "[below threshold]",
        "[waiting, restart, pinned replay]",
        "[callback deny, duplicate, reject]",
        "[reapproval]",
        "[resume contention]",
        "[lost commit acknowledgement]",
        "[relay failures]",
    ):
        assert label in output


def test_below_threshold_commits_order_budget_ledger_and_outbox_together(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "below.sqlite3", amount=99_999)
    result = _invoke(host)
    assert result.attempt.code == COMMITTED
    assert result.execution is not None

    order = _rows(path, "SELECT status, amount, version FROM purchase_orders WHERE id = 'PO-1'")[0]
    budget = _rows(path, "SELECT reserved, version FROM budgets WHERE id = 'B-1'")[0]
    ledger = _rows(path, "SELECT execution_id, status FROM request_ledger")
    outbox = _rows(path, "SELECT dedup_id, payload FROM outbox")
    assert (order, budget) == (("APPROVED", 99_999, 2), (99_999, 2))
    assert ledger == [(result.execution.execution_id, COMMITTED)]
    assert len(outbox) == 1 and result.execution.execution_id in str(outbox[0][1])

    assert consumer.relay_once(host)[0].status == "DELIVERED"
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM notification_inbox") == [(1,)]
    assert _rows(path, "SELECT status, attempts FROM effect_delivery") == [("DELIVERED", 1)]


def test_at_threshold_waits_without_business_writes_or_held_lock(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "waiting.sqlite3", amount=100_000)
    result = _invoke(host)
    assert result.attempt.code == AWAITING
    assert result.execution is not None and result.execution.required_approval is not None

    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(path, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [(0, 1)]
    assert _rows(path, "SELECT COUNT(*) FROM outbox") == [(0,)]
    assert _rows(path, "SELECT status FROM request_ledger") == [(AWAITING,)]

    with closing(sqlite3.connect(path, timeout=5)) as connection:
        connection.execute("UPDATE purchase_orders SET status = 'CANCELLED' WHERE id = 'PO-1'")
        connection.commit()
    assert _rows(path, "SELECT status FROM purchase_orders WHERE id = 'PO-1'") == [("CANCELLED",)]


def test_restart_and_new_default_replay_keep_the_pinned_execution(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "pin.sqlite3", amount=120_000)
    first = _invoke(host)
    assert first.execution is not None and first.execution.required_approval is not None
    assert first.execution.deduplicated is False

    reopened = wiring.open_host(path)
    replay = _replay(reopened)
    assert replay.attempt.code == AWAITING
    assert replay.execution is not None
    assert replay.execution.execution_id == first.execution.execution_id
    assert replay.execution.pinned_manifest == first.execution.pinned_manifest
    assert replay.execution.deduplicated is True
    assert _rows(path, "SELECT COUNT(*) FROM request_ledger") == [(1,)]

    _approve(reopened, first)
    assert _finish(reopened, first).attempt.code == COMMITTED
    assert _rows(path, "SELECT reserved FROM budgets WHERE id = 'B-1'") == [(120_000,)]
    assert _rows(path, "SELECT action_version, status FROM request_ledger") == [
        ("2.0.0", COMMITTED)
    ]


def test_denied_callbacks_and_duplicate_keep_one_pending_decision(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "callbacks.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    approval = pending.execution.required_approval

    outsider = consumer.decide(
        host,
        execution_id,
        approval,
        principal=wiring.outsider(),
        authority=wiring.HostAuthority(roles=(), permissions=()),
    )
    misuse = consumer.decide(host, execution_id, approval, fingerprint="0" * 64)
    assert outsider.attempt.code == "DENIED" and outsider.decision is None
    assert misuse.attempt.reason == "KEY_MISUSE"
    assert _rows(path, "SELECT COUNT(*) FROM approval_decisions") == [(0,)]
    assert _rows(path, "SELECT status FROM request_ledger") == [(AWAITING,)]

    first = consumer.decide(host, execution_id, approval)
    duplicate = consumer.decide(host, execution_id, approval)
    assert first.decision is not None and duplicate.decision is not None
    assert duplicate.execution is not None and duplicate.execution.deduplicated is True
    assert _rows(path, "SELECT COUNT(*) FROM approval_decisions") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM approval_audit") == [(4,)]
    assert _rows(path, "SELECT COUNT(*) FROM outbox") == [(0,)]


def test_valid_reject_ends_terminal_without_business_write(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "reject.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    rejected = consumer.decide(
        host,
        pending.execution.execution_id,
        pending.execution.required_approval,
        decision="REJECT",
        reason="budget withdrawn",
    )
    assert rejected.attempt.code == "REJECTED"
    assert _rows(path, "SELECT status FROM request_ledger") == [("REJECTED",)]
    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(path, "SELECT reserved FROM budgets WHERE id = 'B-1'") == [(0,)]
    assert _rows(path, "SELECT COUNT(*) FROM outbox") == [(0,)]


def test_material_change_mints_new_approval_then_commits_once(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "reapproval.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    old = pending.execution.required_approval
    _approve(host, pending)

    database.update_amount(path, 150_000)
    changed = _finish(host, pending)
    assert changed.attempt.code == AWAITING
    assert changed.attempt.reason == "REAPPROVAL_REQUIRED"
    assert changed.execution is not None and changed.execution.required_approval is not None
    new = changed.execution.required_approval
    assert new.callback_key != old.callback_key
    assert new.intent_fingerprint != old.intent_fingerprint

    stale = consumer.resume_execution(host, execution_id, old.callback_key)
    assert stale.attempt.reason == "KEY_MISUSE"
    assert _rows(path, "SELECT reserved FROM budgets WHERE id = 'B-1'") == [(0,)]

    consumer.decide(host, execution_id, new)
    assert _finish(host, changed).attempt.code == COMMITTED
    assert _rows(path, "SELECT status, amount, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("APPROVED", 150_000, 2)
    ]
    assert _rows(path, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [(150_000, 2)]
    assert _rows(path, "SELECT COUNT(*) FROM outbox") == [(1,)]
    assert _rows(path, "SELECT outcome FROM approval_resume_outcomes") == [
        ("REAPPROVAL",),
        (COMMITTED,),
    ]


def test_contention_commits_one_resume_outcome_and_one_reservation(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "contention.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    key = pending.execution.required_approval.callback_key
    _approve(host, pending)
    host.authority = wiring.HostAuthority(barrier=threading.Barrier(2))

    results: list[ActionResult] = []

    def run() -> None:
        results.append(consumer.resume_execution(host, execution_id, key))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not any(thread.is_alive() for thread in threads)
    committed = [item for item in results if item.attempt.code == COMMITTED]
    assert committed and all(
        item.execution is not None and item.execution.execution_id == execution_id
        for item in committed
    )
    assert _rows(path, "SELECT COUNT(*) FROM approval_resume_outcomes") == [(1,)]
    assert _rows(path, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [(120_000, 2)]
    assert _rows(path, "SELECT status, amount FROM purchase_orders WHERE id = 'PO-1'") == [
        ("APPROVED", 120_000)
    ]


def test_lost_resume_ack_reconciles_without_a_second_reservation(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "lost-ack.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    _approve(host, pending)

    uncertain = _finish(host, pending, provider=wiring.InterruptedProvider(path, mode="after"))
    assert uncertain.attempt.code == "UNKNOWN"
    assert _rows(path, "SELECT status FROM request_ledger") == [(COMMITTED,)]

    fresh = wiring.open_host(path)
    by_key = consumer.reconcile_request(fresh, ROOT_KEY, wiring.REQUEST_KEY)
    by_id = consumer.reconcile_execution(fresh, execution_id)
    assert by_key.attempt.code == COMMITTED
    assert by_id.execution is not None and by_id.execution.status == COMMITTED
    replay = _finish(fresh, pending)
    assert replay.attempt.code == COMMITTED
    assert replay.execution is not None and replay.execution.deduplicated is True

    assert _rows(path, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [(120_000, 2)]
    assert _rows(path, "SELECT COUNT(*) FROM request_ledger") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM outbox") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM approval_resume_outcomes") == [(1,)]


def test_transient_relay_failure_retries_and_keeps_execution_committed(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "transient.sqlite3", amount=120_000)
    pending = _invoke(host)
    _approve(host, pending)
    finished = _finish(host, pending)
    assert finished.execution is not None
    execution_id = finished.execution.execution_id

    calls: list[int] = []

    def transient(message: object) -> Exception | None:
        calls.append(1)
        return TransientDelivery("receiver unavailable") if len(calls) == 1 else None

    store = wiring.SQLiteRelayStore(path)
    first = consumer.relay_once(
        host, store=store, receiver=wiring.SQLiteLocalReceiver(path, before_write=transient)
    )
    statuses = consumer.effect_status(host, execution_id, store=store)
    assert first[0].status == "PENDING_RETRY" and statuses[0].status == "PENDING_RETRY"
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(0,)]

    retry = consumer.relay_once(host)
    assert retry[0].status == "DELIVERED"
    assert consumer.effect_status(host, execution_id)[0].status == "DELIVERED"
    assert _rows(path, "SELECT status, attempts FROM effect_delivery") == [("DELIVERED", 2)]
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM notification_inbox") == [(1,)]
    assert _rows(path, "SELECT status FROM request_ledger") == [(COMMITTED,)]


def test_permanent_relay_failure_does_not_uncommit_the_action(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "permanent.sqlite3", amount=120_000)
    pending = _invoke(host)
    _approve(host, pending)
    _finish(host, pending)

    receiver = wiring.SQLiteLocalReceiver(
        path, before_write=lambda message: PermanentDelivery("sink rejected")
    )
    delivery = consumer.relay_once(host, receiver=receiver)
    assert delivery[0].status == "FAILED"
    assert consumer.relay_once(host) == ()
    assert _rows(path, "SELECT status FROM outbox") == [("FAILED",)]
    assert _rows(path, "SELECT status FROM effect_delivery") == [("FAILED",)]
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(0,)]
    assert _rows(path, "SELECT status FROM request_ledger") == [(COMMITTED,)]
    assert _rows(path, "SELECT reserved FROM budgets WHERE id = 'B-1'") == [(120_000,)]


def test_lost_relay_ack_replays_one_durable_notification(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "relay-ack.sqlite3", amount=120_000)
    pending = _invoke(host)
    _approve(host, pending)
    finished = _finish(host, pending)
    assert finished.execution is not None
    execution_id = finished.execution.execution_id

    acks: list[int] = []

    def lost(message: object) -> Exception | None:
        acks.append(1)
        return TransientDelivery("ack lost") if len(acks) == 1 else None

    store = wiring.SQLiteRelayStore(path)
    first = consumer.relay_once(
        host, store=store, receiver=wiring.SQLiteLocalReceiver(path, after_write=lost)
    )
    assert first[0].status == "PENDING_RETRY"
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]
    assert _rows(path, "SELECT COUNT(*) FROM notification_inbox") == [(1,)]
    assert _rows(path, "SELECT status FROM request_ledger") == [(COMMITTED,)]

    replay = consumer.relay_once(host, store=store)
    assert replay[0].status == "DELIVERED" and replay[0].replayed is True
    assert _rows(path, "SELECT COUNT(*) FROM local_notifications") == [(1,)]
    assert _rows(path, "SELECT status, attempts FROM effect_delivery") == [("DELIVERED", 2)]
    assert consumer.effect_status(host, execution_id)[0].status == "DELIVERED"


def test_effect_status_gate_is_permissioned_and_tenant_scoped(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "effect-gate.sqlite3", amount=120_000)
    pending = _invoke(host)
    _approve(host, pending)
    finished = _finish(host, pending)
    assert finished.execution is not None
    execution_id = finished.execution.execution_id

    without_permission = Principal(wiring.REQUESTER, wiring.TENANT, frozenset({wiring.READ}))
    with pytest.raises(EffectReadDenied):
        consumer.effect_status_for(
            host,
            execution_id,
            principal=without_permission,  # type: ignore[arg-type]
        )
    foreign = wiring.reader()
    foreign = Principal(foreign.identity, "other-tenant", foreign.permissions)
    assert consumer.effect_status_for(host, execution_id, principal=foreign) == ()  # type: ignore[arg-type]
    assert _rows(path, "SELECT status FROM request_ledger") == [(COMMITTED,)]
