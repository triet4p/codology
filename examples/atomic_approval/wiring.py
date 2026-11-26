"""Wiring for the executable Procurement/Finance example: graph, plan, principals.

This module is host configuration. It composes the tier-2 declarations from
``examples.procurement_finance.runtime`` through Load, Link, Snapshot and
deployment binding, then exposes the adapter, principals and host-issued read
grants a caller needs. It contains no business rule: permission checks, budget
arithmetic and writes live in the declared handlers and the engine.
"""

from __future__ import annotations

from pathlib import Path

from codology import (
    EXECUTION_READ_PERMISSION,
    BoundAction,
    Capability,
    DefinitionKey,
    DelegationGrant,
    DelegationPrincipal,
    Deployment,
    Enlistment,
    LinkedDeclarations,
    ModuleDeclarations,
    Principal,
    Provider,
    ReadGrant,
    Snapshot,
    bind_action,
    link,
    load,
    snapshot,
)
from codology.adapter import ResourceBinding, SQLiteProvider
from examples.procurement_finance import runtime

ORDER_KEY = DefinitionKey("procurement.purchase_order", "1.0.0")
BUDGET_KEY = DefinitionKey("finance.budget", "1.0.0")
RESERVE_KEY = DefinitionKey("finance.reserve_budget", "1.0.0")
APPROVE_KEY = DefinitionKey("procurement.approve_purchase_order", "1.1.0")

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
SCOPE = "team-1"
SESSION = "sqlite:approval"

READ_ORDER = "purchase_order.read"
READ_BUDGET = "finance.budget.read"
APPROVE_PERMISSION = "purchase_order.approve"
RESERVE_PERMISSION = "budget.reserve"

_RESOURCES = (
    ResourceBinding(
        ORDER_KEY.identity,
        ORDER_KEY.version,
        "purchase_orders",
        ("status", "approved_amount"),
        tenant_column="tenant",
        scope_column="scope",
    ),
    ResourceBinding(
        BUDGET_KEY.identity,
        BUDGET_KEY.version,
        "budgets",
        ("ceiling", "reserved"),
        tenant_column="tenant",
        scope_column="scope",
        currency="USD",
    ),
)


def linked_graph() -> LinkedDeclarations:
    """Load and link the tier-2 declarations; no static tier-3 class participates."""
    return link(
        load(
            ModuleDeclarations(
                runtime.Procurement, (runtime.PurchaseOrder, runtime.ApprovePurchaseOrder)
            ),
            ModuleDeclarations(runtime.Finance, (runtime.Budget, runtime.ReserveBudget)),
        )
    )


def published_snapshot() -> Snapshot:
    """Publish the linked graph; binding looks actions up at exact versions."""
    return snapshot(linked_graph())


def deployment() -> Deployment:
    """One provider session hosts both resources and the request ledger."""
    return Deployment(
        providers=(Provider("approval-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),),
        enlistments=(
            Enlistment(ORDER_KEY.identity, "approval-db", SESSION),
            Enlistment(BUDGET_KEY.identity, "approval-db", SESSION),
        ),
        delegations=(
            DelegationGrant(
                APPROVE_KEY.identity,
                RESERVE_KEY.identity,
                RESERVE_PERMISSION,
                DelegationPrincipal.REQUESTER,
            ),
        ),
    )


def split_deployment() -> Deployment:
    """Two file-backed sessions that look alike but cannot share a transaction."""
    return Deployment(
        providers=(
            Provider("orders-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),
            Provider("budget-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),
        ),
        enlistments=(
            Enlistment(ORDER_KEY.identity, "orders-db", "sqlite:orders"),
            Enlistment(BUDGET_KEY.identity, "budget-db", "sqlite:budget"),
        ),
        delegations=(
            DelegationGrant(
                APPROVE_KEY.identity,
                RESERVE_KEY.identity,
                RESERVE_PERMISSION,
                DelegationPrincipal.REQUESTER,
            ),
        ),
    )


def bound_approval() -> BoundAction:
    """Bind the example action against the shared-session deployment."""
    return bind_action(published_snapshot(), deployment(), APPROVE_KEY)


def sqlite_provider(database: Path) -> SQLiteProvider:
    """Open the example session through the real adapter; never a mock."""
    return SQLiteProvider(database, SESSION, _RESOURCES)


def alice() -> Principal:
    """Requester holding read, approve, reserve and execution-record authority."""
    return Principal(
        "alice",
        TENANT_A,
        frozenset(
            {
                READ_ORDER,
                READ_BUDGET,
                APPROVE_PERMISSION,
                RESERVE_PERMISSION,
                EXECUTION_READ_PERMISSION,
            }
        ),
    )


def bob() -> Principal:
    """Reader without the live invoke permission; read authority is not write authority."""
    return Principal("bob", TENANT_A, frozenset({READ_ORDER, READ_BUDGET}))


def outsider() -> Principal:
    """Principal with no permissions at all."""
    return Principal("mallory", TENANT_A, frozenset())


def grants_for(
    principal: Principal, *, scopes: tuple[str, ...] = (SCOPE,)
) -> dict[DefinitionKey, ReadGrant]:
    """Host-issued read grants for both resources, scoped to the given scopes."""
    return {
        ORDER_KEY: ReadGrant(principal.identity, ORDER_KEY, principal.tenant, scopes, READ_ORDER),
        BUDGET_KEY: ReadGrant(
            principal.identity, BUDGET_KEY, principal.tenant, scopes, READ_BUDGET
        ),
    }


__all__ = [
    "APPROVE_KEY",
    "APPROVE_PERMISSION",
    "BUDGET_KEY",
    "ORDER_KEY",
    "READ_BUDGET",
    "READ_ORDER",
    "RESERVE_KEY",
    "RESERVE_PERMISSION",
    "SCOPE",
    "SESSION",
    "TENANT_A",
    "TENANT_B",
    "alice",
    "bob",
    "bound_approval",
    "deployment",
    "grants_for",
    "linked_graph",
    "outsider",
    "published_snapshot",
    "split_deployment",
    "sqlite_provider",
]
