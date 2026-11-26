"""Host configuration for the conditional-approval consumer example.

This module owns identities, grants, live approver authority, the deployment
plan and the real SQLite adapters. It holds no business rule: the threshold,
role and self-approval policy are in the declaration, and the consumer only
calls public engine ports with values supplied here.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from codology import (
    OUTBOX_RESOURCE,
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
    bind_action,
    link,
    load,
    snapshot,
)
from codology.adapter import ResourceBinding, SQLiteProvider
from codology.decision import ApprovalAuthority
from codology.ports import CommitOutcomeUnknown
from codology.relay import LocalReceiver, RelayStore
from codology.relay_adapter import SQLiteLocalReceiver, SQLiteRelayStore, create_relay_schema
from codology.resume_adapter import ResumeSQLiteProvider, ResumeSQLiteUnit
from codology.waiting import RequiredApproval
from examples.conditional_approval import declarations as d
from examples.conditional_approval.database import SCOPE, TENANT, build_database

SESSION = "sqlite:conditional-approval"
REQUESTER = "alice"
APPROVER = "carol"
READ = "purchase_order.read"
EXECUTION_READ = "execution.read"
EFFECT_READ = "effect.read"
REQUEST_KEY = f"{TENANT}:{REQUESTER}:approve:PO-1:001"
REASON = "approved after budget check"

ORDER_KEY = DefinitionKey(d.ORDER, "1.0.0")
BUDGET_KEY = DefinitionKey(d.BUDGET, "1.0.0")
ROOT_KEY = DefinitionKey(d.ROOT, "2.0.0")
RESERVE_KEY = DefinitionKey(d.RESERVE, "1.0.0")
ROOT_NEXT_KEY = DefinitionKey(d.ROOT, "2.1.0")


def current_graph() -> LinkedDeclarations:
    """The revision set the execution pins when it first waits."""
    return link(
        load(
            ModuleDeclarations(
                d.Procurement,
                (
                    d.PurchaseOrder,
                    d.ApprovePurchaseOrder,
                    d.OrderApprovedPayload,
                    d.NotifyWarehouse,
                ),
            ),
            ModuleDeclarations(d.Finance, (d.Budget, d.ReserveBudget)),
        )
    )


def newer_default_graph() -> LinkedDeclarations:
    """A later default set whose handlers must never run on a pinned replay."""
    return link(
        load(
            ModuleDeclarations(
                d.ProcurementLater,
                (
                    d.PurchaseOrder,
                    d.ApprovePurchaseOrderLater,
                    d.OrderApprovedPayload,
                    d.NotifyWarehouse,
                ),
            ),
            ModuleDeclarations(d.FinanceLater, (d.Budget, d.ReserveBudgetLater)),
        )
    )


def deployment() -> Deployment:
    """One physical session for both writes and the outbox."""
    return Deployment(
        providers=(
            Provider(
                "orders-db",
                "sqlite",
                frozenset({Capability.ATOMIC_TRANSACTION, Capability.OUTBOX}),
                SESSION,
            ),
        ),
        enlistments=(
            Enlistment(d.ORDER, "orders-db", SESSION),
            Enlistment(d.BUDGET, "orders-db", SESSION),
            Enlistment(OUTBOX_RESOURCE, "orders-db", SESSION),
        ),
        delegations=(
            DelegationGrant(d.ROOT, d.RESERVE, d.RESERVE_PERMISSION, DelegationPrincipal.REQUESTER),
        ),
    )


def bound_root(graph: LinkedDeclarations) -> BoundAction:
    """Bind the root action against the shared-session plan."""
    return bind_action(snapshot(graph), deployment(), ROOT_KEY)


def bound_next(graph: LinkedDeclarations) -> BoundAction:
    """Bind the newer default root; replay still resolves the pinned revision."""
    return bind_action(snapshot(graph), deployment(), ROOT_NEXT_KEY)


def sqlite_provider(path: Path) -> SQLiteProvider:
    """Open the example session through the real adapter, never a mock."""
    return SQLiteProvider(
        path,
        SESSION,
        (
            ResourceBinding(
                d.ORDER,
                "1.0.0",
                "purchase_orders",
                ("status", "amount"),
                tenant_column="tenant",
                scope_column="scope",
            ),
            ResourceBinding(
                d.BUDGET,
                "1.0.0",
                "budgets",
                ("ceiling", "reserved"),
                tenant_column="tenant",
                scope_column="scope",
            ),
        ),
        effect_dedup=SESSION,
    )


class HostAuthority:
    """Live host authority for the approver, with revocation and audit hooks."""

    def __init__(
        self,
        *,
        roles: tuple[str, ...] = (d.APPROVAL_ROLE,),
        permissions: tuple[str, ...] = (d.APPROVE_PERMISSION,),
        scopes: tuple[str, ...] = (SCOPE,),
        revoked: set[str] | None = None,
        barrier: threading.Barrier | None = None,
    ) -> None:
        self.roles = roles
        self.permissions = permissions
        self.scopes = scopes
        self.revoked: set[str] = revoked if revoked is not None else set()
        self.barrier = barrier
        self._local = threading.local()
        self.checked: list[str] = []

    def authorize(self, principal: Principal, approval: RequiredApproval) -> ApprovalAuthority:
        if principal.identity == APPROVER and not getattr(self._local, "met", False):
            self._local.met = True
            if self.barrier is not None:
                self.barrier.wait(timeout=10)
        self.checked.append(principal.identity)
        return ApprovalAuthority(
            frozenset(self.roles),
            frozenset(self.permissions),
            TENANT,
            self.scopes,
            approval.approval_id in self.revoked,
            "host-policy-1",
        )


def requester(*extra: str) -> Principal:
    """The principal that requests the approval and later resumes it."""
    return Principal(REQUESTER, TENANT, frozenset({READ, *extra}))


def approver() -> Principal:
    """A principal in the approver role; role membership is checked live."""
    return Principal(APPROVER, TENANT, frozenset({d.APPROVE_PERMISSION}))


def reader() -> Principal:
    """A principal allowed to reconcile executions and observe effects."""
    return Principal(
        REQUESTER,
        TENANT,
        frozenset({READ, d.APPROVE_PERMISSION, d.RESERVE_PERMISSION, EXECUTION_READ, EFFECT_READ}),
    )


def outsider() -> Principal:
    """A principal with no authority to decide this approval."""
    return Principal("mallory", TENANT, frozenset())


def grants() -> dict[DefinitionKey, ReadGrant]:
    """Host-issued read grants scoped to this tenant and team."""
    return {
        ORDER_KEY: ReadGrant(REQUESTER, ORDER_KEY, TENANT, (SCOPE,), READ),
        BUDGET_KEY: ReadGrant(REQUESTER, BUDGET_KEY, TENANT, (SCOPE,), READ),
    }


@dataclass(slots=True)
class Host:
    """Everything the example's consumer receives from the host."""

    path: Path
    provider: ResumeSQLiteProvider
    store: RelayStore
    receiver: LocalReceiver
    authority: HostAuthority
    grants: Mapping[DefinitionKey, ReadGrant]
    requester: Principal
    approver: Principal
    reader: Principal
    graphs: tuple[LinkedDeclarations, LinkedDeclarations]
    bound: BoundAction
    bound_next: BoundAction


