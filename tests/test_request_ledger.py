"""Durable request ledger: one commit with the writes, replay and scoped reads."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from codology import (
    EXECUTION_READ_PERMISSION,
    Capability,
    Comparison,
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
from codology.declarations import Action, CommitRequirement, Module, ObjectRef
from codology.engine import ActionResult, HandlerCtx, ScopedEngineProvider, invoke, reconcile
from codology.linking import LinkedDeclarations
from codology.money import MinorMoney
from examples.procurement_finance import runtime

_ORDER = "procurement.purchase_order"
_BUDGET = "finance.budget"
_ROOT = "procurement.approve_purchase_order"
_RESERVE = "finance.reserve_budget"
_ORDER_KEY = DefinitionKey(_ORDER, "1.0.0")
_BUDGET_KEY = DefinitionKey(_BUDGET, "1.0.0")
_ROOT_KEY = DefinitionKey(_ROOT, "1.1.0")
_SESSION = "sqlite:main"
_TENANT = "A"
_SCOPE = "team1"
_APPROVE = "purchase_order.approve"
_RESERVE_PERMISSION = "budget.reserve"
_READ = "purchase_order.read"
_AMOUNT = MinorMoney.from_decimal(Decimal("40000"), "USD")

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
"""


class _HandlerCounts:
    def __init__(self) -> None:
        self.root = 0
        self.child = 0
        self._lock = threading.Lock()

    def bump(self, name: str) -> None:
        with self._lock:
            if name == "root":
                self.root += 1
            else:
                self.child += 1


_COUNTS = _HandlerCounts()


class CountingApprove(Action):
    """Tier-2 root with the example's contract, counting real handler runs."""

    identity = _ROOT
    version = "1.1.0"
    order: ObjectRef[runtime.PurchaseOrder]
    budget: ObjectRef[runtime.Budget]
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
        budget: runtime.Budget,
        reason: str,
        amount: MinorMoney,
    ) -> None:
        _COUNTS.bump("root")
        ctx.require(order.status == "PENDING_APPROVAL", reason="order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")
        ctx.call(
            _RESERVE,
            budget=budget,
            amount=amount,
            expectedVersion=budget.version,
        )
        ctx.uow.register_mutation(
            order,
            status="APPROVED",
            approved_amount=amount.minor,
            expectedVersion=order.version,
        )


class CountingReserve(Action):
    """Finance-owned child counting its own handler runs."""

    identity = _RESERVE
    version = "1.0.0"
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
        _COUNTS.bump("child")
        ctx.require(amount.minor > 0, reason="amount_not_positive")
        available = budget.ceiling - budget.reserved
        ctx.require(available >= amount.minor, reason="budget_insufficient")
        ctx.uow.register_mutation(
            budget,
            reserved=budget.reserved + amount.minor,
            expectedVersion=expectedVersion,
        )


class LedgerProcurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (runtime.PurchaseOrder, CountingApprove)


class LedgerFinance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (runtime.Budget, CountingReserve)


@pytest.fixture(autouse=True)
def counts() -> _HandlerCounts:
    """Reset handler counters for each test."""
    _COUNTS.root = 0
    _COUNTS.child = 0
    return _COUNTS


