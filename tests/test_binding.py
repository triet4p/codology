"""Deployment binding checks for an atomic cross-module action.

The fixture is a tier-2 contract: the root action writes the order and calls a
Finance action that writes the budget. Every handler raises, so a passing test
also proves binding only inspects the published plan.
"""

from __future__ import annotations

import pytest

from codology import (
    AmbientServiceIdentity,
    Capability,
    DefinitionKey,
    DelegationGrant,
    DelegationPrincipal,
    Deployment,
    Enlistment,
    MissingCapability,
    ModuleDeclarations,
    NoSharedTransaction,
    PermissionBroadened,
    Provider,
    Snapshot,
    UnboundWrite,
    UndeclaredCall,
    bind_action,
    link,
    load,
    snapshot,
)
from codology.declarations import Action, CommitRequirement, Module, ObjectRef, ObjectType


class Budget(ObjectType):
    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"

    limit: int
    reserved: int


class PurchaseOrder(ObjectType):
    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"

    status: str
    amount: int


class ReserveBudget(Action):
    identity = "finance.reserve_budget"
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: int

    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget, amount: int) -> None:
        raise AssertionError("static binding must never execute a handler")


class ApproveOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "1.1.0"

    order: ObjectRef[PurchaseOrder]

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = ("finance.reserve_budget",)
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC

    def handler(self, ctx: object, order: PurchaseOrder) -> None:
        raise AssertionError("static binding must never execute a handler")


class ReserveBudgetAtomically(Action):
    """A child action whose own contract also demands one atomic commit."""

    identity = "finance.reserve_budget_atomically"
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: int

    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"
    commitRequirement = CommitRequirement.ATOMIC

    def handler(self, ctx: object, budget: Budget, amount: int) -> None:
        raise AssertionError("static binding must never execute a handler")


class SettleOrder(Action):
    """A non-atomic root that delegates a write to an atomic child action."""

    identity = "procurement.settle_purchase_order"
    version = "1.0.0"

    order: ObjectRef[PurchaseOrder]

    reads = (PurchaseOrder,)
    writes = (PurchaseOrder,)
    calls = ("finance.reserve_budget_atomically",)
    permission = "purchase_order.settle"

    def handler(self, ctx: object, order: PurchaseOrder) -> None:
        raise AssertionError("static binding must never execute a handler")


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApproveOrder, SettleOrder)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget, ReserveBudgetAtomically)


_APPROVE = DefinitionKey("procurement.approve_purchase_order", "1.1.0")
_SETTLE = DefinitionKey("procurement.settle_purchase_order", "1.0.0")
_RESERVE = DefinitionKey("finance.reserve_budget", "1.0.0")
_ORDER_KEY = DefinitionKey("procurement.purchase_order", "1.0.0")
_BUDGET_KEY = DefinitionKey("finance.budget", "1.0.0")
_ORDER = "procurement.purchase_order"
_BUDGET = "finance.budget"
_RESERVE_ID = "finance.reserve_budget"
_CAPABILITIES = frozenset({Capability.ATOMIC_TRANSACTION})


def _published() -> Snapshot:
    return snapshot(
        link(
            load(
                ModuleDeclarations(
                    Procurement,
                    (PurchaseOrder, ApproveOrder, SettleOrder),
                ),
                ModuleDeclarations(
                    Finance,
                    (Budget, ReserveBudget, ReserveBudgetAtomically),
                ),
            )
        )
    )


def _shared_provider() -> Provider:
    return Provider("orders-db", "sqlite", _CAPABILITIES)


def _shared_enlistments() -> tuple[Enlistment, ...]:
    return (
        Enlistment(_ORDER, "orders-db", "sqlite:main"),
        Enlistment(_BUDGET, "orders-db", "sqlite:main"),
    )


def _grant() -> DelegationGrant:
    return DelegationGrant(
        caller=_APPROVE.identity,
        call=_RESERVE_ID,
        permission="budget.reserve",
    )


def test_sufficient_atomic_deployment_binds_one_session_plan() -> None:
    deployment = Deployment(
        providers=(_shared_provider(),),
        enlistments=_shared_enlistments(),
        delegations=(_grant(),),
    )

    bound = bind_action(_published(), deployment, _APPROVE)

    assert bound.action == _APPROVE
    assert bound.commit_requirement == CommitRequirement.ATOMIC.value
    assert bound.session is not None
    assert bound.session.provider == "orders-db"
    assert bound.session.session == "sqlite:main"
    assert bound.session.capabilities == _CAPABILITIES

    writes = {write.resource: write for write in bound.writes}
    assert set(writes) == {_ORDER_KEY, _BUDGET_KEY}
    assert writes[_ORDER_KEY].via == (_APPROVE,)
    assert writes[_BUDGET_KEY].via == (_APPROVE, _RESERVE)
    assert {write.provider for write in bound.writes} == {"orders-db"}
    assert {write.session for write in bound.writes} == {"sqlite:main"}
    assert set(bound.session.writes) == {_ORDER_KEY, _BUDGET_KEY}

    assert len(bound.calls) == 1
    call = bound.calls[0]
    assert call.caller == _APPROVE
    assert call.callee == _RESERVE
    assert call.permission == "budget.reserve"

    assert len(bound.delegations) == 1
    delegation = bound.delegations[0]
    assert delegation.caller == _APPROVE
    assert delegation.callee == _RESERVE
    assert delegation.permission == "budget.reserve"


