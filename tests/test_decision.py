"""Decision gate: live approver authority, callback keys, audit and terminal reject."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

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
    decode_awaiting,
    encode_awaiting,
    link,
    load,
    query,
    snapshot,
)
from codology.adapter import ResourceBinding, SQLiteProvider
from codology.decision import ApprovalAuthority, DecisionResult, approve, reject
from codology.declarations import Action, Module, ObjectRef, ObjectType, all_of
from codology.declarations.behavior import Approval, Param
from codology.engine import ActionResult, HandlerCtx, invoke, reconcile
from codology.linking import LinkedDeclarations
from codology.ports import TransactionUnavailable
from codology.waiting import AwaitingExecution, RequiredApproval

_ORDER = "procurement.purchase_order"
_BUDGET = "finance.budget"
_ROOT = "procurement.approve_order"
_RESERVE = "finance.reserve_budget"
_ORDER_KEY = DefinitionKey(_ORDER, "1.0.0")
_BUDGET_KEY = DefinitionKey(_BUDGET, "1.0.0")
_ROOT_KEY = DefinitionKey(_ROOT, "2.0.0")
_SELF_KEY = DefinitionKey(_ROOT, "2.1.0")
_RESERVE_KEY = DefinitionKey(_RESERVE, "1.0.0")
_SESSION = "sqlite:decision"
_TENANT = "A"
_SCOPE = "team1"
_APPROVE = "purchase_order.approve"
_RESERVE_PERMISSION = "budget.reserve"
_READ = "purchase_order.read"
_REQUEST_KEY = "tenant-a:alice:approve:PO-1:001"
_ROLE = "finance_director"

_SCHEMA = """
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
            budget, reserved=budget.reserved + amount, expectedVersion=expectedVersion
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
        role=_ROLE,
        self_approval=False,
    )

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget, reason: str) -> None:
        ctx.require(order.status == "PENDING", reason="order_not_pending")
        ctx.call(_RESERVE, budget=budget, amount=order.amount, expectedVersion=budget.version)
        ctx.uow.register_mutation(order, status="APPROVED", expectedVersion=order.version)


class ApproveOrderSelf(Action):
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
        role=_ROLE,
        self_approval=True,
    )

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget, reason: str) -> None:
        ctx.require(order.status == "PENDING", reason="order_not_pending")
        ctx.call(_RESERVE, budget=budget, amount=order.amount, expectedVersion=budget.version)
        ctx.uow.register_mutation(order, status="APPROVED", expectedVersion=order.version)


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApproveOrder, ApproveOrderSelf)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


class HostAuthority:
    """Host-owned live role, permission, scope and revocation for callbacks."""

    def __init__(
        self,
        *,
        roles: tuple[str, ...] = (_ROLE,),
        permissions: tuple[str, ...] = (_APPROVE,),
        scopes: tuple[str, ...] = (_SCOPE,),
        tenant: str = _TENANT,
        revoked: set[str] | None = None,
        revision: str = "policy-1",
        unavailable: bool = False,
    ) -> None:
        self.roles = roles
        self.permissions = permissions
        self.scopes = scopes
        self.tenant = tenant
        self.revoked: set[str] = revoked if revoked is not None else set()
        self.revision = revision
        self.unavailable = unavailable
        self.decisions: list[tuple[str, str]] = []

    def authorize(self, principal: Principal, approval: RequiredApproval) -> ApprovalAuthority:
        self.decisions.append((principal.identity, approval.approval_id))
        if self.unavailable:
            raise TransactionUnavailable("policy source is unavailable")
        return ApprovalAuthority(
            frozenset(self.roles),
            frozenset(self.permissions),
            self.tenant,
            self.scopes,
            approval.approval_id in self.revoked,
            self.revision,
        )


def _database(tmp_path: Path, *, amount: int = 120_000, name: str = "decision.sqlite3") -> Path:
    path = tmp_path / name
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO purchase_orders (id, tenant, scope, status, amount, created_at, version) "
            "VALUES ('PO-1', ?, ?, 'PENDING', ?, 1, 1)",
            (_TENANT, _SCOPE, amount),
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


def _linked(*, self_approval: bool = False) -> LinkedDeclarations:
    exported = (PurchaseOrder, ApproveOrderSelf) if self_approval else (PurchaseOrder, ApproveOrder)
    return link(
        load(
            ModuleDeclarations(Procurement, exported),
            ModuleDeclarations(Finance, (Budget, ReserveBudget)),
        )
    )


