"""Physical transaction and guarded-write behavior on the SQLite adapter."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from codology import (
    Capability,
    DefinitionKey,
    Deployment,
    Enlistment,
    ModuleDeclarations,
    Provider,
    SessionPlan,
    bind_action,
    link,
    load,
    snapshot,
)
from codology.adapter import CurrencyMismatch, ResourceBinding, SQLiteProvider, SQLiteUnitOfWork
from codology.declarations import Action, CommitRequirement, Module, ObjectRef, ObjectType
from codology.money import MinorMoney
from codology.ports import (
    ApplyResult,
    Assignment,
    Condition,
    GuardedWrite,
    SessionMismatch,
    StalePlan,
    TransactionProvider,
    UnitOfWork,
)
from codology.uow import UnboundWriteAttempt, commit_guarded_writes


class Budget(ObjectType):
    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"

    balance: int


class PurchaseOrder(ObjectType):
    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"

    status: str
    approved_amount: int


class ReserveBudget(Action):
    identity = "finance.reserve_budget"
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: int

    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget, amount: int) -> None:
        raise AssertionError("runtime tests must not execute declaration handlers")


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
        raise AssertionError("runtime tests must not execute declaration handlers")


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApproveOrder)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


_BUDGET = "finance.budget"
_ORDER = "procurement.purchase_order"
_BUDGET_ID = "B-001"
_SESSION = "sqlite:main"
_CURRENCY = "VND"
_CAPABILITIES = frozenset({Capability.ATOMIC_TRANSACTION})

_SCHEMA = """
CREATE TABLE budgets (
    id TEXT PRIMARY KEY,
    balance INTEGER NOT NULL CHECK (balance >= 0),
    version INTEGER NOT NULL
);
CREATE TABLE purchase_orders (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    approved_amount INTEGER,
    version INTEGER NOT NULL
);
"""


def _plan() -> SessionPlan:
    published = snapshot(
        link(
            load(
                ModuleDeclarations(Procurement, (PurchaseOrder, ApproveOrder)),
                ModuleDeclarations(Finance, (Budget, ReserveBudget)),
            )
        )
    )
    deployment = Deployment(
        providers=(Provider("orders-db", "sqlite", _CAPABILITIES),),
        enlistments=(
            Enlistment(_ORDER, "orders-db", _SESSION),
            Enlistment(_BUDGET, "orders-db", _SESSION),
        ),
    )
    bound = bind_action(
        published,
        deployment,
        DefinitionKey("procurement.approve_purchase_order", "1.1.0"),
    )
    assert bound.session is not None
    return bound.session


def _database(
    tmp_path: Path,
    *,
    balance: int = 100_000,
    orders: tuple[tuple[str, str], ...] = (("PO-A", "PENDING_APPROVAL"),),
) -> Path:
    path = tmp_path / "orders.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.execute(
            "INSERT INTO budgets (id, balance, version) VALUES (?, ?, 1)",
            (_BUDGET_ID, balance),
        )
        connection.executemany(
            "INSERT INTO purchase_orders (id, status, approved_amount, version) "
            "VALUES (?, ?, NULL, 1)",
            orders,
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
            ResourceBinding(_BUDGET, "1.0.0", "budgets", ("balance",), currency=_CURRENCY),
            ResourceBinding(
                _ORDER,
                "1.0.0",
                "purchase_orders",
                ("status", "approved_amount"),
                currency=_CURRENCY,
            ),
        ),
    )


def _amount(value: str = "40000") -> MinorMoney:
    return MinorMoney.from_decimal(Decimal(value), _CURRENCY)


def _budget_write(
    amount: MinorMoney | None = None,
    *,
    version: int = 1,
    currency: str = _CURRENCY,
) -> GuardedWrite:
    value = _amount() if amount is None else amount
    if currency != _CURRENCY:
        value = MinorMoney(currency, value.minor)
    return GuardedWrite(
        _BUDGET,
        _BUDGET_ID,
        version,
        (Assignment("balance", "add", -value),),
        (Condition("balance", ">=", value),),
    )


def _order_write(
    order_id: str = "PO-A",
    *,
    version: int = 1,
    amount: MinorMoney | None = None,
) -> GuardedWrite:
    return GuardedWrite(
        _ORDER,
        order_id,
        version,
        (
            Assignment("status", "set", "APPROVED"),
            Assignment("approved_amount", "set", _amount() if amount is None else amount),
        ),
        (Condition("status", "==", "PENDING_APPROVAL"),),
    )


def _state(
    path: Path,
) -> tuple[tuple[int, int], dict[str, tuple[str, int | None, int]]]:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT balance, version FROM budgets WHERE id = ?", (_BUDGET_ID,)
        ).fetchone()
        assert row is not None
        budget = (int(row[0]), int(row[1]))
        orders = {
            str(order_id): (
                str(status),
                None if approved is None else int(approved),
                int(version),
            )
            for order_id, status, approved, version in connection.execute(
                "SELECT id, status, approved_amount, version FROM purchase_orders ORDER BY id"
            ).fetchall()
        }
        return budget, orders
    finally:
        connection.close()


def test_two_writes_share_one_open_transaction(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    before = _state(path)

    unit = provider.begin(_plan())
    first = unit.apply(_budget_write())
    assert _state(path) == before
    second = unit.apply(_order_write())
    assert _state(path) == before
    assert first.rowcount == 1 and second.rowcount == 1
    assert first.transaction == second.transaction

    unit.commit()
    unit.close()
    budget, orders = _state(path)
    assert budget == (60_000, 2)
    assert orders["PO-A"] == ("APPROVED", 40_000, 2)


def test_unit_of_work_closes_its_connection_after_commit(tmp_path: Path) -> None:
    path = _database(tmp_path)
    unit = _provider(path).begin(_plan())
    assert isinstance(unit, SQLiteUnitOfWork)
    connection = cast(sqlite3.Connection, vars(unit)["_connection"])

    unit.commit()
    unit.close()

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_unit_of_work_closes_its_connection_after_rollback(tmp_path: Path) -> None:
    path = _database(tmp_path)
    unit = _provider(path).begin(_plan())
    assert isinstance(unit, SQLiteUnitOfWork)
    connection = cast(sqlite3.Connection, vars(unit)["_connection"])
    before = _state(path)
    unit.apply(_budget_write())

    unit.rollback()
    unit.close()

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")
    assert _state(path) == before


def test_unit_of_work_close_is_idempotent_after_commit(tmp_path: Path) -> None:
    path = _database(tmp_path)
    unit = _provider(path).begin(_plan())
    unit.commit()
    unit.close()
    unit.close()


class _SecondApplyFails:
    """Test-local wrapper: lose the response after the first write."""

    def __init__(self, inner: UnitOfWork) -> None:
        self._inner = inner
        self._calls = 0

    @property
    def transaction(self) -> str:
        return self._inner.transaction

    def apply(self, write: GuardedWrite) -> ApplyResult:
        self._calls += 1
        if self._calls == 2:
            raise RuntimeError("response lost before commit")
        return self._inner.apply(write)

    def commit(self) -> None:
        raise AssertionError("commit must not be reached")

    def rollback(self) -> None:
        self._inner.rollback()

    def close(self) -> None:
        self._inner.close()


class _FailingProvider:
    def __init__(self, inner: TransactionProvider) -> None:
        self._inner = inner

    def begin(self, plan: SessionPlan) -> UnitOfWork:
        return _SecondApplyFails(self._inner.begin(plan))


def test_failure_after_first_write_rolls_back_cleanly(tmp_path: Path) -> None:
    path = _database(tmp_path)
    before = _state(path)

    with pytest.raises(RuntimeError, match="response lost"):
        commit_guarded_writes(
            _FailingProvider(_provider(path)),
            _plan(),
            (_budget_write(), _order_write()),
        )
    assert _state(path) == before


@pytest.mark.parametrize(
    ("case", "writes", "order_status", "expected_resource"),
    [
        (
            "stale budget version",
            (_budget_write(version=2), _order_write()),
            "PENDING_APPROVAL",
            _BUDGET,
        ),
        (
            "insufficient budget",
            (_budget_write(_amount("120000")), _order_write()),
            "PENDING_APPROVAL",
            _BUDGET,
        ),
        ("order not pending", (_budget_write(), _order_write()), "CANCELLED", _ORDER),
        (
            "stale order version",
            (_budget_write(), _order_write(version=2)),
            "PENDING_APPROVAL",
            _ORDER,
        ),
    ],
)
def test_guard_conflicts_never_overwrite(
    tmp_path: Path,
    case: str,
    writes: tuple[GuardedWrite, ...],
    order_status: str,
    expected_resource: str,
) -> None:
    path = _database(tmp_path, orders=(("PO-A", order_status),))
    before = _state(path)

    with pytest.raises(StalePlan) as caught:
        commit_guarded_writes(_provider(path), _plan(), writes)

    assert caught.value.resource == expected_resource
    assert caught.value.rowcount == 0
    assert _state(path) == before


def test_controlled_two_connection_budget_contention(tmp_path: Path) -> None:
    path = _database(
        tmp_path,
        orders=(("PO-A", "PENDING_APPROVAL"), ("PO-B", "PENDING_APPROVAL")),
    )
    provider = _provider(path)
    plan = _plan()
    before = _state(path)
    both_read = threading.Barrier(2)
    loser_turn = threading.Event()
    outcomes: dict[str, tuple[ApplyResult, ...] | BaseException] = {}

    def run(order_id: str) -> None:
        observed = _state(path)[0]
        assert observed == before[0]
        both_read.wait()
        writes = (
            _budget_write(_amount("80000")),
            _order_write(order_id, amount=_amount("80000")),
        )
        if order_id == "PO-A":
            try:
                outcomes["A"] = commit_guarded_writes(provider, plan, writes)
            except BaseException as error:
                outcomes["A"] = error
            loser_turn.set()
            return
        loser_turn.wait()
        try:
            outcomes["B"] = commit_guarded_writes(provider, plan, writes)
        except StalePlan as error:
            outcomes["B"] = error

    threads = [threading.Thread(target=run, args=(order_id,)) for order_id in ("PO-A", "PO-B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    committed = outcomes["A"]
    assert isinstance(committed, tuple)
    assert all(isinstance(result, ApplyResult) and result.rowcount == 1 for result in committed)
    assert isinstance(outcomes["B"], StalePlan)
    budget, orders = _state(path)
    assert budget == (20_000, 2)
    assert orders["PO-A"] == ("APPROVED", 80_000, 2)
    assert orders["PO-B"] == ("PENDING_APPROVAL", None, 1)


def test_runtime_session_mismatch_is_refused_before_writes(tmp_path: Path) -> None:
    path = _database(tmp_path)
    before = _state(path)

    with pytest.raises(SessionMismatch):
        _provider(path).begin(replace(_plan(), session="sqlite:other"))
    assert _state(path) == before


def test_write_outside_bound_plan_is_refused(tmp_path: Path) -> None:
    path = _database(tmp_path)
    before = _state(path)

    with pytest.raises(UnboundWriteAttempt):
        commit_guarded_writes(_provider(path), replace(_plan(), writes=()), (_budget_write(),))
    assert _state(path) == before


def test_minor_money_conversion_and_currency_pinning(tmp_path: Path) -> None:
    assert MinorMoney.from_decimal(Decimal("12.34"), _CURRENCY, exponent=2).minor == 1234
    with pytest.raises(ValueError):
        MinorMoney.from_decimal(Decimal("12.345"), _CURRENCY, exponent=2)
    with pytest.raises(TypeError):
        MinorMoney.from_decimal(0.1, _CURRENCY)  # type: ignore[arg-type]

    path = _database(tmp_path)
    before = _state(path)
    with pytest.raises(CurrencyMismatch):
        commit_guarded_writes(_provider(path), _plan(), (_budget_write(currency="USD"),))
    assert _state(path) == before