class _FailingUnit:
    """Lose the response after the first guarded write but before commit."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.applied = 0

    @property
    def transaction(self) -> str:
        return self._inner.transaction

    def apply(self, write: Any) -> Any:
        if self.applied:
            raise RuntimeError("response lost before commit")
        self.applied += 1
        return self._inner.apply(write)

    def lookup(self, scope: Any, request_key: str) -> Any:
        return self._inner.lookup(scope, request_key)

    def record(self, entry: Any) -> None:
        self._inner.record(entry)

    def commit(self) -> None:
        raise AssertionError("commit must not be reached")

    def rollback(self) -> None:
        self._inner.rollback()

    def close(self) -> None:
        self._inner.close()


class _FailingProvider:
    def __init__(self, inner: SQLiteProvider) -> None:
        self._inner = inner

    @property
    def resources(self) -> Mapping[str, Any]:
        return self._inner.resources

    def resolve(self, ref: VersionedRef[object], grant: ReadGrant) -> Any:
        return self._inner.resolve(ref, grant)

    def lookup(self, scope: Any, request_key: str) -> Any:
        return self._inner.lookup(scope, request_key)

    def begin(self, plan: Any) -> _FailingUnit:
        return _FailingUnit(self._inner.begin(plan))


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "ledger.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.executemany(
            "INSERT INTO purchase_orders "
            "(id, tenant, scope, status, approved_amount, created_at, version) "
            "VALUES (?, ?, ?, 'PENDING_APPROVAL', NULL, 1, 1)",
            (("PO-1", _TENANT, _SCOPE), ("PO-2", _TENANT, _SCOPE)),
        )
        connection.execute(
            "INSERT INTO budgets (id, tenant, scope, ceiling, reserved, version) "
            "VALUES ('B-1', 'A', 'team1', 100000, 0, 1)"
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


def _linked() -> LinkedDeclarations:
    return link(
        load(
            ModuleDeclarations(LedgerProcurement, (runtime.PurchaseOrder, CountingApprove)),
            ModuleDeclarations(LedgerFinance, (runtime.Budget, CountingReserve)),
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


def _principal(*permissions: str, identity: str = "alice", tenant: str = _TENANT) -> Principal:
    return Principal(identity, tenant, frozenset({_READ, *permissions}))


def _grant(principal: Principal, definition: DefinitionKey) -> ReadGrant:
    return ReadGrant(principal.identity, definition, principal.tenant, (_SCOPE,), _READ)


def _parameters(
    path: Path, *, order_id: str = "PO-1", reason: str = "approved after budget check"
) -> dict[str, object]:
    provider = _provider(path)
    principal = _principal(_APPROVE, _RESERVE_PERMISSION)

    def ref(definition: DefinitionKey, target: type[object]) -> VersionedRef[object]:
        predicate = (
            Comparison("status", "==", "PENDING_APPROVAL") if definition == _ORDER_KEY else None
        )
        page = query(
            provider=provider,
            principal=principal,
            grant=_grant(principal, definition),
            from_=definition,
            target=target,
            order=OrderBy("created_at") if definition == _ORDER_KEY else OrderBy("id"),
            predicate=predicate,
            limit=10,
        )
        matching = [
            row
            for row in page.rows
            if row.key == ("B-1" if definition == _BUDGET_KEY else order_id)
        ]
        assert len(matching) == 1
        return matching[0].as_ref()

    return {
        "order": ref(_ORDER_KEY, runtime.PurchaseOrder),
        "budget": ref(_BUDGET_KEY, runtime.Budget),
        "reason": reason,
        "amount": _AMOUNT,
    }


def _invoke(
    path: Path,
    *,
    request_key: str | None = None,
    intent_fingerprint: str | None = None,
    principal: Principal | None = None,
    parameters: Mapping[str, object] | None = None,
    provider: ScopedEngineProvider | None = None,
) -> ActionResult:
    graph = _linked()
    caller = principal if principal is not None else _principal(_APPROVE, _RESERVE_PERMISSION)
    return invoke(
        linked=graph,
        action=_ROOT_KEY,
        bound=bind_action(snapshot(graph), _deployment(), _ROOT_KEY),
        provider=provider if provider is not None else _provider(path),
        principal=caller,
        grants={_ORDER_KEY: _grant(caller, _ORDER_KEY), _BUDGET_KEY: _grant(caller, _BUDGET_KEY)},
        parameters=parameters if parameters is not None else _parameters(path),
        request_key=request_key,
        intent_fingerprint=intent_fingerprint,
    )


def _ledger(path: Path) -> tuple[tuple[str, ...], ...]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT tenant, principal, action, request_key, intent_fingerprint, "
            "execution_id FROM request_ledger ORDER BY principal, request_key"
        ).fetchall()
        return tuple(tuple(str(value) for value in row) for row in rows)
    finally:
        connection.close()


def _execution_id(result: ActionResult) -> str:
    assert result.execution is not None
    return result.execution.execution_id


def _state(path: Path) -> tuple[tuple[str, int | None, int], tuple[int, int, int]]:
    connection = sqlite3.connect(path)
    try:
        order = connection.execute(
            "SELECT status, approved_amount, version FROM purchase_orders WHERE id = 'PO-1'"
        ).fetchone()
        budget = connection.execute(
            "SELECT ceiling, reserved, version FROM budgets WHERE id = 'B-1'"
        ).fetchone()
        assert order is not None and budget is not None
        return (
            (str(order[0]), None if order[1] is None else int(order[1]), int(order[2])),
            (int(budget[0]), int(budget[1]), int(budget[2])),
        )
    finally:
        connection.close()


def _reader(*, identity: str = "alice", tenant: str = _TENANT) -> Principal:
    return _principal(EXECUTION_READ_PERMISSION, identity=identity, tenant=tenant)


def test_commit_persists_ledger_with_both_writes_in_one_transaction(
    tmp_path: Path, counts: _HandlerCounts
) -> None:
    path = _database(tmp_path)
    result = _invoke(path, request_key="req-atomic")

    assert result.attempt.code == "COMMITTED"
    assert result.attempt.request_key == "req-atomic"
    assert result.attempt.intent_fingerprint is not None
    assert result.execution is not None
    assert len(result.writes) == 2
    assert {write.resource for write in result.writes} == {_ORDER, _BUDGET}
    assert len({write.transaction for write in result.writes}) == 1
    assert all(write.rowcount == 1 for write in result.writes)
    assert _state(path) == (("APPROVED", 40_000, 2), (100_000, 40_000, 2))
    rows = _ledger(path)
    assert len(rows) == 1
    assert rows[0] == (
        _TENANT,
        "alice",
        _ROOT,
        "req-atomic",
        result.attempt.intent_fingerprint,
        _execution_id(result),
    )
    assert counts.root == 1 and counts.child == 1


def test_failure_after_first_write_leaves_no_committed_record(tmp_path: Path) -> None:
    path = _database(tmp_path)
    before = _state(path)
    failing = _FailingProvider(_provider(path))
    with pytest.raises(RuntimeError, match="response lost"):
        _invoke(path, request_key="req-rollback", provider=failing)

    assert _state(path) == before
    connection = sqlite3.connect(path)
    try:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM request_ledger WHERE status = 'COMMITTED'"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_business_rejection_writes_no_ledger_row(tmp_path: Path) -> None:
    path = _database(tmp_path)
    parameters = _parameters(path)
    parameters["amount"] = MinorMoney.from_decimal(Decimal("120000"), "USD")
    result = _invoke(path, request_key="req-rejected", parameters=parameters)

    assert result.attempt.code == "REJECTED"
    assert result.attempt.reason is None
    assert _ledger(path) == ()
    assert _state(path)[0] == ("PENDING_APPROVAL", None, 1)


def test_reopened_connection_replays_without_running_handler_again(
    tmp_path: Path, counts: _HandlerCounts
) -> None:
    path = _database(tmp_path)
    parameters = _parameters(path)
    first = _invoke(path, request_key="req-lost", parameters=parameters)
    assert first.attempt.code == "COMMITTED"

    # The first response is discarded; only the durable record survives.
    reopened = _provider(path)
    stored = reconcile(
        provider=reopened,
        principal=_reader(),
        action=_ROOT_KEY,
        request_key="req-lost",
    )
    assert stored.attempt.code == "COMMITTED"
    assert stored.execution is not None
    assert _execution_id(stored) == _execution_id(first)
    assert stored.execution.deduplicated is True

    replayed = _invoke(path, request_key="req-lost", parameters=parameters)
    assert replayed.attempt.code == "COMMITTED"
    assert replayed.execution is not None
    assert replayed.execution.deduplicated is True
    assert _execution_id(replayed) == _execution_id(first)
    assert replayed.writes == ()
    assert counts.root == 1 and counts.child == 1
    assert _state(path) == (("APPROVED", 40_000, 2), (100_000, 40_000, 2))


def test_caller_fingerprint_mismatch_is_key_misuse(tmp_path: Path) -> None:
    path = _database(tmp_path)
    parameters = _parameters(path)
    first = _invoke(
        path,
        request_key="req-key",
        intent_fingerprint="not-the-canonical-intent",
        parameters=parameters,
    )
    assert first.attempt.code == "DENIED"
    assert first.attempt.reason == "KEY_MISUSE"
    assert _ledger(path) == ()

    committed = _invoke(path, request_key="req-key", parameters=parameters)
    assert committed.attempt.code == "COMMITTED"
    different = dict(parameters)
    different["reason"] = "different reason"
    replay = _invoke(path, request_key="req-key", parameters=different)
    assert replay.attempt.code == "DENIED"
    assert replay.attempt.reason == "KEY_MISUSE"
    assert len(_ledger(path)) == 1
    assert _state(path) == (("APPROVED", 40_000, 2), (100_000, 40_000, 2))


def test_concurrent_same_key_commits_once(tmp_path: Path, counts: _HandlerCounts) -> None:
    path = _database(tmp_path)
    barrier = threading.Barrier(2)
    results: dict[str, ActionResult] = {}

    def run(name: str) -> None:
        barrier.wait(timeout=10)
        results[name] = _invoke(path, request_key="req-race")

    threads = [threading.Thread(target=run, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert len(results) == 2
    assert sorted(result.attempt.code for result in results.values()) == [
        "COMMITTED",
        "COMMITTED",
    ]
    assert (
        sum(
            1
            for result in results.values()
            if result.execution is not None and result.execution.deduplicated
        )
        == 1
    )
    assert counts.root == 1 and counts.child == 1
    assert len(_ledger(path)) == 1
    assert _state(path) == (("APPROVED", 40_000, 2), (100_000, 40_000, 2))


def test_keys_are_isolated_by_principal_tenant_and_action(tmp_path: Path) -> None:
    path = _database(tmp_path)
    alice = _principal(_APPROVE, _RESERVE_PERMISSION)
    bob = _principal(_APPROVE, _RESERVE_PERMISSION, identity="bob")
    first = _invoke(path, request_key="shared-key", principal=alice)
    second = _invoke(
        path,
        request_key="shared-key",
        principal=bob,
        parameters=_parameters(path, order_id="PO-2"),
    )
    assert first.attempt.code == "COMMITTED" and second.attempt.code == "COMMITTED"

    rows = _ledger(path)
    assert len(rows) == 2
    assert {row[1] for row in rows} == {"alice", "bob"}

    alice_view = reconcile(
        provider=_provider(path),
        principal=_reader(),
        action=_ROOT_KEY,
        request_key="shared-key",
    )
    bob_view = reconcile(
        provider=_provider(path),
        principal=_reader(identity="bob"),
        action=_ROOT_KEY,
        request_key="shared-key",
    )
    assert alice_view.execution is not None and bob_view.execution is not None
    assert _execution_id(alice_view) == _execution_id(first)
    assert _execution_id(bob_view) == _execution_id(second)

    other_tenant = reconcile(
        provider=_provider(path),
        principal=_principal(EXECUTION_READ_PERMISSION, tenant="B"),
        action=_ROOT_KEY,
        request_key="shared-key",
    )
    assert other_tenant.attempt.code == "UNKNOWN"
    other_action = reconcile(
        provider=_provider(path),
        principal=_reader(),
        action=DefinitionKey("finance.reserve_budget", "1.0.0"),
        request_key="shared-key",
    )
    assert other_action.attempt.code == "UNKNOWN"


def test_lookup_needs_read_authority_and_replay_needs_invoke_authority(
    tmp_path: Path, counts: _HandlerCounts
) -> None:
    path = _database(tmp_path)
    parameters = _parameters(path)
    committed = _invoke(path, request_key="req-authority", parameters=parameters)
    assert committed.attempt.code == "COMMITTED"

    denied_read = reconcile(
        provider=_provider(path),
        principal=_principal(),
        action=_ROOT_KEY,
        request_key="req-authority",
    )
    assert denied_read.attempt.code == "DENIED"

    replay = _invoke(
        path,
        request_key="req-authority",
        principal=_principal(_READ),
        parameters=parameters,
    )
    assert replay.attempt.code == "DENIED"
    assert replay.execution is None
    assert counts.root == 1 and counts.child == 1
    assert _state(path) == (("APPROVED", 40_000, 2), (100_000, 40_000, 2))


def test_untrusted_record_is_unknown_and_never_reinvokes(
    tmp_path: Path, counts: _HandlerCounts
) -> None:
    path = _database(tmp_path)
    unknown = reconcile(
        provider=_provider(path),
        principal=_reader(),
        action=_ROOT_KEY,
        request_key="never-committed",
    )
    assert unknown.attempt.code == "UNKNOWN"
    assert unknown.execution is None
    assert counts.root == 0 and counts.child == 0
    assert _ledger(path) == ()


def test_denied_attempt_never_enters_the_execution_record(tmp_path: Path) -> None:
    path = _database(tmp_path)
    denied = _invoke(path, request_key="req-denied", principal=_principal(_RESERVE_PERMISSION))
    assert denied.attempt.code == "DENIED"
    assert denied.execution is None
    assert _ledger(path) == ()
    assert _state(path)[0] == ("PENDING_APPROVAL", None, 1)
