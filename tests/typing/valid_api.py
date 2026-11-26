"""Positive typing checks for the Load -> Link -> Snapshot surface.

This module is not collected by pytest; ``uv run pyright`` checks it in strict
mode. ``assert_type`` calls fail the type-check if a public return type drifts.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import assert_type, cast

from codology import (
    AllOf,
    Assignment,
    Comparison,
    Condition,
    DefinitionKey,
    Dependency,
    GuardedWrite,
    LinkedDeclarations,
    LinkedDefinition,
    LoadedDeclarations,
    LoadedDefinition,
    LoadedModule,
    MinorMoney,
    OrderBy,
    Principal,
    QueryPage,
    QueryRow,
    ReadGrant,
    Snapshot,
    SnapshotEntry,
    VersionedRef,
    link,
    load,
    snapshot,
)
from codology.declarations import ObjectRef
from examples.procurement_finance.finance import Budget
from examples.procurement_finance.model import FINANCE_GROUP, PROCUREMENT_GROUP

loaded = load(PROCUREMENT_GROUP, FINANCE_GROUP)
assert_type(loaded, LoadedDeclarations)
assert_type(loaded.modules["finance"], LoadedModule)
assert_type(loaded.definitions["finance.budget"], LoadedDefinition)
assert_type(loaded.definitions["finance.budget"].identity, str | None)
assert_type(loaded.definitions["finance.budget"].owner, str)

linked = link(loaded)
assert_type(linked, LinkedDeclarations)
assert_type(linked.definitions["finance.budget"], LinkedDefinition)
assert_type(linked.definitions["finance.budget"].hints, Mapping[str, object])
assert_type(linked.definitions["finance.budget"].handler_hints, Mapping[str, object])

published = snapshot(linked)
assert_type(published, Snapshot)
entry = published.lookup("finance.budget", "1.0.0")
assert_type(entry, SnapshotEntry)
assert_type(entry.dependencies, tuple[Dependency, ...])
assert_type(published.versions_of("finance.budget"), tuple[str, ...])
assert_type(DefinitionKey("finance.budget", "1.0.0"), DefinitionKey)

assert_type(ObjectRef[Budget], type[ObjectRef])
assert_type(MinorMoney.from_decimal(Decimal("12.34"), "VND", exponent=2), MinorMoney)
assert_type(Assignment("balance", "add", -1), Assignment)
assert_type(Condition("balance", ">=", 1), Condition)
assert_type(
    GuardedWrite("finance.budget", "B-001", 1, (Assignment("balance", "add", -1),)),
    GuardedWrite,
)
assert_type(Principal("alice", "A", frozenset({"purchase_order.read"})), Principal)
assert_type(
    ReadGrant("alice", DefinitionKey("finance.budget", "1.0.0"), "A", ("team1",), "read"),
    ReadGrant,
)
assert_type(Comparison("status", "==", "PENDING_APPROVAL"), Comparison)
assert_type(AllOf((Comparison("status", "==", "PENDING_APPROVAL"),)), AllOf)
assert_type(OrderBy("created_at", "asc"), OrderBy)
row: QueryRow[Budget] = cast(
    QueryRow[Budget],
    QueryRow.issue(DefinitionKey("finance.budget", "1.0.0"), "B-001", 1, {"balance": 100}),
)
assert_type(row.as_ref(), VersionedRef[Budget])
assert_type(
    VersionedRef.issue(DefinitionKey("finance.budget", "1.0.0"), "B-001", 1),
    VersionedRef[object],
)
assert_type(QueryPage((row,), 1, None), QueryPage[Budget])