def _deployment() -> Deployment:
    return Deployment(
        providers=(Provider("decision-db", "sqlite", frozenset({Capability.ATOMIC_TRANSACTION})),),
        enlistments=(
            Enlistment(_ORDER, "decision-db", _SESSION),
            Enlistment(_BUDGET, "decision-db", _SESSION),
        ),
        delegations=(
            DelegationGrant(_ROOT, _RESERVE, _RESERVE_PERMISSION, DelegationPrincipal.REQUESTER),
        ),
    )


def _requester() -> Principal:
    return Principal("alice", _TENANT, frozenset({_READ, _APPROVE, _RESERVE_PERMISSION}))


def _approver() -> Principal:
    return Principal("dana", _TENANT, frozenset({_APPROVE}))


def _parameters(path: Path) -> dict[str, object]:
    provider = _provider(path)

    def ref(definition: DefinitionKey, target: type[object]) -> VersionedRef[object]:
        grant = ReadGrant("alice", definition, _TENANT, (_SCOPE,), _READ)
        page = query(
            provider=provider,
            principal=_requester(),
            grant=grant,
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


def _pending(
    path: Path,
    *,
    self_approval: bool = False,
    expires_at: str | None = None,
) -> ActionResult:
    action = _SELF_KEY if self_approval else _ROOT_KEY
    graph = _linked(self_approval=self_approval)
    return invoke(
        linked=graph,
        action=action,
        bound=bind_action(snapshot(graph), _deployment(), action),
        provider=_provider(path),
        principal=_requester(),
        grants={
            _ORDER_KEY: ReadGrant("alice", _ORDER_KEY, _TENANT, (_SCOPE,), _READ),
            _BUDGET_KEY: ReadGrant("alice", _BUDGET_KEY, _TENANT, (_SCOPE,), _READ),
        },
        parameters=_parameters(path),
        request_key=_REQUEST_KEY,
        approval_expires_at=expires_at,
    )


def _rows(path: Path, table: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        connection.close()


def _call(
    pending: ActionResult,
    path: Path,
    authority: HostAuthority,
    *,
    kind: Literal["APPROVE", "REJECT"] = "APPROVE",
    principal: Principal | None = None,
    callback_key: str | None = None,
    fingerprint: str | None = None,
    reason: str = "approved after budget check",
    now: datetime | None = None,
    provider: SQLiteProvider | None = None,
) -> DecisionResult:
    assert pending.execution is not None and pending.execution.required_approval is not None
    gate = approve if kind == "APPROVE" else reject
    return gate(
        provider=provider if provider is not None else _provider(path),
        authority_provider=authority,
        principal=principal if principal is not None else _approver(),
        execution_id=pending.execution.execution_id,
        callback_key=(
            callback_key
            if callback_key is not None
            else pending.execution.required_approval.callback_key
        ),
        expected_intent_fingerprint=(
            fingerprint
            if fingerprint is not None
            else pending.execution.required_approval.intent_fingerprint
        ),
        reason=reason,
        now=now,
    )


def test_authorized_approve_records_decision_without_business_write(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)
    assert pending.execution is not None and pending.attempt.code == "AWAITING_APPROVAL"

    result = _call(pending, path, HostAuthority())

    assert result.attempt.code == "AWAITING_APPROVAL"
    assert result.attempt.reason == "APPROVED"
    assert result.decision is not None and result.decision.decision == "APPROVE"
    assert result.decision.approval.permission == _APPROVE
    assert result.execution is not None and result.execution.status == "AWAITING_APPROVAL"
    assert result.execution.deduplicated is False
    assert result.writes == ()
    assert _rows(path, "purchase_orders")[0][3] == "PENDING"
    assert _rows(path, "budgets")[0][4] == 0
    assert _rows(path, "outbox") == []
    assert len(_rows(path, "request_ledger")) == 1
    decisions = _rows(path, "approval_decisions")
    assert len(decisions) == 1 and decisions[0][3] == "APPROVE"
    assert [row[4] for row in _rows(path, "approval_audit")] == ["AWAITING_APPROVAL"]


def test_replay_is_idempotent_and_rechecks_live_authority(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)
    authority = HostAuthority()
    first = _call(pending, path, authority)
    assert first.decision is not None

    replay = _call(pending, path, authority)

    assert replay.decision is not None
    assert replay.decision.callback_key == first.decision.callback_key
    assert replay.execution is not None and replay.execution.deduplicated is True
    assert len(_rows(path, "approval_decisions")) == 1
    assert [row[4] for row in _rows(path, "approval_audit")] == [
        "AWAITING_APPROVAL",
        "AWAITING_APPROVAL",
    ]

    authority.roles = ()
    denied = _call(pending, path, authority)
    assert denied.attempt.code == "DENIED" and denied.decision is None
    assert len(_rows(path, "approval_decisions")) == 1
    assert _rows(path, "approval_audit")[-1][4] == "DENIED"


def test_changed_payload_on_a_known_key_is_key_misuse(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)

    wrong_first = _call(pending, path, HostAuthority(), fingerprint="0" * 64)
    assert wrong_first.attempt.code == "DENIED"
    assert wrong_first.attempt.reason == "KEY_MISUSE"
    assert _rows(path, "approval_decisions") == []
    assert _rows(path, "approval_audit")[-1][4] == "DENIED"

    _call(pending, path, HostAuthority())
    flipped = _call(pending, path, HostAuthority(), kind="REJECT")
    assert flipped.attempt.reason == "KEY_MISUSE"
    assert flipped.decision is None
    assert [row[3] for row in _rows(path, "approval_decisions")] == ["APPROVE"]
    assert [row[7] for row in _rows(path, "request_ledger")] == ["AWAITING_APPROVAL"]


def test_outsider_and_wrong_tenant_never_claim_the_key(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)

    outsider = _call(pending, path, HostAuthority(roles=(), permissions=()))
    foreign = _call(
        pending,
        path,
        HostAuthority(),
        principal=Principal("dana", "B", frozenset({_APPROVE})),
    )
    for result in (outsider, foreign):
        assert result.attempt.code == "DENIED" and result.decision is None
    assert _rows(path, "approval_decisions") == []
    assert [row[7] for row in _rows(path, "request_ledger")] == ["AWAITING_APPROVAL"]

    accepted = _call(pending, path, HostAuthority())
    assert accepted.decision is not None


def test_live_role_permission_scope_and_tenant_are_all_checked(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)
    for authority in (
        HostAuthority(roles=()),
        HostAuthority(permissions=()),
        HostAuthority(scopes=("team-2",)),
        HostAuthority(tenant="B"),
    ):
        assert _call(pending, path, authority).attempt.code == "DENIED"
    assert _rows(path, "approval_decisions") == []


def test_self_approval_follows_the_declaration(tmp_path: Path) -> None:
    path = _database(tmp_path)
    forbidden = _pending(path)
    requester_as_approver = Principal("alice", _TENANT, frozenset({_APPROVE}))
    denied = _call(forbidden, path, HostAuthority(), principal=requester_as_approver)
    assert denied.attempt.code == "DENIED" and denied.decision is None

    allowed_path = _database(tmp_path, name="self.sqlite3")
    allowed = _pending(allowed_path, self_approval=True)
    result = _call(allowed, allowed_path, HostAuthority(), principal=requester_as_approver)
    assert result.attempt.code == "AWAITING_APPROVAL" and result.decision is not None
    assert result.decision.approval.self_approval is True


def test_expired_and_revoked_approvals_cannot_authorize_commit(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path, expires_at="2030-01-01T00:00:00Z")
    expired = _call(pending, path, HostAuthority(), now=datetime(2031, 1, 1, tzinfo=UTC))
    assert expired.attempt.code == "DENIED" and expired.decision is None

    approval = pending.execution and pending.execution.required_approval
    assert approval is not None
    revoked = HostAuthority(revoked={approval.approval_id})
    denied = _call(pending, path, revoked)
    assert denied.attempt.code == "DENIED" and denied.decision is None
    assert _rows(path, "approval_decisions") == []


def test_stale_approval_and_unknown_callback_do_not_change_pending(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)

    unknown = _call(pending, path, HostAuthority(), callback_key="EX-unknown:AP-unknown")
    malformed = _call(pending, path, HostAuthority(), callback_key="not-a-callback-key")
    for result in (unknown, malformed):
        assert result.attempt.code == "DENIED" and result.decision is None

    old = pending.execution and pending.execution.required_approval
    assert old is not None
    old_key = old.callback_key
    _replace_approval(path, pending)
    stale = _call(pending, path, HostAuthority(), callback_key=old_key)
    assert stale.attempt.code == "DENIED" and stale.decision is None
    assert _rows(path, "approval_decisions") == []


def _replace_approval(path: Path, pending: ActionResult) -> RequiredApproval:
    """Simulate a newer approval replacing the one the caller still holds."""
    assert pending.execution is not None
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT payload FROM request_ledger").fetchall()
        assert len(rows) == 1
        waiting = decode_awaiting(str(rows[0][0]))
        assert waiting is not None
        older = waiting.required_approval
        newer = RequiredApproval(
            "AP-replacement",
            older.role,
            older.tenant,
            older.scope,
            older.requester,
            older.expires_at,
            older.self_approval,
            older.intent_fingerprint,
            f"{waiting.execution_id}:AP-replacement",
            older.permission,
        )
        changed = AwaitingExecution(
            waiting.execution_id,
            waiting.action,
            waiting.requester,
            waiting.canonical_input,
            waiting.pinned_manifest,
            waiting.material_intent,
            newer,
            waiting.created_at,
        )
        connection.execute("UPDATE request_ledger SET payload = ?", (encode_awaiting(changed),))
        connection.commit()
    finally:
        connection.close()
    return newer


def test_valid_reject_ends_terminal_once_without_business_write(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)

    first = _call(pending, path, HostAuthority(), kind="REJECT", reason="budget withdrawn")
    assert first.attempt.code == "REJECTED"
    assert first.execution is not None and first.execution.status == "REJECTED"
    assert first.decision is not None and first.decision.decision == "REJECT"
    assert first.writes == ()
    assert [row[7] for row in _rows(path, "request_ledger")] == ["REJECTED"]
    assert _rows(path, "purchase_orders")[0][3] == "PENDING"
    assert _rows(path, "budgets")[0][4] == 0
    assert _rows(path, "outbox") == []

    replay = _call(pending, path, HostAuthority(), kind="REJECT", reason="budget withdrawn")
    assert replay.attempt.code == "REJECTED"
    assert replay.execution is not None and replay.execution.deduplicated is True
    assert len(_rows(path, "approval_decisions")) == 1
    assert [row[7] for row in _rows(path, "request_ledger")] == ["REJECTED"]

    reader = Principal(
        "alice", _TENANT, frozenset({_READ, _APPROVE, _RESERVE_PERMISSION, "execution.read"})
    )
    reconciled = reconcile(
        provider=_provider(path),
        principal=reader,
        action=_ROOT_KEY,
        request_key=_REQUEST_KEY,
    )
    assert reconciled.attempt.code == "REJECTED"
    assert reconciled.execution is not None and reconciled.execution.status == "REJECTED"

    replayed_invoke = _pending(path)
    assert replayed_invoke.attempt.code == "REJECTED"
    assert replayed_invoke.execution is not None
    assert replayed_invoke.execution.status == "REJECTED"
    assert replayed_invoke.writes == ()


def test_reject_cannot_be_flipped_to_approve_after_terminal(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)
    _call(pending, path, HostAuthority(), kind="REJECT", reason="budget withdrawn")

    flipped = _call(pending, path, HostAuthority(), reason="budget withdrawn")
    assert flipped.attempt.reason == "KEY_MISUSE" and flipped.decision is None
    assert [row[3] for row in _rows(path, "approval_decisions")] == ["REJECT"]
    assert [row[7] for row in _rows(path, "request_ledger")] == ["REJECTED"]


def test_provider_failure_returns_unknown_without_claim(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)
    result = _call(pending, path, HostAuthority(unavailable=True))
    assert result.attempt.code == "UNKNOWN" and result.decision is None
    assert _rows(path, "approval_decisions") == []


def test_decision_survives_a_fresh_provider_and_connection(tmp_path: Path) -> None:
    path = _database(tmp_path)
    pending = _pending(path)
    first = _call(pending, path, HostAuthority(), provider=_provider(path))
    assert first.decision is not None

    replay = _call(pending, path, HostAuthority(revision="policy-2"), provider=_provider(path))
    assert replay.decision is not None
    assert replay.decision.recorded_at == first.decision.recorded_at
    assert replay.decision.authority_revision == "policy-1"
    assert len(_rows(path, "approval_decisions")) == 1