def open_host(
    path: Path,
    *,
    authority: HostAuthority | None = None,
    store: RelayStore | None = None,
    receiver: LocalReceiver | None = None,
    graphs: tuple[LinkedDeclarations, LinkedDeclarations] | None = None,
) -> Host:
    """Open a host over an already seeded database with real SQLite adapters."""
    revisions = graphs or (current_graph(), newer_default_graph())
    return Host(
        path=Path(path),
        provider=ResumeSQLiteProvider(sqlite_provider(path)),
        store=store or SQLiteRelayStore(path),
        receiver=receiver or SQLiteLocalReceiver(path),
        authority=authority or HostAuthority(),
        grants=grants(),
        requester=requester(d.APPROVE_PERMISSION, d.RESERVE_PERMISSION),
        approver=approver(),
        reader=reader(),
        graphs=revisions,
        bound=bound_root(revisions[0]),
        bound_next=bound_next(revisions[1]),
    )


def install(path: Path, **seed: object) -> Path:
    """Create a fresh seeded database including the relay's durable tables."""
    database = build_database(path, **seed)  # type: ignore[arg-type]
    create_relay_schema(database)
    return database


class InterruptedUnit(ResumeSQLiteUnit):
    """A resume unit whose commit acknowledgement is lost at a chosen point."""

    def __init__(self, *args: object, mode: str) -> None:
        super().__init__(*args)  # type: ignore[arg-type]
        self.mode = mode

    def commit(self) -> None:
        if self.mode == "before":
            raise CommitOutcomeUnknown("no commit acknowledgement")
        super().commit()
        if self.mode == "after":
            raise CommitOutcomeUnknown("lost commit acknowledgement")


class InterruptedProvider(ResumeSQLiteProvider):
    """Host-owned adapter wrapper for a deterministic lost-ack scenario."""

    def __init__(self, path: Path, *, mode: str) -> None:
        super().__init__(sqlite_provider(path))
        self.mode = mode

    def _new_unit(self, connection: sqlite3.Connection) -> ResumeSQLiteUnit:
        return InterruptedUnit(
            connection,
            self.resources,
            self._provider.ledger_table,
            self._provider.decision_table,
            self.resume_table,
            self._provider.outbox_table,
            self._provider.effect_dedup,
            mode=self.mode,
        )


__all__ = [
    "APPROVER",
    "BUDGET_KEY",
    "EFFECT_READ",
    "EXECUTION_READ",
    "Host",
    "HostAuthority",
    "ORDER_KEY",
    "READ",
    "REQUESTER",
    "REQUEST_KEY",
    "REASON",
    "RESERVE_KEY",
    "ROOT_KEY",
    "SESSION",
    "SCOPE",
    "TENANT",
    "approver",
    "bound_root",
    "current_graph",
    "deployment",
    "grants",
    "install",
    "newer_default_graph",
    "open_host",
    "outsider",
    "reader",
    "requester",
    "sqlite_provider",
    "InterruptedProvider",
    "InterruptedUnit",
]
