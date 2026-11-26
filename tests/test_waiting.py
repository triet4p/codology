"""Invoke gate waiting state: structural predicate, durable pending, no held write."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codology import (
    EXECUTION_READ_PERMISSION,
    Capability,
    DefinitionKey,
    DelegationGrant,
    DelegationPrincipal,
    Deployment,
    EffectSessionMismatch,
    Enlistment,
    MissingCapability,
    ModuleDeclarations,
    OrderBy,
    Principal,
    Provider,
    ReadGrant,
    VersionedRef,
    bind_action,
    decode_manifest,
    link,
    load,
    query,
    snapshot,
)
from codology.adapter import ResourceBinding, SQLiteProvider
from codology.declarations import (
    Action,
    Effect,
    Module,
    ObjectRef,
    ObjectType,
    Param,
    Value,
    all_of,
)
from codology.declarations.behavior import Approval
from codology.engine import ActionResult, HandlerCtx, ScopedEngineProvider, invoke, reconcile
from codology.linking import LinkedDeclarations

_ORDER = "procurement.purchase_order"
_BUDGET = "finance.budget"
_ROOT = "procurement.approve_order"
_RESERVE = "finance.reserve_budget"
_ORDER_KEY = DefinitionKey(_ORDER, "1.0.0")
_BUDGET_KEY = DefinitionKey(_BUDGET, "1.0.0")
_ROOT_KEY = DefinitionKey(_ROOT, "2.0.0")
_RESERVE_KEY = DefinitionKey(_RESERVE, "1.0.0")
_SESSION = "sqlite:waiting"
_TENANT = "A"
_SCOPE = "team1"
_APPROVE = "purchase_order.approve"
_RESERVE_PERMISSION = "budget.reserve"
_READ = "purchase_order.read"
_REQUEST_KEY = "tenant-a:alice:approve:PO-1:001"

_SCHEMA = """
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
CREATE TABLE outbox (id TEXT PRIMARY KEY, dedup_id TEXT NOT NULL, payload TEXT NOT NULL);
"""


class PurchaseOrder(ObjectType):
    identity = _ORDER
    version = "1.0.0"
    keyType = "PO"

    status: str
    amount: int


class Budget(ObjectType):
    identity = _BUDGET
    version = "1.0.0"
    keyType = "B"

    ceiling: int
    reserved: int


class ReserveBudget(Action):
    identity = _RESERVE
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: int
    expectedVersion: int

    reads = (Budget,)
    writes = (Budget,)
    permission = _RESERVE_PERMISSION

    def handler(self, ctx: HandlerCtx, budget: Budget, amount: int, expectedVersion: int) -> None:
        ctx.require(budget.reserved + amount <= budget.ceiling, reason="budget_insufficient")
        ctx.uow.register_mutation(
            budget,
            reserved=budget.reserved + amount,
            expectedVersion=expectedVersion,
        )


class ApproveOrder(Action):
    identity = _ROOT
    version = "2.0.0"

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]
    reason: str

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (_RESERVE,)
    permission = _APPROVE
    approval = Approval.conditional(
        when=all_of(Param("order").amount >= 100_000, Param("reason") != ""),
        role="finance_director",
        self_approval=False,
    )

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget, reason: str) -> None:
        ctx.require(order.status == "PENDING", reason="order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")
        ctx.call(
            _RESERVE,
            budget=budget,
            amount=order.amount,
            expectedVersion=budget.version,
        )
        ctx.uow.register_mutation(
            order,
            status="APPROVED",
            expectedVersion=order.version,
        )


class ApproveOrderLater(Action):
    """A newer default revision whose handler must never run on replay."""

    identity = _ROOT
    version = "2.1.0"

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]
    reason: str

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (_RESERVE,)
    permission = _APPROVE
    approval = Approval.conditional(
        when=all_of(Param("order").amount >= 100_000, Param("reason") != ""),
        role="finance_director",
        self_approval=False,
    )

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget, reason: str) -> None:
        raise AssertionError("a replay must not run a newer handler")


class ProcurementBoth(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApproveOrder, ApproveOrderLater)


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApproveOrder)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


def _database(tmp_path: Path, *, amount: int = 40_000, status: str = "PENDING") -> Path:
    path = tmp_path / "waiting.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO purchase_orders "
            "(id, tenant, scope, status, amount, created_at, version) "
            "VALUES ('PO-1', ?, ?, ?, ?, 1, 1)",
            (_TENANT, _SCOPE, status, amount),
        )
        connection.execute(
            "INSERT INTO budgets (id, tenant, scope, ceiling, reserved, version) "
            "VALUES ('B-1', ?, ?, 1_000_000, 0, 1)",
            (_TENANT, _SCOPE),
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _provider(path: Path) -> SQLiteProvider:
    return SQLiteProvider(
        path,
        _SESSION,
        (
            ResourceBinding(
                _ORDER,
                "1.0.0",
                "purchase_orders",
                ("status", "amount"),
                tenant_column="tenant",
                scope_column="scope",
            ),
            ResourceBinding(
                _BUDGET,
                "1.0.0",
                "budgets",
                ("ceiling", "reserved"),
                tenant_column="tenant",
                scope_column="scope",
            ),
        ),
    )


def _linked() -> LinkedDeclarations:
    return link(
        load(
            ModuleDeclarations(Procurement, (PurchaseOrder, ApproveOrder)),
            ModuleDeclarations(Finance, (Budget, ReserveBudget)),
        )
    )


def _deployment() -> Deployment:
    return Deployment(
        providers=(Provider("orders-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),),
        enlistments=(
            Enlistment(_ORDER, "orders-db", _SESSION),
            Enlistment(_BUDGET, "orders-db", _SESSION),
        ),
        delegations=(
            DelegationGrant(_ROOT, _RESERVE, _RESERVE_PERMISSION, DelegationPrincipal.REQUESTER),
        ),
    )


def _principal(*permissions: str) -> Principal:
    return Principal("alice", _TENANT, frozenset({_READ, *permissions}))


def _grant(definition: DefinitionKey, scopes: tuple[str, ...] = (_SCOPE,)) -> ReadGrant:
    return ReadGrant("alice", definition, _TENANT, scopes, _READ)


def _parameters(path: Path) -> dict[str, object]:
    provider = _provider(path)
    principal = _principal(_APPROVE, _RESERVE_PERMISSION)

    def ref(definition: DefinitionKey, target: type[object]) -> VersionedRef[object]:
        page = query(
            provider=provider,
            principal=principal,
            grant=_grant(definition),
            from_=definition,
            target=target,
            order=OrderBy("created_at") if definition == _ORDER_KEY else OrderBy("id"),
            predicate=None,
            limit=10,
        )
        assert len(page.rows) == 1
        return page.rows[0].as_ref()

    return {
        "order": ref(_ORDER_KEY, PurchaseOrder),
        "budget": ref(_BUDGET_KEY, Budget),
        "reason": "approved after budget check",
    }


def _invoke(
    path: Path,
    parameters: dict[str, object],
    *,
    principal: Principal | None = None,
    linked: LinkedDeclarations | None = None,
    request_key: str | None = _REQUEST_KEY,
    intent_fingerprint: str | None = None,
    approval_expires_at: str | None = None,
    provider: ScopedEngineProvider | None = None,
    action: DefinitionKey = _ROOT_KEY,
) -> ActionResult:
    graph = linked if linked is not None else _linked()
    return invoke(
        linked=graph,
        action=action,
        bound=bind_action(snapshot(graph), _deployment(), action),
        provider=provider if provider is not None else _provider(path),
        principal=principal if principal is not None else _principal(_APPROVE, _RESERVE_PERMISSION),
        grants={_ORDER_KEY: _grant(_ORDER_KEY), _BUDGET_KEY: _grant(_BUDGET_KEY)},
        parameters=parameters,
        request_key=request_key,
        intent_fingerprint=intent_fingerprint,
        approval_expires_at=approval_expires_at,
    )


def _rows(path: Path, table: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        connection.close()


def _ledger(path: Path) -> list[tuple[object, ...]]:
    return _rows(path, "request_ledger")


def test_below_threshold_commits_through_the_atomic_path(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=99_999)
    result = _invoke(path, _parameters(path))

    assert result.attempt.code == "COMMITTED"
    assert result.execution is not None
    assert result.execution.status == "COMMITTED"
    assert result.execution.required_approval is None
    assert len(result.writes) == 2
    assert _rows(path, "purchase_orders")[0][3] == "APPROVED"
    assert _rows(path, "budgets")[0][4] == 99_999
    assert _ledger(path)[0][7] == "COMMITTED"


def test_at_threshold_waits_without_business_writes_or_held_transaction(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=100_000)
    result = _invoke(path, _parameters(path))

    assert result.attempt.code == "AWAITING_APPROVAL"
    execution = result.execution
    assert execution is not None and execution.status == "AWAITING_APPROVAL"
    assert result.writes == ()
    assert execution.requester.identity == "alice"
    assert execution.pinned_manifest is not None
    assert decode_manifest(execution.pinned_manifest).root.version == "2.0.0"
    assert execution.material_intent is not None
    assert execution.material_intent.child_keys == (_RESERVE_KEY,)
    assert execution.required_approval is not None
    assert execution.required_approval.role == "finance_director"
    assert execution.required_approval.self_approval is False
    assert execution.required_approval.tenant == _TENANT
    assert execution.required_approval.scope == (_SCOPE,)
    assert execution.required_approval.requester.identity == "alice"
    assert execution.required_approval.expires_at.endswith("Z")
    deadline = datetime.fromisoformat(execution.required_approval.expires_at.replace("Z", "+00:00"))
    remaining = deadline - datetime.now(UTC)
    assert timedelta(hours=23) < remaining < timedelta(hours=25)
    assert execution.required_approval.callback_key.startswith(execution.execution_id + ":")
    assert _rows(path, "purchase_orders")[0][3] == "PENDING"
    assert _rows(path, "purchase_orders")[0][6] == 1
    assert _rows(path, "budgets")[0][4] == 0
    assert _rows(path, "outbox") == []
    rows = _ledger(path)
    assert len(rows) == 1 and rows[0][7] == "AWAITING_APPROVAL"


def test_above_threshold_also_waits(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=150_000)
    result = _invoke(path, _parameters(path))
    assert result.attempt.code == "AWAITING_APPROVAL"


def test_failed_precondition_creates_no_approval_request(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=200_000, status="CANCELLED")
    result = _invoke(path, _parameters(path))

    assert result.attempt.code == "REJECTED"
    assert _ledger(path) == []
    assert _rows(path, "purchase_orders")[0][3] == "CANCELLED"


def test_pending_survives_engine_reopen_and_replay(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    first = _invoke(path, _parameters(path))
    assert first.attempt.code == "AWAITING_APPROVAL"
    assert first.execution is not None

    second = _invoke(path, _parameters(path))
    assert second.attempt.code == "AWAITING_APPROVAL"
    assert second.execution is not None
    assert second.execution.execution_id == first.execution.execution_id
    assert second.execution.deduplicated is True

    reader = _principal(_APPROVE, _RESERVE_PERMISSION, EXECUTION_READ_PERMISSION)
    reconciled = reconcile(
        provider=_provider(path),
        principal=reader,
        action=_ROOT_KEY,
        request_key=_REQUEST_KEY,
    )
    assert reconciled.execution is not None
    assert reconciled.execution.execution_id == first.execution.execution_id
    assert reconciled.execution.material_intent is not None


def test_another_connection_can_write_while_execution_waits(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    assert _invoke(path, _parameters(path)).attempt.code == "AWAITING_APPROVAL"

    connection = sqlite3.connect(path, timeout=1)
    try:
        connection.execute("UPDATE purchase_orders SET status = 'CANCELLED' WHERE id = 'PO-1'")
        connection.commit()
    finally:
        connection.close()
    assert _rows(path, "purchase_orders")[0][3] == "CANCELLED"


def test_replay_ignores_a_changed_default_revision(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    first = _invoke(path, _parameters(path))
    assert first.execution is not None
    graph = link(
        load(
            ModuleDeclarations(ProcurementBoth, (PurchaseOrder, ApproveOrderLater)),
            ModuleDeclarations(Finance, (Budget, ReserveBudget)),
        )
    )
    replay = _invoke(
        path,
        _parameters(path),
        linked=graph,
        action=DefinitionKey(_ROOT, "2.1.0"),
    )
    assert replay.execution is not None
    assert replay.execution.execution_id == first.execution.execution_id
    assert replay.attempt.code == "AWAITING_APPROVAL"


def test_same_key_with_different_intent_is_key_misuse(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    parameters = _parameters(path)
    first = _invoke(path, parameters)
    assert first.attempt.code == "AWAITING_APPROVAL"

    changed = dict(parameters)
    changed["reason"] = "a different reason"
    second = _invoke(path, changed)
    assert second.attempt.code == "DENIED"
    assert second.attempt.reason == "KEY_MISUSE"
    assert len(_ledger(path)) == 1


def test_lookup_and_replay_do_not_cross_tenant_boundaries(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    first = _invoke(path, _parameters(path))
    assert first.execution is not None

    other = Principal(
        "alice",
        "B",
        frozenset({_READ, _APPROVE, _RESERVE_PERMISSION, EXECUTION_READ_PERMISSION}),
    )
    remote = reconcile(
        provider=_provider(path),
        principal=other,
        action=_ROOT_KEY,
        request_key=_REQUEST_KEY,
    )
    assert remote.attempt.code == "UNKNOWN"
    assert remote.execution is None

    reader = _principal(EXECUTION_READ_PERMISSION)
    own = reconcile(
        provider=_provider(path),
        principal=reader,
        action=_ROOT_KEY,
        request_key=_REQUEST_KEY,
    )
    assert own.attempt.code == "AWAITING_APPROVAL"
    assert own.execution is not None
    assert own.execution.execution_id == first.execution.execution_id


def test_reconcile_requires_record_read_authority(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    _invoke(path, _parameters(path))
    result = reconcile(
        provider=_provider(path),
        principal=_principal(_APPROVE),
        action=_ROOT_KEY,
        request_key=_REQUEST_KEY,
    )
    assert result.attempt.code == "DENIED"
    assert result.execution is None


def test_two_invokes_with_same_key_create_one_execution(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    parameters = _parameters(path)
    first = _invoke(path, parameters)
    second = _invoke(path, parameters)
    assert first.execution is not None and second.execution is not None
    assert first.execution.execution_id == second.execution.execution_id
    assert len(_ledger(path)) == 1


def test_material_intent_captures_compared_value_and_object_versions(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=130_000)
    result = _invoke(path, _parameters(path))
    assert result.execution is not None and result.execution.material_intent is not None
    intent = result.execution.material_intent
    assert intent.object_versions
    assert any(
        item.parameter == "order" and item.path == ("amount",) for item in intent.comparisons
    )
    assert intent.fingerprint
    assert intent.canonical_input["reason"] == "approved after budget check"


def test_host_can_pin_an_explicit_approval_deadline(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    result = _invoke(
        path,
        _parameters(path),
        approval_expires_at="2030-01-01T00:00:00Z",
    )
    assert result.execution is not None and result.execution.required_approval is not None
    assert result.execution.required_approval.expires_at == "2030-01-01T00:00:00Z"


def test_pending_payload_rejects_tampering(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    _invoke(path, _parameters(path))
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE request_ledger SET payload = '{\"tampered\": true}' WHERE request_key = ?",
            (_REQUEST_KEY,),
        )
        connection.commit()
    finally:
        connection.close()
    result = _invoke(path, _parameters(path))
    assert result.attempt.code == "DENIED"


class Notice(Value):
    identity = "procurement.notice"
    version = "1.0.0"

    order: str


class NotifyEffect(Effect):
    identity = "procurement.notify"
    version = "1.0.0"
    payload = Notice
    dedupKey = ("order",)


class GuardedEffectAction(Action):
    """An effect declaration whose handler must never run without a bound outbox."""

    identity = "procurement.guarded_effect"

    version = "1.0.0"

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = (PurchaseOrder,)
    writes = (PurchaseOrder,)
    permission = _APPROVE
    approval = Approval.conditional(
        when=Param("order").amount >= 100_000,
        role="finance_director",
        self_approval=False,
    )
    effects = (NotifyEffect,)

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("an unbound effect declaration must not run a handler")


class ProcurementWithEffect(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, GuardedEffectAction, Notice, NotifyEffect)


def test_effect_binding_is_rejected_before_handler_when_outbox_is_missing(tmp_path: Path) -> None:
    path = _database(tmp_path, amount=120_000)
    graph = link(
        load(
            ModuleDeclarations(
                ProcurementWithEffect,
                (PurchaseOrder, GuardedEffectAction, Notice, NotifyEffect),
            ),
            ModuleDeclarations(Finance, (Budget, ReserveBudget)),
        )
    )
    action = DefinitionKey("procurement.guarded_effect", "1.0.0")
    snapshot_graph = snapshot(graph)
    with pytest.raises(EffectSessionMismatch, match="codology.outbox"):
        bind_action(snapshot_graph, _deployment(), action)
    enlisted = replace(
        _deployment(),
        enlistments=(
            *_deployment().enlistments,
            Enlistment("codology.outbox", "orders-db", _SESSION),
        ),
    )

    with pytest.raises(MissingCapability, match="outbox"):
        bind_action(snapshot_graph, enlisted, action)
    assert _rows(path, "outbox") == []
    assert _rows(path, "purchase_orders")[0][3] == "PENDING"
