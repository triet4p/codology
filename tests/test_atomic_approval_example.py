"""End-to-end checks for the executable Procurement/Finance consumer example.

The tests drive the shipped consumer path (``query`` -> ``row.as_ref()`` ->
``invoke``) over a file-backed SQLite database and then read the same facts from
independent connections. They cover one commit, read and invoke refusals, split
binding, rollback after a partial write, budget contention and replay.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from codology import (
    ApplyResult,
    CommitOutcomeUnknown,
    DefinitionKey,
    GuardedWrite,
    LedgerEntry,
    NoSharedTransaction,
    OrderBy,
    Principal,
    QueryRow,
    ReadDenied,
    ReadGrant,
    RequestScope,
    SessionPlan,
    UnitOfWork,
    UnsupportedSecureQuery,
    VersionedRef,
    bind_action,
    query,
)
from codology.adapter import SQLiteProvider
from codology.engine import ActionResult, ResourceSpec, ScopedEngineProvider, reconcile
from codology.ledger import LedgerUnitOfWork
from codology.money import MinorMoney
from examples.atomic_approval import consumer
from examples.atomic_approval.__main__ import main
from examples.atomic_approval.database import build_database
from examples.atomic_approval.wiring import (
    APPROVE_KEY,
    BUDGET_KEY,
    ORDER_KEY,
    RESERVE_KEY,
    SESSION,
    TENANT_A,
    alice,
    bob,
    bound_approval,
    grants_for,
    linked_graph,
    outsider,
    published_snapshot,
    split_deployment,
    sqlite_provider,
)
from examples.procurement_finance import runtime

AMOUNT = MinorMoney.from_decimal(Decimal("40000"), "USD")
CONTENDED = MinorMoney.from_decimal(Decimal("80000"), "USD")
REQUEST_KEY = "tenant-a:alice:approve:PO-1:001"


def _refs(
    provider: SQLiteProvider,
    principal: Principal,
    grants: Mapping[DefinitionKey, ReadGrant],
    *,
    order_id: str = "PO-1",
    budget_id: str = "B-1",
) -> tuple[VersionedRef[runtime.PurchaseOrder], VersionedRef[runtime.Budget]]:
    page = consumer.find_orders(provider, principal, grants)
    order = next(row for row in page.rows if row.key == order_id)
    budget = consumer.find_budget(provider, principal, grants, budget_id)
    return order.as_ref(), budget.as_ref()


def _approve(
    provider: ScopedEngineProvider,
    principal: Principal,
    order: VersionedRef[runtime.PurchaseOrder],
    budget: VersionedRef[runtime.Budget],
    *,
    request_key: str = REQUEST_KEY,
    amount: MinorMoney = AMOUNT,
    reason: str = "approved after budget check",
) -> ActionResult:
    grants = grants_for(principal)
    return consumer.approve(
        provider=provider,
        linked=linked_graph(),
        bound=bound_approval(),
        principal=principal,
        grants=grants,
        order=order,
        budget=budget,
        reason=reason,
        amount=amount,
        request_key=request_key,
    )


def _order(path: Path, key: str = "PO-1") -> tuple[str, int | None, int]:
    connection = sqlite3.connect(path)
    try:
        found = connection.execute(
            "SELECT status, approved_amount, version FROM purchase_orders WHERE id = ?",
            (key,),
        ).fetchone()
    finally:
        connection.close()
    assert found is not None
    return str(found[0]), None if found[1] is None else int(found[1]), int(found[2])


def _budget(path: Path, key: str = "B-1") -> tuple[int, int, int]:
    connection = sqlite3.connect(path)
    try:
        found = connection.execute(
            "SELECT ceiling, reserved, version FROM budgets WHERE id = ?",
            (key,),
        ).fetchone()
    finally:
        connection.close()
    assert found is not None
    return int(found[0]), int(found[1]), int(found[2])


def _ledger(path: Path) -> tuple[tuple[str, ...], ...]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "SELECT tenant, principal, action, request_key, intent_fingerprint, "
            "execution_id, status FROM request_ledger ORDER BY principal, request_key"
        ).fetchall()
    finally:
        connection.close()
    return tuple(tuple(str(value) for value in row) for row in rows)


def _state(path: Path) -> tuple[tuple[str, int | None, int], tuple[int, int, int]]:
    return _order(path), _budget(path)


def _assert_write_lock_released(path: Path) -> None:
    connection = sqlite3.connect(path, timeout=1.0)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()
    finally:
        connection.close()


def test_consumer_commits_the_order_and_budget_in_one_transaction(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    provider = sqlite_provider(path)
    principal = alice()
    grants = grants_for(principal)

    pending = consumer.find_orders(provider, principal, grants)
    assert pending.count == 2
    assert {row.key for row in pending.rows} == {"PO-1", "PO-2"}
    order, budget = _refs(provider, principal, grants)

    result = _approve(provider, principal, order, budget)

    assert result.attempt.code == "COMMITTED"
    assert result.execution is not None
    assert result.execution.children == (RESERVE_KEY,)
    assert {write.resource for write in result.writes} == {ORDER_KEY.identity, BUDGET_KEY.identity}
    assert len({write.transaction for write in result.writes}) == 1
    assert all(write.rowcount == 1 for write in result.writes)

    assert _state(path) == (("APPROVED", 40_000, 2), (100_000, 40_000, 2))
    rows = _ledger(path)
    assert len(rows) == 1
    assert rows[0][:4] == (TENANT_A, "alice", APPROVE_KEY.identity, REQUEST_KEY)
    assert rows[0][4] == result.attempt.intent_fingerprint
    assert rows[0][5] == result.execution.execution_id
    assert rows[0][6] == "COMMITTED"

    approved = consumer.find_orders(provider, principal, grants, status="APPROVED")
    assert [row.key for row in approved.rows] == ["PO-1"]


def test_read_denial_and_scope_policy_never_leak_rows(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    provider = sqlite_provider(path)
    principal = alice()
    grants = grants_for(principal)

    with pytest.raises(ReadDenied):
        consumer.find_orders(provider, outsider(), grants_for(outsider()))

    page = consumer.find_orders(provider, principal, grants)
    assert page.count == 2
    assert {row.key for row in page.rows} == {"PO-1", "PO-2"}

    limited = consumer.find_orders(provider, principal, grants, limit=1)
    assert limited.count == 2
    assert len(limited.rows) == 1
    assert limited.next_cursor is not None

    narrow = consumer.find_orders(provider, principal, grants_for(principal, scopes=("team-2",)))
    assert narrow.rows == ()
    assert narrow.count == 0

    with pytest.raises(UnsupportedSecureQuery):
        query(
            provider=provider,
            principal=principal,
            grant=grants[ORDER_KEY],
            from_=ORDER_KEY,
            target=runtime.PurchaseOrder,
            order=OrderBy("created_at"),
            traverse="budget",
        )


def test_invoke_denial_changes_nothing_and_stores_no_record(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    provider = sqlite_provider(path)
    principal = alice()
    order, budget = _refs(provider, principal, grants_for(principal))
    before = (_state(path), _ledger(path))
    readable = consumer.find_orders(provider, bob(), grants_for(bob()))
    assert readable.count == 2

    denied = _approve(
        provider,
        bob(),
        order,
        budget,
        request_key="tenant-a:bob:approve:PO-1:001",
    )

    assert denied.attempt.code == "DENIED"
    assert denied.execution is None
    assert denied.writes == ()
    assert (_state(path), _ledger(path)) == before


def test_split_binding_is_rejected_before_any_business_write(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")

    with pytest.raises(NoSharedTransaction):
        bind_action(published_snapshot(), split_deployment(), APPROVE_KEY)

    assert _state(path) == (("PENDING_APPROVAL", None, 1), (100_000, 0, 1))
    assert _ledger(path) == ()


class _FailingUnit:
    """Let the first guarded write through, then fail before commit."""

    def __init__(self, inner: UnitOfWork) -> None:
        self._inner = inner
        self._applied = 0

    @property
    def transaction(self) -> str:
        return self._inner.transaction

    def apply(self, write: GuardedWrite) -> ApplyResult:
        if self._applied:
            raise RuntimeError("response lost after the first write")
        self._applied += 1
        return self._inner.apply(write)

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None:
        return cast(LedgerUnitOfWork, self._inner).lookup(scope, request_key)

    def record(self, entry: LedgerEntry) -> None:
        cast(LedgerUnitOfWork, self._inner).record(entry)

    def commit(self) -> None:
        raise AssertionError("commit must not be reached")

    def rollback(self) -> None:
        self._inner.rollback()

    def close(self) -> None:
        self._inner.close()


class _FailingProvider:
    """Adapter wrapper that opens the real session and fails mid-transaction."""

    def __init__(self, inner: SQLiteProvider) -> None:
        self._inner = inner

    @property
    def resources(self) -> Mapping[str, ResourceSpec]:
        return self._inner.resources

    def resolve(self, ref: VersionedRef[object], grant: ReadGrant) -> QueryRow[object] | None:
        return self._inner.resolve(ref, grant)

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None:
        return self._inner.lookup(scope, request_key)

    def begin(self, plan: SessionPlan) -> _FailingUnit:
        return _FailingUnit(self._inner.begin(plan))


def test_failure_after_first_write_rolls_back_state_and_ledger(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    provider = sqlite_provider(path)
    principal = alice()
    order, budget = _refs(provider, principal, grants_for(principal))
    before = (_state(path), _ledger(path))

    with pytest.raises(RuntimeError, match="response lost"):
        _approve(_FailingProvider(provider), principal, order, budget)

    assert (_state(path), _ledger(path)) == before
    assert _ledger(path) == ()


class _LostCommitAckUnit:
    """Commit for real, then lose the acknowledgement so the outcome is unknown."""

    def __init__(self, inner: UnitOfWork) -> None:
        self._inner = inner

    @property
    def transaction(self) -> str:
        return self._inner.transaction

    def apply(self, write: GuardedWrite) -> ApplyResult:
        return self._inner.apply(write)

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None:
        return cast(LedgerUnitOfWork, self._inner).lookup(scope, request_key)

    def record(self, entry: LedgerEntry) -> None:
        cast(LedgerUnitOfWork, self._inner).record(entry)

    def commit(self) -> None:
        self._inner.commit()
        raise CommitOutcomeUnknown("the commit acknowledgement was lost")

    def rollback(self) -> None:
        self._inner.rollback()

    def close(self) -> None:
        self._inner.close()


class _LostCommitAckProvider:
    def __init__(self, inner: ScopedEngineProvider) -> None:
        self._inner = inner

    @property
    def resources(self) -> Mapping[str, ResourceSpec]:
        return self._inner.resources

    def resolve(self, ref: VersionedRef[object], grant: ReadGrant) -> QueryRow[object] | None:
        return self._inner.resolve(ref, grant)

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None:
        return self._inner.lookup(scope, request_key)

    def begin(self, plan: SessionPlan) -> UnitOfWork:
        return _LostCommitAckUnit(self._inner.begin(plan))


def test_provider_session_mismatch_returns_unknown_without_writes(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    provider = sqlite_provider(path)
    principal = alice()
    order, budget = _refs(provider, principal, grants_for(principal))
    before = (_state(path), _ledger(path))
    mismatched = SQLiteProvider(
        path, "sqlite:not-the-bound-session", tuple(provider.resources.values())
    )

    result = _approve(mismatched, principal, order, budget)

    assert result.attempt.code == "UNKNOWN"
    assert result.attempt.detail is not None
    assert result.execution is None
    assert result.writes == ()
    assert (_state(path), _ledger(path)) == before


def test_locked_write_session_returns_unknown_without_waiting(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    provider = sqlite_provider(path)
    principal = alice()
    order, budget = _refs(provider, principal, grants_for(principal))
    before = (_state(path), _ledger(path))
    contended = SQLiteProvider(path, SESSION, tuple(provider.resources.values()), timeout=0.05)
    holder = sqlite3.connect(path, isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        result = _approve(contended, principal, order, budget)
        elapsed = time.monotonic() - started
    finally:
        holder.rollback()
        holder.close()

    assert result.attempt.code == "UNKNOWN"
    assert result.execution is None
    assert result.writes == ()
    assert elapsed < 5.0
    assert (_state(path), _ledger(path)) == before


def test_unconfirmed_commit_returns_unknown_without_claiming_rollback(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    provider = sqlite_provider(path)
    principal = alice()
    order, budget = _refs(provider, principal, grants_for(principal))

    result = _approve(_LostCommitAckProvider(provider), principal, order, budget)

    assert result.attempt.code == "UNKNOWN"
    assert result.execution is None
    assert result.writes == ()
    # The commit was durable even though its acknowledgement was lost.
    assert _state(path) == (("APPROVED", 40_000, 2), (100_000, 40_000, 2))
    stored = reconcile(
        provider=sqlite_provider(path),
        principal=principal,
        action=APPROVE_KEY,
        request_key=REQUEST_KEY,
    )
    assert stored.execution is not None
    assert stored.execution.deduplicated is True


def test_two_orders_contending_for_one_budget_commit_exactly_once(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    principal = alice()
    grants = grants_for(principal)
    barrier = threading.Barrier(2)
    results: dict[str, ActionResult] = {}
    errors: dict[str, Exception] = {}

    def run(name: str, order_id: str) -> None:
        try:
            provider = sqlite_provider(path)
            order, budget = _refs(provider, principal, grants, order_id=order_id)
            barrier.wait(timeout=10)
            results[name] = _approve(
                provider,
                principal,
                order,
                budget,
                amount=CONTENDED,
                request_key=f"tenant-a:alice:approve:{order_id}:001",
            )
        except Exception as exc:  # surfaced after the threads join
            errors[name] = exc

    threads = [
        threading.Thread(target=run, args=("a", "PO-1")),
        threading.Thread(target=run, args=("b", "PO-2")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()

    assert errors == {}
    committed = [result for result in results.values() if result.attempt.code == "COMMITTED"]
    assert len(committed) == 1
    commit = committed[0]
    assert commit.execution is not None
    assert {write.resource for write in commit.writes} == {ORDER_KEY.identity, BUDGET_KEY.identity}
    assert len({write.transaction for write in commit.writes}) == 1

    loser = next(result for result in results.values() if result is not commit)
    assert loser.attempt.code in {"REJECTED", "StalePlan"}
    assert loser.writes == ()

    ceiling, reserved, version = _budget(path)
    assert reserved == CONTENDED.minor <= ceiling
    assert version == 2
    approved = [key for key in ("PO-1", "PO-2") if _order(path, key)[0] == "APPROVED"]
    assert len(approved) == 1
    assert len(_ledger(path)) == 1


def test_replay_and_reconcile_after_lost_response_write_nothing(tmp_path: Path) -> None:
    path = build_database(tmp_path / "approval.sqlite3")
    provider = sqlite_provider(path)
    principal = alice()
    order, budget = _refs(provider, principal, grants_for(principal))

    first = _approve(provider, principal, order, budget)
    assert first.attempt.code == "COMMITTED"
    assert first.execution is not None
    after_first = (_state(path), _ledger(path))

    stored = reconcile(
        provider=sqlite_provider(path),
        principal=principal,
        action=APPROVE_KEY,
        request_key=REQUEST_KEY,
    )
    assert stored.execution is not None
    assert stored.execution.execution_id == first.execution.execution_id
    assert stored.execution.deduplicated is True

    replay = _approve(sqlite_provider(path), principal, order, budget)
    assert replay.attempt.code == "COMMITTED"
    assert replay.execution is not None
    assert replay.execution.execution_id == first.execution.execution_id
    assert replay.execution.deduplicated is True
    assert replay.writes == ()
    assert (_state(path), _ledger(path)) == after_first
    _assert_write_lock_released(path)

    misuse = _approve(sqlite_provider(path), principal, order, budget, reason="different reason")
    assert misuse.attempt.code == "DENIED"
    assert misuse.attempt.reason == "KEY_MISUSE"
    assert misuse.execution is None
    assert (_state(path), _ledger(path)) == after_first

    denied_replay = _approve(sqlite_provider(path), bob(), order, budget)
    assert denied_replay.attempt.code == "DENIED"
    assert denied_replay.execution is None
    assert (_state(path), _ledger(path)) == after_first


def test_cli_runs_the_documented_consumer_flow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "cli.sqlite3"

    assert main(path) == 0

    output = capsys.readouterr().out
    for expected in (
        "code=COMMITTED",
        "children=finance.reserve_budget@1.0.0",
        "shared_transaction=True",
        "deduplicated=True",
        "PENDING_APPROVAL count=1; APPROVED count=1",
        "read without a live grant: ReadDenied",
        "query outside the granted scope: rows=0 count=0",
        "invoke without approve: DENIED (execution=None)",
        "split binding: NoSharedTransaction",
        "ALL CHECKS PASSED",
    ):
        assert expected in output
    assert _state(path) == (("APPROVED", 40_000, 2), (100_000, 40_000, 2))
    assert len(_ledger(path)) == 1
