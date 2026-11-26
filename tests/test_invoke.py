"""Invoke gate: live authorization, scoped typed refs, narrow ctx and one UoW."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import pytest

from codology import (
    BoundAction,
    Capability,
    Comparison,
    DefinitionKey,
    Deployment,
    Enlistment,
    LinkedDeclarations,
    ModuleDeclarations,
    OrderBy,
    Principal,
    Provider,
    ReadGrant,
    VersionedRef,
    bind_action,
    link,
    load,
    query,
    snapshot,
)
from codology.adapter import ResourceBinding, SQLiteProvider
from codology.declarations import Action, Module, ObjectRef, ObjectType
from codology.engine import ActionResult, HandlerCtx, InvokeDenied, ResolvedObject, invoke
from codology.query import ReadDenied

_ORDER = "procurement.purchase_order"
_BUDGET = "finance.budget"
_ORDER_KEY = DefinitionKey(_ORDER, "1.0.0")
_BUDGET_KEY = DefinitionKey(_BUDGET, "1.0.0")
_APPROVE_KEY = DefinitionKey("procurement.approve_order", "1.1.0")
_DUAL_KEY = DefinitionKey("procurement.approve_and_reserve", "1.1.0")
_CALL_KEY = DefinitionKey("procurement.call_reserve", "1.1.0")
_RESERVE_KEY = DefinitionKey("finance.reserve_budget", "1.0.0")
_SESSION = "sqlite:main"
_TENANT = "A"
_SCOPE = "team1"
_APPROVE = "purchase_order.approve"
_RESERVE = "budget.reserve"
_READ = "purchase_order.read"

_hook: Callable[[HandlerCtx, ResolvedObject[object], str], None] | None = None


class PurchaseOrder(ObjectType):
    identity = _ORDER
    version = "1.0.0"
    keyType = "PO"

    status: str
    approved_amount: int


class Budget(ObjectType):
    identity = _BUDGET
    version = "1.0.0"
    keyType = "B"

    balance: int


class ApproveOrder(Action):
    identity = _APPROVE_KEY.identity
    version = _APPROVE_KEY.version

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = (PurchaseOrder,)
    writes = (PurchaseOrder,)
    permission = _APPROVE

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, reason: str) -> None:
        if _hook is not None:
            _hook(ctx, cast(ResolvedObject[object], order), reason)
            return
        ctx.require(order.status == "PENDING_APPROVAL", reason="order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")
        ctx.uow.register_mutation(
            order,
            status="APPROVED",
            approved_amount=40_000,
            expectedVersion=order.version,
        )


class ApproveAndReserve(Action):
    identity = _DUAL_KEY.identity
    version = _DUAL_KEY.version

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder, Budget)
    permission = _APPROVE

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget) -> None:
        ctx.uow.register_mutation(
            order, status="APPROVED", approved_amount=40_000, expectedVersion=order.version
        )
        ctx.uow.register_mutation(
            budget, balance=60_000, expectedVersion=cast(ResolvedObject[object], budget).version
        )


class ReserveBudget(Action):
    identity = _RESERVE_KEY.identity
    version = _RESERVE_KEY.version

    budget: ObjectRef[Budget]

    reads = (Budget,)
    writes = (Budget,)
    permission = _RESERVE

    def handler(self, ctx: HandlerCtx, budget: Budget) -> None:
        ctx.uow.register_mutation(
            budget, balance=60_000, expectedVersion=cast(ResolvedObject[object], budget).version
        )


class CallReserve(Action):
    identity = _CALL_KEY.identity
    version = _CALL_KEY.version

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (_RESERVE_KEY.identity,)
    permission = _APPROVE

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget) -> None:
        ctx.call(_RESERVE_KEY.identity, budget=budget)
        ctx.uow.register_mutation(
            order, status="APPROVED", approved_amount=40_000, expectedVersion=order.version
        )


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApproveOrder, ApproveAndReserve, CallReserve)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


_SCHEMA = """
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
    balance INTEGER NOT NULL,
    version INTEGER NOT NULL
);
"""


def pytest_runtest_setup() -> None:
    global _hook
    _hook = None


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "invoke.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO purchase_orders "
            "(id, tenant, scope, status, approved_amount, created_at, version) "
            "VALUES ('PO-1', 'A', 'team1', 'PENDING_APPROVAL', NULL, 1, 1)"
        )
        connection.execute(
            "INSERT INTO budgets (id, tenant, scope, balance, version) "
            "VALUES ('B-1', 'A', 'team1', 100000, 1)"
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
                ("status", "approved_amount"),
                tenant_column="tenant",
                scope_column="scope",
            ),
            ResourceBinding(
                _BUDGET,
                "1.0.0",
                "budgets",
                ("balance",),
                tenant_column="tenant",
                scope_column="scope",
            ),
        ),
    )


def _linked() -> LinkedDeclarations:
    return link(
        load(
            ModuleDeclarations(
                Procurement, (PurchaseOrder, ApproveOrder, ApproveAndReserve, CallReserve)
            ),
            ModuleDeclarations(Finance, (Budget, ReserveBudget)),
        )
    )


def _bound(action: DefinitionKey, *, delegated: bool = False) -> BoundAction:
    from codology import DelegationGrant, DelegationPrincipal

    grants = (
        (
            DelegationGrant(
                _CALL_KEY.identity,
                _RESERVE_KEY.identity,
                _RESERVE,
                DelegationPrincipal.REQUESTER,
            ),
        )
        if delegated
        else ()
    )
    deployment = Deployment(
        providers=(Provider("orders-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),),
        enlistments=(
            Enlistment(_ORDER, "orders-db", _SESSION),
            Enlistment(_BUDGET, "orders-db", _SESSION),
        ),
        delegations=grants,
    )
    return bind_action(snapshot(_linked()), deployment, action)


def _principal(*permissions: str) -> Principal:
    return Principal("alice", _TENANT, frozenset({_READ, *permissions}))


def _grant(definition: DefinitionKey, scopes: tuple[str, ...] = (_SCOPE,)) -> ReadGrant:
    return ReadGrant("alice", definition, _TENANT, scopes, _READ)


def _ref(
    provider: SQLiteProvider,
    principal: Principal,
    grant: ReadGrant,
    definition: DefinitionKey,
) -> VersionedRef[object]:
    predicate = Comparison("status", "==", "PENDING_APPROVAL") if definition == _ORDER_KEY else None
    page = query(
        provider=provider,
        principal=principal,
        grant=grant,
        from_=definition,
        target=PurchaseOrder if definition == _ORDER_KEY else Budget,
        order=OrderBy("created_at") if definition == _ORDER_KEY else OrderBy("id"),
        predicate=predicate,
        limit=1,
    )
    assert len(page.rows) == 1
    return page.rows[0].as_ref()


def _call(
    path: Path,
    action: DefinitionKey,
    parameters: Mapping[str, object],
    *,
    principal: Principal | None = None,
    scopes: tuple[str, ...] = (_SCOPE,),
    delegated: bool = False,
) -> ActionResult:
    grants = {
        _ORDER_KEY: _grant(_ORDER_KEY, scopes),
        _BUDGET_KEY: _grant(_BUDGET_KEY, scopes),
    }
    return invoke(
        linked=_linked(),
        action=action,
        bound=_bound(action, delegated=delegated),
        provider=_provider(path),
        principal=principal if principal is not None else _principal(_APPROVE, _RESERVE),
        grants=grants,
        parameters=parameters,
    )


def _orders(path: Path) -> tuple[str, int | None, int]:
    connection = sqlite3.connect(path)
    try:
        found = connection.execute(
            "SELECT status, approved_amount, version FROM purchase_orders WHERE id = 'PO-1'"
        ).fetchone()
        assert found is not None
        return str(found[0]), None if found[1] is None else int(found[1]), int(found[2])
    finally:
        connection.close()


def _budget(path: Path) -> tuple[int, int]:
    connection = sqlite3.connect(path)
    try:
        found = connection.execute(
            "SELECT balance, version FROM budgets WHERE id = 'B-1'"
        ).fetchone()
        assert found is not None
        return int(found[0]), int(found[1])
    finally:
        connection.close()


def test_authorized_invoke_commits_resolved_ref_once(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    principal = _principal(_APPROVE, _RESERVE)
    ref = _ref(provider, principal, _grant(_ORDER_KEY), _ORDER_KEY)

    result = _call(path, _APPROVE_KEY, {"order": ref, "reason": "approved after budget check"})

    assert result.attempt.code == "COMMITTED" and result.attempt.detail is None
    assert result.execution is not None
    assert result.execution.status == "COMMITTED"
    assert result.execution.requester == principal
    assert result.execution.committed[0].key == "PO-1"
    assert all(write.rowcount == 1 for write in result.writes)
    assert len({write.transaction for write in result.writes}) == 1
    assert _orders(path) == ("APPROVED", 40_000, 2)


def test_read_only_principal_is_denied_without_execution(tmp_path: Path) -> None:
    path = _database(tmp_path)
    ref = _ref(_provider(path), _principal(_APPROVE), _grant(_ORDER_KEY), _ORDER_KEY)
    before = _orders(path)

    result = _call(
        path,
        _APPROVE_KEY,
        {"order": ref, "reason": "ok"},
        principal=_principal(),
    )

    assert result.attempt.code == "DENIED"
    assert result.execution is None and result.writes == ()
    assert _orders(path) == before


def test_permission_lost_after_query_is_denied(tmp_path: Path) -> None:
    path = _database(tmp_path)
    ref = _ref(_provider(path), _principal(_APPROVE), _grant(_ORDER_KEY), _ORDER_KEY)
    before = _orders(path)

    result = _call(
        path,
        _APPROVE_KEY,
        {"order": ref, "reason": "ok"},
        principal=Principal("alice", _TENANT, frozenset({_APPROVE})),
    )

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == before


def test_ref_outside_current_scope_is_denied(tmp_path: Path) -> None:
    path = _database(tmp_path)
    ref = _ref(_provider(path), _principal(_APPROVE), _grant(_ORDER_KEY), _ORDER_KEY)
    before = _orders(path)

    result = _call(
        path,
        _APPROVE_KEY,
        {"order": ref, "reason": "ok"},
        scopes=("team2",),
    )

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == before


def test_ref_of_wrong_declared_type_is_denied(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    principal = _principal(_APPROVE)
    budget_ref = _ref(provider, principal, _grant(_BUDGET_KEY), _BUDGET_KEY)
    before = _orders(path)

    result = _call(path, _APPROVE_KEY, {"order": budget_ref, "reason": "ok"})

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == before


def test_stale_ref_is_rejected_without_write(tmp_path: Path) -> None:
    path = _database(tmp_path)
    ref = _ref(_provider(path), _principal(_APPROVE), _grant(_ORDER_KEY), _ORDER_KEY)
    connection = sqlite3.connect(path)
    try:
        connection.execute("UPDATE purchase_orders SET version = version + 1 WHERE id = 'PO-1'")
        connection.commit()
    finally:
        connection.close()
    bumped = _orders(path)

    result = _call(path, _APPROVE_KEY, {"order": ref, "reason": "ok"})

    assert result.attempt.code == "StalePlan"
    assert result.execution is None and result.writes == ()
    assert _orders(path) == bumped


def test_business_requirement_returns_rejected_without_write(tmp_path: Path) -> None:
    path = _database(tmp_path)
    ref = _ref(_provider(path), _principal(_APPROVE), _grant(_ORDER_KEY), _ORDER_KEY)
    before = _orders(path)

    result = _call(path, _APPROVE_KEY, {"order": ref, "reason": "  "})

    assert result.attempt.code == "REJECTED"
    assert result.attempt.detail == "reason_required"
    assert result.execution is not None and result.execution.status == "REJECTED"
    assert result.writes == ()
    assert _orders(path) == before


def test_world_change_between_resolve_and_commit_is_stale(tmp_path: Path) -> None:
    path = _database(tmp_path)
    ref = _ref(_provider(path), _principal(_APPROVE), _grant(_ORDER_KEY), _ORDER_KEY)

    def interfere(ctx: HandlerCtx, order: ResolvedObject[object], reason: str) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "UPDATE purchase_orders SET status = 'CANCELLED', version = version + 1 "
                "WHERE id = 'PO-1'"
            )
            connection.commit()
        finally:
            connection.close()
        ctx.uow.register_mutation(
            order, status="APPROVED", approved_amount=40_000, expectedVersion=order.version
        )

    global _hook
    _hook = interfere
    result = _call(path, _APPROVE_KEY, {"order": ref, "reason": "ok"})

    assert result.attempt.code == "StalePlan"
    assert result.execution is None and result.writes == ()
    assert _orders(path) == ("CANCELLED", None, 2)


def test_write_on_undeclared_resource_is_denied(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    principal = _principal(_APPROVE)
    order_ref = _ref(provider, principal, _grant(_ORDER_KEY), _ORDER_KEY)
    budget_ref = _ref(provider, principal, _grant(_BUDGET_KEY), _BUDGET_KEY)
    before = _orders(path)

    def stray_write(ctx: HandlerCtx, order: ResolvedObject[object], reason: str) -> None:
        budget = ctx.resolve(budget_ref)
        ctx.uow.register_mutation(budget, balance=0, expectedVersion=budget.version)

    global _hook
    _hook = stray_write
    result = _call(path, _APPROVE_KEY, {"order": order_ref, "reason": "ok"})

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == before and _budget(path) == (100_000, 1)


def test_context_exposes_no_raw_capability_or_undeclared_call(tmp_path: Path) -> None:
    path = _database(tmp_path)
    ref = _ref(_provider(path), _principal(_APPROVE), _grant(_ORDER_KEY), _ORDER_KEY)
    budget_ref = _ref(_provider(path), _principal(_APPROVE), _grant(_BUDGET_KEY), _BUDGET_KEY)

    def inspect(ctx: HandlerCtx, order: ResolvedObject[object], reason: str) -> None:
        for forbidden in ("connection", "cursor", "commit", "rollback", "credentials", "sql"):
            assert not hasattr(ctx, forbidden)
            assert not hasattr(ctx.uow, forbidden)
        with pytest.raises(InvokeDenied):
            ctx.call("finance.reserve_budget")
        with pytest.raises(InvokeDenied):
            ctx.resolve(budget_ref)
        assert ctx.principal.identity == "alice"
        assert ctx.writes == (_ORDER,)
        ctx.uow.register_mutation(
            order, status="APPROVED", approved_amount=40_000, expectedVersion=order.version
        )

    global _hook
    _hook = inspect
    result = _call(path, _APPROVE_KEY, {"order": ref, "reason": "ok"})

    assert result.attempt.code == "COMMITTED"
    assert _orders(path) == ("APPROVED", 40_000, 2)


def test_two_registered_writes_share_one_physical_transaction(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    principal = _principal(_APPROVE)
    order_ref = _ref(provider, principal, _grant(_ORDER_KEY), _ORDER_KEY)
    budget_ref = _ref(provider, principal, _grant(_BUDGET_KEY), _BUDGET_KEY)

    result = _call(
        path,
        _DUAL_KEY,
        {"order": order_ref, "budget": budget_ref},
    )

    assert result.attempt.code == "COMMITTED"
    assert len(result.writes) == 2
    assert len({write.transaction for write in result.writes}) == 1
    assert _orders(path) == ("APPROVED", 40_000, 2)
    assert _budget(path) == (60_000, 2)


def test_declared_child_call_needs_live_requester_permission(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    principal = _principal(_APPROVE, _RESERVE)
    order_ref = _ref(provider, principal, _grant(_ORDER_KEY), _ORDER_KEY)
    budget_ref = _ref(provider, principal, _grant(_BUDGET_KEY), _BUDGET_KEY)
    before = _orders(path)

    denied = _call(
        path,
        _CALL_KEY,
        {"order": order_ref, "budget": budget_ref},
        principal=Principal("alice", _TENANT, frozenset({_READ, _APPROVE})),
        delegated=True,
    )
    assert denied.attempt.code == "DENIED"
    assert denied.execution is None
    assert _orders(path) == before and _budget(path) == (100_000, 1)

    allowed = _call(
        path,
        _CALL_KEY,
        {"order": order_ref, "budget": budget_ref},
        delegated=True,
    )
    assert allowed.attempt.code == "COMMITTED"
    assert allowed.execution is not None
    assert allowed.execution.children == (_RESERVE_KEY,)
    assert _budget(path) == (60_000, 2)
    assert _orders(path) == ("APPROVED", 40_000, 2)


def test_read_denial_does_not_leak_row_detail(tmp_path: Path) -> None:
    path = _database(tmp_path)
    ref = _ref(_provider(path), _principal(_APPROVE), _grant(_ORDER_KEY), _ORDER_KEY)

    result = _call(
        path,
        _APPROVE_KEY,
        {"order": ref, "reason": "ok"},
        principal=Principal("stranger", _TENANT, frozenset({_READ, _APPROVE})),
    )

    assert result.attempt.code == "DENIED"
    assert "PO-1" not in str(result.attempt.detail)
    with pytest.raises(ReadDenied):
        _ref(
            _provider(path),
            Principal("stranger", _TENANT, frozenset({_READ})),
            _grant(_ORDER_KEY),
            _ORDER_KEY,
        )
