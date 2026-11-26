"""Read-policy behavior at the engine query boundary and SQLite read adapter."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest

from codology import (
    AllOf,
    Comparison,
    DefinitionKey,
    InvalidCursor,
    LinkBinding,
    OrderBy,
    Principal,
    QueryPage,
    QueryPredicate,
    QueryRequest,
    QueryRow,
    ReadDenied,
    ReadGrant,
    SecureQueryProvider,
    UnsupportedSecureQuery,
    VersionedRef,
    query,
)
from codology.adapter import ResourceBinding, SQLiteProvider
from codology.declarations import ObjectType
from codology.money import MinorMoney

_ORDER = "procurement.purchase_order"
_DEFINITION = DefinitionKey(_ORDER, "1.0.0")
_BUDGET = DefinitionKey("finance.budget", "1.0.0")
_SESSION = "sqlite:main"
_CURRENCY = "VND"


class PurchaseOrder(ObjectType):
    identity = _ORDER
    version = "1.0.0"
    keyType = "PO"

    status: str
    approved_amount: int


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
"""

_ROWS = (
    ("PO-1", "A", "team1", "PENDING_APPROVAL", None, 2, 1),
    ("PO-2", "A", "team2", "PENDING_APPROVAL", None, 2, 1),
    ("PO-3", "B", "team1", "PENDING_APPROVAL", None, 2, 1),
    ("PO-4", "A", "team1", "APPROVED", 40_000, 1, 3),
    ("PO-5", "A", "team1", "PENDING_APPROVAL", None, 2, 2),
    ("PO-6", "A", "team1", "PENDING_APPROVAL", None, 3, 1),
)


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "read.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        connection.executemany(
            "INSERT INTO purchase_orders "
            "(id, tenant, scope, status, approved_amount, created_at, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            _ROWS,
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
                currency=_CURRENCY,
                tenant_column="tenant",
                scope_column="scope",
                links=(
                    LinkBinding("budget", _BUDGET, "internal", "budget_id"),
                    LinkBinding("budget_view", _BUDGET, "navigable", "budget_id"),
                ),
            ),
        ),
    )


def _principal(
    identity: str = "alice",
    tenant: str = "A",
    permissions: frozenset[str] = frozenset({"purchase_order.read"}),
) -> Principal:
    return Principal(identity, tenant, permissions)


def _grant(
    principal: str = "alice",
    tenant: str = "A",
    scopes: tuple[str, ...] = ("team1",),
) -> ReadGrant:
    return ReadGrant(principal, _DEFINITION, tenant, scopes, "purchase_order.read")


def _pending() -> Comparison:
    return Comparison("status", "==", "PENDING_APPROVAL")


def _unsupported_op() -> Comparison:
    predicate = Comparison("status", "==", "P%")
    object.__setattr__(predicate, "op", cast(object, "like"))
    return predicate


def _state(path: Path) -> tuple[tuple[object, ...], ...]:
    connection = sqlite3.connect(path)
    try:
        return tuple(
            connection.execute(
                "SELECT id, tenant, scope, status, approved_amount, created_at, version "
                "FROM purchase_orders ORDER BY id"
            ).fetchall()
        )
    finally:
        connection.close()


class _CountingProvider:
    def __init__(self, inner: SecureQueryProvider) -> None:
        self._inner = inner
        self.calls = 0

    def fetch(self, request: QueryRequest) -> QueryPage[object]:
        self.calls += 1
        return self._inner.fetch(request)


