"""Declared child actions: linked revision, narrowed delegation, one UoW."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

import pytest

from codology import (
    Capability,
    Comparison,
    DefinitionKey,
    DelegationGrant,
    DelegationPrincipal,
    Deployment,
    Enlistment,
    ModuleDeclarations,
    NoSharedTransaction,
    NotExported,
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
from codology.declarations import Action, CommitRequirement, Module, ObjectRef
from codology.engine import ActionResult, HandlerCtx, invoke
from codology.linking import LinkedDeclarations
from codology.money import MinorMoney
from examples.procurement_finance import finance as static_finance
from examples.procurement_finance import procurement as static_procurement
from examples.procurement_finance import runtime

_ORDER = "procurement.purchase_order"
_BUDGET = "finance.budget"
_RESERVE = "finance.reserve_budget"
_ROOT = "procurement.approve_purchase_order"
_ORDER_KEY = DefinitionKey(_ORDER, "1.0.0")
_BUDGET_KEY = DefinitionKey(_BUDGET, "1.0.0")
_RESERVE_KEY = DefinitionKey(_RESERVE, "1.0.0")
_ROOT_KEY = DefinitionKey(_ROOT, "1.1.0")
_SESSION = "sqlite:main"
_OTHER_SESSION = "sqlite:other"
_TENANT = "A"
_SCOPE = "team1"
_APPROVE = "purchase_order.approve"
_RESERVE_PERMISSION = "budget.reserve"
_READ = "purchase_order.read"
_AMOUNT = MinorMoney.from_decimal(Decimal("40000"), "USD")


class ReserveBudgetNext(Action):
    """A decoy child at a different revision, used to prove revision pinning."""

    identity = _RESERVE
    version = "1.1.0"

    budget: ObjectRef[runtime.Budget]
    amount: MinorMoney
    expectedVersion: int

    reads = (runtime.Budget,)
    writes = (runtime.Budget,)
    permission = _RESERVE_PERMISSION

    def handler(
        self,
        ctx: HandlerCtx,
        budget: runtime.Budget,
        amount: MinorMoney,
        expectedVersion: int,
    ) -> None:
        ctx.uow.register_mutation(budget, reserved=999_999, expectedVersion=expectedVersion)


class RawBudgetCall(Action):
    """A root that hands the child a raw id instead of a query-issued ref."""

    identity = "procurement.raw_budget_call"
    version = "1.1.0"

    order: ObjectRef[runtime.PurchaseOrder]
    budget: str
    reason: str
    amount: MinorMoney

    reads = (runtime.PurchaseOrder, runtime.Budget)
    writes = (runtime.PurchaseOrder,)
    calls = (_RESERVE,)
    permission = _APPROVE
    commitRequirement = CommitRequirement.ATOMIC

    def handler(
        self,
        ctx: HandlerCtx,
        order: runtime.PurchaseOrder,
        budget: str,
        reason: str,
        amount: MinorMoney,
    ) -> None:
        ctx.call(_RESERVE, budget=budget, amount=amount, expectedVersion=1)
        ctx.uow.register_mutation(
            order, status="APPROVED", approved_amount=amount.minor, expectedVersion=order.version
        )


class StrayBudgetWrite(Action):
    """A Procurement action that tries to write Finance's budget directly."""

    identity = "procurement.stray_budget_write"
    version = "1.1.0"

    order: ObjectRef[runtime.PurchaseOrder]
    budget: ObjectRef[runtime.Budget]
    reason: str
    amount: MinorMoney

    reads = (runtime.PurchaseOrder, runtime.Budget)
    writes = (runtime.PurchaseOrder,)
    permission = _APPROVE
    commitRequirement = CommitRequirement.ATOMIC

    def handler(
        self,
        ctx: HandlerCtx,
        order: runtime.PurchaseOrder,
        budget: runtime.Budget,
        reason: str,
        amount: MinorMoney,
    ) -> None:
        ctx.uow.register_mutation(budget, reserved=1, expectedVersion=budget.version)


class NoWriteChild(Action):
    """A child whose declaration grants no write at all."""

    identity = _RESERVE
    version = "1.0.0"

    budget: ObjectRef[runtime.Budget]
    amount: MinorMoney
    expectedVersion: int

    reads = (runtime.Budget,)
    writes = ()
    permission = _RESERVE_PERMISSION

    def handler(
        self,
        ctx: HandlerCtx,
        budget: runtime.Budget,
        amount: MinorMoney,
        expectedVersion: int,
    ) -> None:
        ctx.uow.register_mutation(budget, reserved=amount.minor, expectedVersion=expectedVersion)


