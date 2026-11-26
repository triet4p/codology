"""Shared SQLite fixtures and declarations for the resume gate tests."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from codology import (
    Capability,
    DefinitionKey,
    DelegationGrant,
    DelegationPrincipal,
    Deployment,
    Enlistment,
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
from codology.decision import ApprovalAuthority, DecisionResult, approve
from codology.declarations import Action, Module, ObjectRef, ObjectType, all_of
from codology.declarations.behavior import Approval, Param
from codology.engine import ActionResult, HandlerCtx, invoke
from codology.linking import LinkedDeclarations
from codology.ports import CommitOutcomeUnknown
from codology.resume import resume
from codology.resume_adapter import ResumeSQLiteProvider, ResumeSQLiteUnit
from codology.waiting import RequiredApproval

ORDER = "procurement.purchase_order"
BUDGET = "finance.budget"
ROOT = "procurement.approve_order"
RESERVE = "finance.reserve_budget"
ORDER_KEY = DefinitionKey(ORDER, "1.0.0")
BUDGET_KEY = DefinitionKey(BUDGET, "1.0.0")
ROOT_KEY = DefinitionKey(ROOT, "2.0.0")
RESERVE_KEY = DefinitionKey(RESERVE, "1.0.0")
SESSION = "sqlite:resume"
TENANT = "A"
SCOPE = "team1"
APPROVE_PERMISSION = "purchase_order.approve"
RESERVE_PERMISSION = "budget.reserve"
READ = "purchase_order.read"
REQUEST_KEY = "tenant-a:alice:approve:PO-1:001"
ROLE = "finance_director"
APPROVER = "carol"

SCHEMA = """
CREATE TABLE purchase_orders (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, scope TEXT NOT NULL,
    status TEXT NOT NULL, amount INTEGER NOT NULL, created_at INTEGER NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE budgets (
    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, scope TEXT NOT NULL,
    ceiling INTEGER NOT NULL, reserved INTEGER NOT NULL, version INTEGER NOT NULL
);
CREATE TABLE request_ledger (
    tenant TEXT NOT NULL, principal TEXT NOT NULL, action TEXT NOT NULL,
    request_key TEXT NOT NULL, intent_fingerprint TEXT NOT NULL,
    execution_id TEXT NOT NULL, action_version TEXT NOT NULL, status TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (tenant, principal, action, request_key)
);
CREATE INDEX ledger_execution ON request_ledger(execution_id);
CREATE TABLE outbox (id TEXT PRIMARY KEY, dedup_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE approval_decisions (
    callback_key TEXT PRIMARY KEY, execution_id TEXT NOT NULL,
    approval_id TEXT NOT NULL, decision TEXT NOT NULL,
    intent_fingerprint TEXT NOT NULL, reason TEXT NOT NULL,
    principal TEXT NOT NULL, approval TEXT NOT NULL,
    authority_revision TEXT, recorded_at TEXT NOT NULL
);
CREATE TABLE approval_audit (
    attempt_id TEXT PRIMARY KEY, callback_key TEXT NOT NULL,
    execution_id TEXT NOT NULL, principal TEXT NOT NULL, code TEXT NOT NULL,
    detail TEXT, decision TEXT, intent_fingerprint TEXT, recorded_at TEXT NOT NULL
);
CREATE TABLE approval_resume_outcomes (
    callback_key TEXT PRIMARY KEY, execution_id TEXT NOT NULL,
    outcome TEXT NOT NULL, detail TEXT, recorded_at TEXT NOT NULL
);
"""


class PurchaseOrder(ObjectType):
    identity = ORDER
    version = "1.0.0"
    keyType = "PO"

    status: str
    amount: int


class Budget(ObjectType):
    identity = BUDGET
    version = "1.0.0"
    keyType = "B"

    ceiling: int
    reserved: int


class ReserveBudget(Action):
    identity = RESERVE
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: int
    expectedVersion: int

    reads = (Budget,)
    writes = (Budget,)
    permission = RESERVE_PERMISSION

    def handler(self, ctx: HandlerCtx, budget: Budget, amount: int, expectedVersion: int) -> None:
        ctx.require(budget.reserved + amount <= budget.ceiling, reason="budget_insufficient")
        ctx.uow.register_mutation(
            budget, reserved=budget.reserved + amount, expectedVersion=expectedVersion
        )


class ReserveBudgetLater(Action):
    """A newer default child whose handler must never run on resume."""

    identity = RESERVE
    version = "1.1.0"

    budget: ObjectRef[Budget]
    amount: int
    expectedVersion: int

    reads = (Budget,)
    writes = (Budget,)
    permission = RESERVE_PERMISSION

    def handler(self, ctx: HandlerCtx, budget: Budget, amount: int, expectedVersion: int) -> None:
        raise AssertionError("the unpinned child handler must not run")


class ApproveOrder(Action):
    identity = ROOT
    version = "2.0.0"

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]
    reason: str

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (RESERVE,)
    permission = APPROVE_PERMISSION
    approval = Approval.conditional(
        when=all_of(Param("order").amount >= 100_000, Param("reason") != ""),
        role=ROLE,
        self_approval=False,
    )

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget, reason: str) -> None:
        ctx.require(order.status == "PENDING", reason="order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")
        ctx.call(RESERVE, budget=budget, amount=order.amount, expectedVersion=budget.version)
        ctx.uow.register_mutation(order, status="APPROVED", expectedVersion=order.version)


class ApproveOrderLater(Action):
    """A newer default root whose handler must never run on resume."""

    identity = ROOT
    version = "2.1.0"

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]
    reason: str

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (RESERVE,)
    permission = APPROVE_PERMISSION
    approval = Approval.conditional(
        when=all_of(Param("order").amount >= 100_000, Param("reason") != ""),
        role=ROLE,
        self_approval=False,
    )

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget, reason: str) -> None:
        raise AssertionError("the unpinned root handler must not run")


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApproveOrder)


class ProcurementLater(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApproveOrderLater)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


class FinanceLater(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudgetLater)


OLD_GRAPH = link(
    load(
        ModuleDeclarations(Procurement, (PurchaseOrder, ApproveOrder)),
        ModuleDeclarations(Finance, (Budget, ReserveBudget)),
    )
)
LATER_GRAPH = link(
    load(
        ModuleDeclarations(ProcurementLater, (PurchaseOrder, ApproveOrderLater)),
        ModuleDeclarations(FinanceLater, (Budget, ReserveBudgetLater)),
    )
)


class HostAuthority:
    """Host-owned live approver authority with deterministic race hooks."""

    def __init__(
        self,
        *,
        roles: tuple[str, ...] = (ROLE,),
        permissions: tuple[str, ...] = (APPROVE_PERMISSION,),
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
        self.checks: list[str] = []

    def authorize(self, principal: Principal, approval: RequiredApproval) -> ApprovalAuthority:
        if principal.identity == APPROVER and not getattr(self._local, "met", False):
            self._local.met = True
            if self.barrier is not None:
                self.barrier.wait(timeout=10)
        self.checks.append(principal.identity)
        return ApprovalAuthority(
            frozenset(self.roles),
            frozenset(self.permissions),
            TENANT,
            self.scopes,
            approval.approval_id in self.revoked,
            "policy-1",
        )


@dataclass(frozen=True, slots=True)
class Case:
    path: Path
    provider: ResumeSQLiteProvider
    parameters: dict[str, object]
    waiting: ActionResult
    decision: DecisionResult
    authority: HostAuthority

    @property
    def execution_id(self) -> str:
        assert self.waiting.execution is not None
        return self.waiting.execution.execution_id

    @property
    def approval(self) -> RequiredApproval:
        assert self.waiting.execution is not None
        approval = self.waiting.execution.required_approval
        assert approval is not None
        return approval

    @property
    def callback_key(self) -> str:
        return self.approval.callback_key

    @property
    def fingerprint(self) -> str:
        return self.approval.intent_fingerprint


class HookedUnit(ResumeSQLiteUnit):
    """A unit whose commit is interrupted at a deterministic point."""

    def __init__(self, *args: object, mode: str) -> None:
        super().__init__(*args)  # type: ignore[arg-type]
        self.mode = mode

    def commit(self) -> None:
        if self.mode == "before":
            raise CommitOutcomeUnknown("no commit acknowledgement")
        super().commit()
        if self.mode == "after":
            raise CommitOutcomeUnknown("lost commit acknowledgement")


class HookedProvider(ResumeSQLiteProvider):
    """Injects a competing writer or a commit acknowledgement failure."""

    def __init__(
        self,
        base: SQLiteProvider,
        *,
        before_unit: Callable[[], None] | None = None,
        commit_mode: str | None = None,
    ) -> None:
        super().__init__(base)
        self.before_unit = before_unit
        self.commit_mode = commit_mode

    def resume_unit(self) -> ResumeSQLiteUnit:
        if self.before_unit is not None:
            self.before_unit()
        return super().resume_unit()

    def _new_unit(self, connection: sqlite3.Connection) -> ResumeSQLiteUnit:
        if self.commit_mode is None:
            return super()._new_unit(connection)
        return HookedUnit(
            connection,
            self.resources,
            self._provider.ledger_table,
            self._provider.decision_table,
            self.resume_table,
            mode=self.commit_mode,
        )


def database(tmp_path: Path, *, amount: int = 120_000, status: str = "PENDING") -> Path:
    path = tmp_path / "resume.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT INTO purchase_orders (id, tenant, scope, status, amount, created_at, version) "
            "VALUES ('PO-1', ?, ?, ?, ?, 1, 1)",
            (TENANT, SCOPE, status, amount),
        )
        connection.execute(
            "INSERT INTO budgets (id, tenant, scope, ceiling, reserved, version) "
            "VALUES ('B-1', ?, ?, 1_000_000, 0, 1)",
            (TENANT, SCOPE),
        )
        connection.commit()
    finally:
        connection.close()
    return path


def sqlite(path: Path) -> SQLiteProvider:
    return SQLiteProvider(
        path,
        SESSION,
        (
            ResourceBinding(
                ORDER,
                "1.0.0",
                "purchase_orders",
                ("status", "amount"),
                tenant_column="tenant",
                scope_column="scope",
            ),
            ResourceBinding(
                BUDGET,
                "1.0.0",
                "budgets",
                ("ceiling", "reserved"),
                tenant_column="tenant",
                scope_column="scope",
            ),
        ),
    )


def provider(path: Path) -> ResumeSQLiteProvider:
    return ResumeSQLiteProvider(sqlite(path))


def deployment() -> Deployment:
    return Deployment(
        providers=(Provider("orders-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),),
        enlistments=(
            Enlistment(ORDER, "orders-db", SESSION),
            Enlistment(BUDGET, "orders-db", SESSION),
        ),
        delegations=(
            DelegationGrant(ROOT, RESERVE, RESERVE_PERMISSION, DelegationPrincipal.REQUESTER),
        ),
    )


def principal(*permissions: str) -> Principal:
    return Principal("alice", TENANT, frozenset({READ, *permissions}))


def approver() -> Principal:
    return Principal(APPROVER, TENANT, frozenset({APPROVE_PERMISSION}))


def reader() -> Principal:
    return Principal(
        "alice",
        TENANT,
        frozenset({READ, APPROVE_PERMISSION, RESERVE_PERMISSION, "execution.read"}),
    )


def grant(definition: DefinitionKey) -> ReadGrant:
    return ReadGrant("alice", definition, TENANT, (SCOPE,), READ)


def grants() -> dict[DefinitionKey, ReadGrant]:
    return {ORDER_KEY: grant(ORDER_KEY), BUDGET_KEY: grant(BUDGET_KEY)}


def parameters(pro: ResumeSQLiteProvider) -> dict[str, object]:
    caller = principal(APPROVE_PERMISSION, RESERVE_PERMISSION)

    def ref(definition: DefinitionKey, target: type[object]) -> VersionedRef[object]:
        page = query(
            provider=pro,
            principal=caller,
            grant=grant(definition),
            from_=definition,
            target=target,
            order=OrderBy("id"),
            predicate=None,
            limit=10,
        )
        assert len(page.rows) == 1
        return page.rows[0].as_ref()

    return {
        "order": ref(ORDER_KEY, PurchaseOrder),
        "budget": ref(BUDGET_KEY, Budget),
        "reason": "approved after budget check",
    }


def case(
    tmp_path: Path,
    *,
    amount: int = 120_000,
    status: str = "PENDING",
    expires_at: str | None = None,
    authority: HostAuthority | None = None,
) -> Case:
    path = database(tmp_path, amount=amount, status=status)
    pro = provider(path)
    waiting = invoke(
        linked=OLD_GRAPH,
        action=ROOT_KEY,
        bound=bind_action(snapshot(OLD_GRAPH), deployment(), ROOT_KEY),
        provider=pro,
        principal=principal(APPROVE_PERMISSION, RESERVE_PERMISSION),
        grants=grants(),
        parameters=parameters(pro),
        request_key=REQUEST_KEY,
        approval_expires_at=expires_at,
    )
    assert waiting.attempt.code == "AWAITING_APPROVAL"
    assert waiting.execution is not None and waiting.execution.required_approval is not None
    authority = authority or HostAuthority()
    decision = approve(
        provider=pro,
        authority_provider=authority,
        principal=approver(),
        execution_id=waiting.execution.execution_id,
        callback_key=waiting.execution.required_approval.callback_key,
        expected_intent_fingerprint=waiting.execution.required_approval.intent_fingerprint,
        reason="budget confirmed",
    )
    assert decision.decision is not None
    return Case(path, pro, parameters(pro), waiting, decision, authority)


def resume_case(
    target: Case,
    *,
    pro: ResumeSQLiteProvider | None = None,
    caller: Principal | None = None,
    authority: HostAuthority | None = None,
    revisions: tuple[LinkedDeclarations, ...] | None = None,
    callback_key: str | None = None,
    now: datetime | None = None,
    expires_at: str | None = None,
) -> ActionResult:
    return resume(
        provider=pro or target.provider,
        revisions=revisions if revisions is not None else (LATER_GRAPH, OLD_GRAPH),
        bound=bind_action(snapshot(OLD_GRAPH), deployment(), ROOT_KEY),  # type: ignore[arg-type]
        principal=caller or principal(APPROVE_PERMISSION, RESERVE_PERMISSION),
        grants=grants(),
        execution_id=target.execution_id,
        callback_key=callback_key or target.callback_key,
        authority_provider=authority or target.authority,
        now=now,
        approval_expires_at=expires_at,
    )


def rows(path: Path, table: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        connection.close()


def update(path: Path, statement: str, values: tuple[object, ...] = ()) -> None:
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute(statement, values)
        connection.commit()
    finally:
        connection.close()
