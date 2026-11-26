"""Transactional outbox: typed intents, one session, stable dedup and no send."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

import pytest
from resume_support import (
    APPROVE_PERMISSION,
    APPROVER,
    BUDGET,
    OLD_GRAPH,
    ORDER,
    RESERVE_PERMISSION,
    ROOT_KEY,
    SESSION,
    HostAuthority,
    approver,
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
    OUTBOX_RESOURCE,
    Capability,
    DefinitionKey,
    Deployment,
    EffectSessionMismatch,
    Enlistment,
    MissingCapability,
    ModuleDeclarations,
    Provider,
    bind_action,
    link,
    load,
    payload_of,
    snapshot,
)
from codology.adapter import SQLiteProvider, SQLiteUnitOfWork
from codology.decision import approve, reject
from codology.declarations import Action, Effect, Module, ObjectRef, ObjectType, Value
from codology.declarations.behavior import Approval, Param
from codology.engine import HandlerCtx, invoke
from codology.ports import SessionPlan, TransactionUnavailable

_EFFECT = "procurement.warehouse_order_approved"
_GATE = "procurement.effect_gate"
_GATE_KEY = DefinitionKey(_GATE, "1.0.0")
_ORDER_KEY = DefinitionKey(ORDER, "1.0.0")

_mode: Literal["valid", "undeclared", "wrong_type", "live"] = "valid"


class PurchaseOrder(ObjectType):
    identity = ORDER
    version = "1.0.0"
    keyType = "PO"

    status: str
    amount: int


class Notice(Value):
    identity = "procurement.notice"
    version = "1.0.0"

    order: str


class NotifyWarehouse(Effect):
    identity = "procurement.gate_notice"
    version = "1.0.0"
    payload = Notice
    dedupKey = ("order",)


class NotDeclared(Effect):
    identity = "procurement.not_declared"
    version = "1.0.0"
    payload = Notice
    dedupKey = ("order",)


class EffectGate(Action):
    identity = _GATE
    version = "1.0.0"

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = (PurchaseOrder,)
    writes = (PurchaseOrder,)
    permission = APPROVE_PERMISSION
    approval = Approval.conditional(
        when=Param("order").amount >= 100_000,
        role="finance_director",
        self_approval=False,
    )
    effects = (NotifyWarehouse,)

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, reason: str) -> None:
        ctx.require(order.status == "PENDING", reason="order_not_pending")
        ctx.uow.register_mutation(order, status="APPROVED", expectedVersion=order.version)
        if _mode == "undeclared":
            ctx.uow.enqueue_effect(NotDeclared, payload=payload_of(Notice, order="PO-1"))
        elif _mode == "wrong_type":
            ctx.uow.enqueue_effect(NotifyWarehouse, payload="raw string")
        elif _mode == "live":
            ctx.uow.enqueue_effect(
                NotifyWarehouse,
                payload=payload_of(Notice, order=order),  # type: ignore[arg-type]
            )
        else:
            ctx.uow.enqueue_effect(NotifyWarehouse, payload=payload_of(Notice, order="PO-1"))


class GateModule(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, EffectGate, Notice, NotifyWarehouse, NotDeclared)


GATE_GRAPH = link(load(ModuleDeclarations(GateModule, GateModule.exports)))


def _rows(path: Path, statement: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    """Read committed state through a connection independent of the engine."""
    connection = sqlite3.connect(path)
    try:
        return connection.execute(statement, params).fetchall()
    finally:
        connection.close()


def _outbox(path: Path) -> list[tuple[object, ...]]:
    return _rows(path, "SELECT id, dedup_id, payload, status FROM outbox ORDER BY id")


def _document(row: tuple[object, ...]) -> dict[str, object]:
    return cast(dict[str, object], json.loads(str(row[2])))


def _invoke(path: Path, request_key: str, params: dict[str, object] | None = None):
    pro = sqlite(path)
    return invoke(
        linked=OLD_GRAPH,
        action=ROOT_KEY,
        bound=bind_action(snapshot(OLD_GRAPH), deployment(), ROOT_KEY),
        provider=pro,
        principal=principal(APPROVE_PERMISSION, RESERVE_PERMISSION),
        grants=grants(),
        parameters=params if params is not None else parameters(pro),
        request_key=request_key,
    )


def _gate_deployment() -> Deployment:
    return Deployment(
        providers=(
            Provider(
                "orders-db",
                "sqlite",
                frozenset({Capability.ATOMIC_TRANSACTION, Capability.OUTBOX}),
                "sqlite:outbox",
            ),
        ),
        enlistments=(
            Enlistment(ORDER, "orders-db", SESSION),
            Enlistment(OUTBOX_RESOURCE, "orders-db", SESSION),
        ),
    )


def _gate_invoke(path: Path, bound: Deployment | None = None):
    pro = sqlite(path)
    return invoke(
        linked=GATE_GRAPH,
        action=_GATE_KEY,
        bound=bind_action(snapshot(GATE_GRAPH), bound or _gate_deployment(), _GATE_KEY),
        provider=pro,
        principal=principal(APPROVE_PERMISSION),
        grants={_ORDER_KEY: grants()[_ORDER_KEY]},
        parameters={"order": parameters(pro)["order"], "reason": "ship it"},
        request_key="tenant-a:alice:gate:PO-1:001",
    )


def test_effect_binding_requires_outbox_capability_and_dedup() -> None:
    bound = bind_action(snapshot(OLD_GRAPH), deployment(), ROOT_KEY)
    assert [item.definition.identity for item in bound.effects] == [_EFFECT]
    assert bound.effects[0].session == bound.session.session  # type: ignore[union-attr]
    assert bound.effects[0].dedup == "sqlite:outbox"

    weak = replace(
        deployment(),
        providers=(
            Provider("orders-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION}), "d"),
        ),
    )
    with pytest.raises(MissingCapability, match="outbox"):
        bind_action(snapshot(OLD_GRAPH), weak, ROOT_KEY)
    no_dedup = replace(
        deployment(),
        providers=(
            Provider(
                "orders-db",
                "sqlite",
                frozenset({Capability.ATOMIC_TRANSACTION, Capability.OUTBOX}),
            ),
        ),
    )
    with pytest.raises(MissingCapability, match="effect_dedup"):
        bind_action(snapshot(OLD_GRAPH), no_dedup, ROOT_KEY)


def test_effect_binding_rejects_a_session_outside_the_business_transaction() -> None:
    split = replace(
        deployment(),
        enlistments=(
            Enlistment(ORDER, "orders-db", SESSION),
            Enlistment(BUDGET, "orders-db", SESSION),
            Enlistment(OUTBOX_RESOURCE, "orders-db", "sqlite:elsewhere"),
        ),
    )
    with pytest.raises(EffectSessionMismatch, match="same transaction"):
        bind_action(snapshot(OLD_GRAPH), split, ROOT_KEY)


def test_below_threshold_invoke_commits_one_outbox_row_with_business_state(
    tmp_path: Path,
) -> None:
    path = database(tmp_path, amount=50_000)
    result = _invoke(path, "tenant-a:alice:approve:PO-1:below")
    assert result.attempt.code == "COMMITTED"
    assert result.execution is not None

    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("APPROVED", 2)
    ]
    assert _rows(path, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [(50_000, 2)]
    ledger = _rows(path, "SELECT status, execution_id FROM request_ledger")
    assert ledger == [("COMMITTED", result.execution.execution_id)]
    outbox = _outbox(path)
    assert len(outbox) == 1
    assert outbox[0][0] == f"{result.execution.execution_id}:{_EFFECT}"
    assert outbox[0][3] == "PENDING"
    document = _document(outbox[0])
    assert document["effect"] == {"identity": _EFFECT, "version": "1.0.0"}
    assert document["action"] == {"identity": ROOT_KEY.identity, "version": ROOT_KEY.version}
    assert document["approver"] is None
    assert document["dedup_id"] == outbox[0][1]
    payload = cast(dict[str, object], document["payload"])
    assert payload["approved_amount"] == 50_000
    order_ref = cast(dict[str, object], payload["order"])
    assert "__ref__" in order_ref
    parts = cast(list[object], order_ref["__ref__"])
    assert parts[1] == "PO-1"


def test_replay_returns_stored_result_without_a_second_outbox_row(tmp_path: Path) -> None:
    path = database(tmp_path, amount=50_000)
    params = parameters(sqlite(path))
    first = _invoke(path, "tenant-a:alice:approve:PO-1:below", params)
    again = _invoke(path, "tenant-a:alice:approve:PO-1:below", params)

    assert again.execution is not None and again.execution.deduplicated is True
    assert first.execution is not None
    assert again.execution.execution_id == first.execution.execution_id
    assert len(_outbox(path)) == 1
    assert _rows(path, "SELECT version FROM purchase_orders WHERE id = 'PO-1'") == [(2,)]


def test_awaiting_preview_and_reject_leave_no_outbox_row(tmp_path: Path) -> None:
    path = database(tmp_path, amount=120_000)
    waiting = _invoke(path, "tenant-a:alice:approve:PO-1:above")
    assert waiting.attempt.code == "AWAITING_APPROVAL"
    assert waiting.execution is not None and waiting.execution.required_approval is not None
    assert _outbox(path) == []
    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(path, "SELECT reserved FROM budgets WHERE id = 'B-1'") == [(0,)]

    rejected = reject(
        provider=provider(path),
        authority_provider=HostAuthority(),
        principal=approver(),
        execution_id=waiting.execution.execution_id,
        callback_key=waiting.execution.required_approval.callback_key,
        expected_intent_fingerprint=waiting.execution.required_approval.intent_fingerprint,
        reason="no budget",
    )
    assert rejected.attempt.code == "REJECTED"
    assert _outbox(path) == []
    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]


def test_resume_commits_one_outbox_row_with_order_budget_and_ledger(tmp_path: Path) -> None:
    target = case(tmp_path)
    assert _outbox(target.path) == []
    result = resume_case(target)
    assert result.attempt.code == "COMMITTED"
    assert result.execution is not None

    assert _rows(target.path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("APPROVED", 2)
    ]
    assert _rows(target.path, "SELECT reserved, version FROM budgets WHERE id = 'B-1'") == [
        (120_000, 2)
    ]
    assert _rows(
        target.path,
        "SELECT status, execution_id FROM request_ledger WHERE execution_id = ?",
        (target.execution_id,),
    ) == [("COMMITTED", target.execution_id)]
    assert _rows(
        target.path,
        "SELECT outcome FROM approval_resume_outcomes WHERE execution_id = ?",
        (target.execution_id,),
    ) == [("COMMITTED",)]
    outbox = _outbox(target.path)
    assert len(outbox) == 1
    assert outbox[0][0] == f"{target.execution_id}:{_EFFECT}"
    assert outbox[0][3] == "PENDING"
    document = _document(outbox[0])
    assert document["approver"] == APPROVER
    assert document["dedup_id"] == outbox[0][1]

    replayed = resume_case(target)
    assert replayed.execution is not None and replayed.execution.deduplicated is True
    assert len(_outbox(target.path)) == 1
    assert _rows(target.path, "SELECT version FROM purchase_orders WHERE id = 'PO-1'") == [(2,)]


def test_dedup_id_is_stable_for_a_declared_key_across_executions(tmp_path: Path) -> None:
    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first_path = database(first_dir, amount=50_000)
    second_path = database(second_dir, amount=50_000)
    first = _invoke(first_path, "tenant-a:alice:approve:PO-1:first")
    second = _invoke(second_path, "tenant-a:alice:approve:PO-1:second")
    assert first.attempt.code == second.attempt.code == "COMMITTED"
    first_row = _outbox(first_path)[0]
    second_row = _outbox(second_path)[0]
    assert first_row[1] == second_row[1]
    assert first_row[0] != second_row[0]


def test_undeclared_effect_fails_closed_before_any_write(tmp_path: Path) -> None:
    global _mode
    _mode = "undeclared"
    try:
        path = database(tmp_path, amount=50_000)
        result = _gate_invoke(path)
        assert result.attempt.code == "DENIED"
        assert "not declared" in str(result.attempt.detail)
    finally:
        _mode = "valid"
    assert _outbox(path) == []
    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(path, "SELECT reserved FROM budgets WHERE id = 'B-1'") == [(0,)]
    assert _rows(path, "SELECT * FROM request_ledger") == []


@pytest.mark.parametrize("mode", ["wrong_type", "live"])
def test_invalid_payload_fails_closed_before_any_write(tmp_path: Path, mode: str) -> None:
    global _mode
    _mode = cast(Literal["valid", "undeclared", "wrong_type", "live"], mode)
    try:
        path = database(tmp_path, amount=50_000)
        result = _gate_invoke(path)
        assert result.attempt.code == "DENIED"
    finally:
        _mode = "valid"
    assert _outbox(path) == []
    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(path, "SELECT * FROM request_ledger") == []


class _RejectingUnit(SQLiteUnitOfWork):
    def record_effect(self, envelope: object) -> bool:  # type: ignore[override]
        raise TransactionUnavailable("the outbox store refused the intent")


class _RejectingProvider(SQLiteProvider):
    def begin(self, plan: SessionPlan) -> SQLiteUnitOfWork:
        unit = cast(SQLiteUnitOfWork, super().begin(plan))
        return _RejectingUnit(
            unit._connection,  # pyright: ignore[reportPrivateUsage]
            unit.transaction,
            unit._resources,  # pyright: ignore[reportPrivateUsage]
            unit._ledger_table,  # pyright: ignore[reportPrivateUsage]
            unit._outbox_table,  # pyright: ignore[reportPrivateUsage]
            unit._effect_dedup,  # pyright: ignore[reportPrivateUsage]
        )


def test_outbox_failure_before_commit_rolls_back_every_write(tmp_path: Path) -> None:
    path = database(tmp_path, amount=50_000)
    source = sqlite(path)
    pro = _RejectingProvider(
        source.database, SESSION, tuple(source.resources.values()), effect_dedup="sqlite:outbox"
    )
    result = invoke(
        linked=GATE_GRAPH,
        action=_GATE_KEY,
        bound=bind_action(snapshot(GATE_GRAPH), _gate_deployment(), _GATE_KEY),
        provider=pro,
        principal=principal(APPROVE_PERMISSION),
        grants={_ORDER_KEY: grants()[_ORDER_KEY]},
        parameters={"order": parameters(provider(path))["order"], "reason": "ship it"},
        request_key="tenant-a:alice:gate:PO-1:rollback",
    )
    assert result.attempt.code == "UNKNOWN"
    assert _outbox(path) == []
    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
    assert _rows(path, "SELECT * FROM request_ledger") == []


def test_valid_typed_enqueue_commits_without_delivering(tmp_path: Path) -> None:
    path = database(tmp_path, amount=50_000)
    result = _gate_invoke(path)
    assert result.attempt.code == "COMMITTED"
    outbox = _outbox(path)
    assert len(outbox) == 1
    document = _document(outbox[0])
    assert document["payload"] == {"order": "PO-1"}
    assert document["approver"] is None
    assert outbox[0][3] == "PENDING"


def test_approve_decision_does_not_enqueue(tmp_path: Path) -> None:
    path = database(tmp_path, amount=120_000)
    waiting = _invoke(path, "tenant-a:alice:approve:PO-1:decision")
    assert waiting.attempt.code == "AWAITING_APPROVAL"
    assert waiting.execution is not None and waiting.execution.required_approval is not None
    approved = approve(
        provider=provider(path),
        authority_provider=HostAuthority(),
        principal=approver(),
        execution_id=waiting.execution.execution_id,
        callback_key=waiting.execution.required_approval.callback_key,
        expected_intent_fingerprint=waiting.execution.required_approval.intent_fingerprint,
        reason="confirmed",
    )
    assert approved.decision is not None
    assert _outbox(path) == []
    assert _rows(path, "SELECT status, version FROM purchase_orders WHERE id = 'PO-1'") == [
        ("PENDING", 1)
    ]