def test_missing_atomic_capability_is_rejected() -> None:
    deployment = Deployment(
        providers=(Provider("orders-db", "sqlite"),),
        enlistments=_shared_enlistments(),
    )

    with pytest.raises(MissingCapability) as raised:
        bind_action(_published(), deployment, _APPROVE)

    error = raised.value
    assert error.action == _APPROVE
    assert error.field == "capabilities"
    assert "atomic_transaction" in str(error)
    assert "orders-db" in str(error)


def test_transitive_child_write_must_be_enlisted() -> None:
    deployment = Deployment(
        providers=(_shared_provider(),),
        enlistments=(Enlistment(_ORDER, "orders-db", "sqlite:main"),),
    )

    with pytest.raises(UnboundWrite) as raised:
        bind_action(_published(), deployment, _APPROVE)

    error = raised.value
    assert error.action == _APPROVE
    assert error.field == "writes"
    assert _BUDGET in str(error)
    assert _RESERVE_ID in str(error)


def test_two_independent_sessions_of_the_same_database_kind_are_rejected() -> None:
    providers = (
        Provider("orders-db", "sqlite", _CAPABILITIES),
        Provider("budget-db", "sqlite", _CAPABILITIES),
    )
    assert {provider.kind for provider in providers} == {"sqlite"}
    deployment = Deployment(
        providers=providers,
        enlistments=(
            Enlistment(_ORDER, "orders-db", "sqlite:orders"),
            Enlistment(_BUDGET, "budget-db", "sqlite:budget"),
        ),
    )

    with pytest.raises(NoSharedTransaction) as raised:
        bind_action(_published(), deployment, _APPROVE)

    error = raised.value
    assert error.action == _APPROVE
    assert error.field == "sessions"
    assert "sqlite:orders" in str(error)
    assert "sqlite:budget" in str(error)
    assert "physical session" in str(error)


def test_ambient_service_delegation_is_rejected() -> None:
    grant = DelegationGrant(
        caller=_APPROVE.identity,
        call=_RESERVE_ID,
        permission="budget.reserve",
        principal=DelegationPrincipal.SERVICE,
    )
    deployment = Deployment(
        providers=(_shared_provider(),),
        enlistments=_shared_enlistments(),
        delegations=(grant,),
    )

    with pytest.raises(AmbientServiceIdentity) as raised:
        bind_action(_published(), deployment, _APPROVE)

    error = raised.value
    assert error.action == _APPROVE
    assert error.field == "delegations"
    assert "service" in str(error)
    assert "requester" in str(error)


def test_delegation_grant_for_an_undeclared_call_is_rejected() -> None:
    grant = DelegationGrant(
        caller=_APPROVE.identity,
        call="finance.settle_budget",
        permission="budget.settle",
    )
    deployment = Deployment(
        providers=(_shared_provider(),),
        enlistments=_shared_enlistments(),
        delegations=(grant,),
    )

    with pytest.raises(UndeclaredCall) as raised:
        bind_action(_published(), deployment, _APPROVE)

    error = raised.value
    assert error.action == _APPROVE
    assert error.field == "delegations"
    assert "finance.settle_budget" in str(error)
    assert f"{_RESERVE_ID}@1.0.0" in str(error)


def test_delegation_permission_broader_than_the_child_contract_is_rejected() -> None:
    grant = DelegationGrant(
        caller=_APPROVE.identity,
        call=_RESERVE_ID,
        permission="budget.*",
    )
    deployment = Deployment(
        providers=(_shared_provider(),),
        enlistments=_shared_enlistments(),
        delegations=(grant,),
    )

    with pytest.raises(PermissionBroadened) as raised:
        bind_action(_published(), deployment, _APPROVE)

    error = raised.value
    assert error.action == _APPROVE
    assert error.field == "delegations"
    assert "'budget.*'" in str(error)
    assert "'budget.reserve'" in str(error)


def test_action_binds_without_delegation_grants() -> None:
    deployment = Deployment(
        providers=(_shared_provider(),),
        enlistments=_shared_enlistments(),
    )

    bound = bind_action(_published(), deployment, _APPROVE)

    assert bound.delegations == ()
    assert bound.session is not None
    assert bound.session.session == "sqlite:main"


def test_child_atomic_requirement_also_requires_provider_capability() -> None:
    deployment = Deployment(
        providers=(Provider("orders-db", "sqlite"),),
        enlistments=_shared_enlistments(),
    )

    with pytest.raises(MissingCapability) as raised:
        bind_action(_published(), deployment, _SETTLE)

    error = raised.value
    assert error.action == _SETTLE
    assert error.field == "capabilities"
    assert "atomic_transaction" in str(error)