class ProcurementVariants(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (
        runtime.PurchaseOrder,
        runtime.ApprovePurchaseOrder,
        RawBudgetCall,
        StrayBudgetWrite,
    )


class FinanceNext(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (runtime.Budget, ReserveBudgetNext)


class FinanceNoExport(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (runtime.Budget,)


class FinanceNoWrite(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (runtime.Budget, NoWriteChild)


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
    ceiling INTEGER NOT NULL,
    reserved INTEGER NOT NULL,
    version INTEGER NOT NULL
);
"""


def _database(tmp_path: Path, *, ceiling: int = 100_000, name: str = "child.sqlite3") -> Path:
    path = tmp_path / name
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO purchase_orders "
            "(id, tenant, scope, status, approved_amount, created_at, version) "
            "VALUES ('PO-1', 'A', 'team1', 'PENDING_APPROVAL', NULL, 1, 1)"
        )
        connection.execute(
            "INSERT INTO budgets (id, tenant, scope, ceiling, reserved, version) "
            "VALUES ('B-1', 'A', 'team1', ?, 0, 1)",
            (ceiling,),
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
                ("ceiling", "reserved"),
                tenant_column="tenant",
                scope_column="scope",
                currency="USD",
            ),
        ),
    )


def _linked(
    *,
    procurement_module: type[Module] = runtime.Procurement,
    finance_module: type[Module] = runtime.Finance,
) -> LinkedDeclarations:
    if procurement_module is runtime.Procurement:
        procurement_definitions = (runtime.PurchaseOrder, runtime.ApprovePurchaseOrder)
    else:
        procurement_definitions = (
            runtime.PurchaseOrder,
            runtime.ApprovePurchaseOrder,
            RawBudgetCall,
            StrayBudgetWrite,
        )
    if finance_module is runtime.Finance:
        finance_definitions = (runtime.Budget, runtime.ReserveBudget)
    elif finance_module is FinanceNext:
        finance_definitions = (runtime.Budget, ReserveBudgetNext)
    elif finance_module is FinanceNoWrite:
        finance_definitions = (runtime.Budget, NoWriteChild)
    else:
        finance_definitions = (runtime.Budget, runtime.ReserveBudget)
    return link(
        load(
            ModuleDeclarations(procurement_module, procurement_definitions),
            ModuleDeclarations(finance_module, finance_definitions),
        )
    )


def _deployment(
    *,
    delegated: bool = True,
    budget_session: str = _SESSION,
    caller: str = _ROOT,
) -> Deployment:
    grants = (
        (DelegationGrant(caller, _RESERVE, _RESERVE_PERMISSION, DelegationPrincipal.REQUESTER),)
        if delegated
        else ()
    )
    return Deployment(
        providers=(Provider("orders-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),),
        enlistments=(
            Enlistment(_ORDER, "orders-db", _SESSION),
            Enlistment(_BUDGET, "orders-db", budget_session),
        ),
        delegations=grants,
    )


def _principal(*permissions: str) -> Principal:
    return Principal("alice", _TENANT, frozenset({_READ, *permissions}))


def _grant(definition: DefinitionKey, scopes: tuple[str, ...] = (_SCOPE,)) -> ReadGrant:
    return ReadGrant("alice", definition, _TENANT, scopes, _READ)


def _ref(
    provider: SQLiteProvider,
    definition: DefinitionKey,
    target: type[object],
) -> VersionedRef[object]:
    predicate = Comparison("status", "==", "PENDING_APPROVAL") if definition == _ORDER_KEY else None
    page = query(
        provider=provider,
        principal=_principal(_APPROVE, _RESERVE_PERMISSION),
        grant=_grant(definition),
        from_=definition,
        target=target,
        order=OrderBy("created_at") if definition == _ORDER_KEY else OrderBy("id"),
        predicate=predicate,
        limit=1,
    )
    assert len(page.rows) == 1
    return page.rows[0].as_ref()


def _parameters(path: Path, *, budget: object | None = None) -> dict[str, object]:
    provider = _provider(path)
    return {
        "order": _ref(provider, _ORDER_KEY, runtime.PurchaseOrder),
        "budget": budget if budget is not None else _ref(provider, _BUDGET_KEY, runtime.Budget),
        "reason": "approved after budget check",
        "amount": _AMOUNT,
    }


def _invoke(
    path: Path,
    *,
    linked: LinkedDeclarations | None = None,
    action: DefinitionKey = _ROOT_KEY,
    parameters: Mapping[str, object] | None = None,
    principal: Principal | None = None,
    delegated: bool = True,
    budget_session: str = _SESSION,
    caller: str = _ROOT,
    grants: Mapping[DefinitionKey, ReadGrant] | None = None,
) -> ActionResult:
    graph = linked if linked is not None else _linked()
    return invoke(
        linked=graph,
        action=action,
        bound=bind_action(
            snapshot(graph),
            _deployment(delegated=delegated, budget_session=budget_session, caller=caller),
            action,
        ),
        provider=_provider(path),
        principal=principal if principal is not None else _principal(_APPROVE, _RESERVE_PERMISSION),
        grants=grants
        if grants is not None
        else {_ORDER_KEY: _grant(_ORDER_KEY), _BUDGET_KEY: _grant(_BUDGET_KEY)},
        parameters=parameters if parameters is not None else _parameters(path),
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


def _budget(path: Path) -> tuple[int, int, int]:
    connection = sqlite3.connect(path)
    try:
        found = connection.execute(
            "SELECT ceiling, reserved, version FROM budgets WHERE id = 'B-1'"
        ).fetchone()
        assert found is not None
        return int(found[0]), int(found[1]), int(found[2])
    finally:
        connection.close()


def test_declared_child_commits_order_and_reservation_in_one_transaction(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)

    result = _invoke(path)

    assert result.attempt.code == "COMMITTED"
    assert result.execution is not None
    assert result.execution.children == (_RESERVE_KEY,)
    assert len(result.writes) == 2
    assert len({write.transaction for write in result.writes}) == 1
    assert all(write.rowcount == 1 for write in result.writes)
    assert _orders(path) == ("APPROVED", 40_000, 2)
    assert _budget(path) == (100_000, 40_000, 2)


def test_child_runs_at_the_revision_pinned_by_the_linked_graph(tmp_path: Path) -> None:
    path = _database(tmp_path)

    pinned = _invoke(path)
    assert pinned.attempt.code == "COMMITTED"
    assert _budget(path) == (100_000, 40_000, 2)

    other = _database(tmp_path, name="next.sqlite3")
    decoy = _invoke(
        other,
        linked=_linked(finance_module=FinanceNext),
    )
    assert decoy.attempt.code == "COMMITTED"
    assert decoy.execution is not None
    assert decoy.execution.children == (DefinitionKey(_RESERVE, "1.1.0"),)
    assert _budget(other) == (100_000, 999_999, 2)


def test_requester_without_reserve_permission_is_denied_without_writes(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)

    result = _invoke(path, principal=_principal(_APPROVE))

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (100_000, 0, 1)


def test_call_without_a_checked_delegation_is_denied(tmp_path: Path) -> None:
    path = _database(tmp_path)

    result = _invoke(path, delegated=False)

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (100_000, 0, 1)


def test_child_ref_must_be_issued_by_a_scoped_query(tmp_path: Path) -> None:
    path = _database(tmp_path)
    graph = _linked(procurement_module=ProcurementVariants)
    action = DefinitionKey("procurement.raw_budget_call", "1.1.0")

    result = _invoke(
        path,
        linked=graph,
        action=action,
        parameters=_parameters(path, budget="B-1"),
        delegated=False,
        caller=action.identity,
    )

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (100_000, 0, 1)


def test_child_instance_outside_requester_scope_is_denied(tmp_path: Path) -> None:
    path = _database(tmp_path)

    result = _invoke(
        path,
        grants={
            _ORDER_KEY: _grant(_ORDER_KEY),
            _BUDGET_KEY: _grant(_BUDGET_KEY, ("team2",)),
        },
    )

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (100_000, 0, 1)


def test_child_business_rejection_prevents_every_write(tmp_path: Path) -> None:
    path = _database(tmp_path, ceiling=30_000)

    result = _invoke(path)

    assert result.attempt.code == "REJECTED"
    assert result.execution is not None
    assert result.execution.status == "REJECTED"
    assert result.writes == ()
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (30_000, 0, 1)


def test_procurement_cannot_write_budget_directly(tmp_path: Path) -> None:
    path = _database(tmp_path)
    graph = _linked(procurement_module=ProcurementVariants)
    action = DefinitionKey("procurement.stray_budget_write", "1.1.0")

    result = _invoke(path, linked=graph, action=action, delegated=False, caller=action.identity)

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (100_000, 0, 1)


def test_child_cannot_exceed_its_declared_write_scope(tmp_path: Path) -> None:
    path = _database(tmp_path)

    result = _invoke(path, linked=_linked(finance_module=FinanceNoWrite))

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (100_000, 0, 1)


def test_split_child_session_is_rejected_at_binding(tmp_path: Path) -> None:
    path = _database(tmp_path)

    with pytest.raises(NoSharedTransaction):
        bind_action(snapshot(_linked()), _deployment(budget_session=_OTHER_SESSION), _ROOT_KEY)
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (100_000, 0, 1)


def test_call_target_must_be_exported_by_finance() -> None:
    with pytest.raises(NotExported):
        _linked(finance_module=FinanceNoExport)


def test_static_tier_three_declaration_is_not_runnable_as_tier_two(tmp_path: Path) -> None:
    path = _database(tmp_path)
    graph = link(
        load(
            ModuleDeclarations(
                static_procurement.Procurement,
                (
                    static_procurement.PurchaseOrder,
                    static_procurement.OrderApprovedPayload,
                    static_procurement.NotifyWarehouseOrderApproved,
                    static_procurement.ApprovePurchaseOrder,
                ),
            ),
            ModuleDeclarations(
                static_finance.Finance,
                (static_finance.Money, static_finance.Budget, static_finance.ReserveBudget),
            ),
        )
    )
    action = DefinitionKey("procurement.approve_purchase_order", "2.0.0")

    result = _invoke(
        path,
        linked=graph,
        action=action,
        parameters={},
        grants={_ORDER_KEY: _grant(_ORDER_KEY)},
        caller=action.identity,
    )

    assert result.attempt.code == "DENIED"
    assert result.execution is None
    assert _orders(path) == ("PENDING_APPROVAL", None, 1)
    assert _budget(path) == (100_000, 0, 1)