def test_policy_filters_rows_count_and_cursor_pages_before_pagination(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    principal = _principal()
    grant = _grant()

    first: QueryPage[PurchaseOrder] = query(
        provider=provider,
        principal=principal,
        grant=grant,
        from_=_DEFINITION,
        target=PurchaseOrder,
        order=OrderBy("created_at"),
        predicate=_pending(),
        limit=1,
        count_requested=True,
    )
    assert first.count == 3
    assert [row.key for row in first.rows] == ["PO-1"]
    assert first.next_cursor is not None

    seen: list[str] = []
    cursor = first.next_cursor
    while cursor is not None:
        page: QueryPage[PurchaseOrder] = query(
            provider=provider,
            principal=principal,
            grant=grant,
            from_=_DEFINITION,
            target=PurchaseOrder,
            order=OrderBy("created_at"),
            predicate=_pending(),
            cursor=cursor,
            limit=1,
            count_requested=True,
        )
        assert page.count == 3
        seen.extend(row.key for row in page.rows)
        assert all(
            row.values["tenant"] == "A"
            and row.values["scope"] == "team1"
            and row.values["status"] == "PENDING_APPROVAL"
            for row in page.rows
        )
        cursor = page.next_cursor

    assert seen == ["PO-5", "PO-6"]


def test_stable_order_tie_break_and_repeated_pages(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    principal = _principal()
    grant = _grant()

    full: QueryPage[PurchaseOrder] = query(
        provider=provider,
        principal=principal,
        grant=grant,
        from_=_DEFINITION,
        target=PurchaseOrder,
        order=OrderBy("created_at"),
        limit=10,
    )
    repeated: QueryPage[PurchaseOrder] = query(
        provider=provider,
        principal=principal,
        grant=grant,
        from_=_DEFINITION,
        target=PurchaseOrder,
        order=OrderBy("created_at"),
        limit=10,
    )
    keys = [row.key for row in full.rows]
    assert keys == ["PO-4", "PO-1", "PO-5", "PO-6"]
    assert [row.key for row in repeated.rows] == keys

    by_status: QueryPage[PurchaseOrder] = query(
        provider=provider,
        principal=principal,
        grant=grant,
        from_=_DEFINITION,
        target=PurchaseOrder,
        order=OrderBy("status", "desc"),
        limit=10,
    )
    assert [row.key for row in by_status.rows] == ["PO-1", "PO-5", "PO-6", "PO-4"]


def test_desc_cursor_pagination_keeps_tied_rows(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _provider(path)
    seen: list[str] = []
    cursor: str | None = None

    for _ in range(4):
        page: QueryPage[PurchaseOrder] = query(
            provider=provider,
            principal=_principal(),
            grant=_grant(),
            from_=_DEFINITION,
            target=PurchaseOrder,
            order=OrderBy("created_at", "desc"),
            predicate=_pending(),
            cursor=cursor,
            limit=1,
            count_requested=True,
        )
        seen.extend(row.key for row in page.rows)
        assert page.count == 3
        cursor = page.next_cursor
        if cursor is None:
            break

    assert cursor is None
    assert seen == ["PO-6", "PO-1", "PO-5"]


def test_cursor_is_bound_to_policy_and_predicate(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _CountingProvider(_provider(path))
    first: QueryPage[PurchaseOrder] = query(
        provider=provider,
        principal=_principal(),
        grant=_grant(),
        from_=_DEFINITION,
        target=PurchaseOrder,
        order=OrderBy("created_at"),
        predicate=_pending(),
        limit=1,
    )
    assert first.next_cursor is not None
    cursor = first.next_cursor
    before = provider.calls
    with pytest.raises(InvalidCursor, match="does not belong to this authorized query"):
        query(
            provider=provider,
            principal=_principal("bob", "B"),
            grant=_grant("bob", "B"),
            from_=_DEFINITION,
            target=PurchaseOrder,
            order=OrderBy("created_at"),
            predicate=_pending(),
            cursor=cursor,
            limit=1,
        )

    with pytest.raises(InvalidCursor):
        query(
            provider=provider,
            principal=_principal(),
            grant=_grant(),
            from_=_DEFINITION,
            target=PurchaseOrder,
            order=OrderBy("created_at"),
            predicate=Comparison("status", "==", "APPROVED"),
            cursor=cursor,
            limit=1,
        )

    with pytest.raises(InvalidCursor):
        query(
            provider=provider,
            principal=_principal(),
            grant=_grant(),
            from_=_DEFINITION,
            target=PurchaseOrder,
            order=OrderBy("created_at"),
            cursor="not-a-cursor",
            limit=1,
        )

    assert provider.calls == before


@pytest.mark.parametrize(
    ("predicate", "traverse", "match", "reaches_adapter"),
    [
        (cast(QueryPredicate, "status = 'PENDING'"), None, "unsupported predicate", False),
        (_unsupported_op(), None, "verified pushdown", False),
        (Comparison("secret", "==", "x"), None, "no verified pushdown", True),
        (None, "budget", "internal", True),
        (None, "budget_view", "no conformance-proven pushdown", True),
    ],
)
def test_unsupported_predicate_or_traversal_returns_no_rows(
    tmp_path: Path,
    predicate: QueryPredicate | None,
    traverse: str | None,
    match: str,
    reaches_adapter: bool,
) -> None:
    path = _database(tmp_path)
    before = _state(path)
    provider = _CountingProvider(_provider(path))

    with pytest.raises(UnsupportedSecureQuery, match=match):
        query(
            provider=provider,
            principal=_principal(),
            grant=_grant(),
            from_=_DEFINITION,
            target=PurchaseOrder,
            order=OrderBy("created_at"),
            predicate=predicate,
            traverse=traverse,
            limit=5,
            count_requested=True,
        )
    assert _state(path) == before
    assert provider.calls == (1 if reaches_adapter else 0)


def test_row_ref_is_versioned_and_cannot_be_rebuilt_from_an_id(tmp_path: Path) -> None:
    path = _database(tmp_path)
    page: QueryPage[PurchaseOrder] = query(
        provider=_provider(path),
        principal=_principal(),
        grant=_grant(),
        from_=_DEFINITION,
        target=PurchaseOrder,
        order=OrderBy("created_at"),
        predicate=_pending(),
        limit=1,
    )
    row: QueryRow[PurchaseOrder] = page.rows[0]
    ref: VersionedRef[PurchaseOrder] = row.as_ref()
    assert ref.definition == _DEFINITION
    assert ref.key == "PO-1"
    assert ref.instance_version == 1
    with pytest.raises(ValueError, match="issued by authorized query rows"):
        VersionedRef(_DEFINITION, "PO-1", 1, object())


def test_missing_live_permission_denies_before_adapter_read(tmp_path: Path) -> None:
    path = _database(tmp_path)
    provider = _CountingProvider(_provider(path))

    with pytest.raises(ReadDenied, match="no live read grant"):
        query(
            provider=provider,
            principal=_principal(permissions=frozenset()),
            grant=_grant(),
            from_=_DEFINITION,
            target=PurchaseOrder,
            order=OrderBy("created_at"),
            predicate=cast(QueryPredicate, object()),
        )
    with pytest.raises(ReadDenied):
        query(
            provider=provider,
            principal=_principal("bob", "B"),
            grant=_grant(),
            from_=_DEFINITION,
            target=PurchaseOrder,
            order=OrderBy("created_at"),
        )
    assert provider.calls == 0


def test_exact_money_predicate_is_pushed_down(tmp_path: Path) -> None:
    path = _database(tmp_path)
    page: QueryPage[PurchaseOrder] = query(
        provider=_provider(path),
        principal=_principal(),
        grant=_grant(),
        from_=_DEFINITION,
        target=PurchaseOrder,
        order=OrderBy("created_at"),
        predicate=AllOf(
            (
                Comparison("status", "==", "APPROVED"),
                Comparison(
                    "approved_amount",
                    "==",
                    MinorMoney.from_decimal(Decimal("40000"), _CURRENCY),
                ),
            )
        ),
        limit=5,
        count_requested=True,
    )
    assert [row.key for row in page.rows] == ["PO-4"]
    assert page.count == 1


def test_query_connection_is_read_only(tmp_path: Path) -> None:
    path = _database(tmp_path)
    before = _state(path)
    page: QueryPage[PurchaseOrder] = query(
        provider=_provider(path),
        principal=_principal(),
        grant=_grant(),
        from_=_DEFINITION,
        target=PurchaseOrder,
        order=OrderBy("created_at"),
        predicate=Comparison("status", "==", "CANCELLED"),
        limit=5,
        count_requested=True,
    )
    assert page.rows == ()
    assert page.count == 0
    assert _state(path) == before
