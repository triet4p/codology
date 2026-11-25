from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from decimal import Decimal
from typing import cast

import pytest

from codology import (
    DefinitionKey,
    LinkedDeclarations,
    ModuleDeclarations,
    UnknownDefinition,
    link,
    load,
    snapshot,
)
from codology.declarations import (
    Action,
    Approval,
    CommitRequirement,
    Declaration,
    Module,
    ObjectRef,
    ObjectType,
    Param,
    Value,
    all_of,
)
from codology.snapshot import (
    AllOfExpr,
    ApprovalView,
    ComparisonExpr,
    Expression,
    FieldPath,
    LiteralValue,
    Snapshot,
)


class Money(Value):
    amount: Decimal
    currency: str


class Budget(ObjectType):
    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"
    limit: Money


class PurchaseOrder(ObjectType):
    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"
    amount: Money


class ReserveBudget(Action):
    identity = "finance.reserve_budget"
    version = "1.0.0"
    budget: ObjectRef[Budget]
    amount: Money
    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget, amount: Money) -> None:
        raise AssertionError("handler must never run")


class ApprovePurchaseOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "1.1.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = ("finance.budget",)
    writes = (PurchaseOrder,)
    calls = ("finance.reserve_budget",)
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC

    def handler(self, ctx: object, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("handler must never run")


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApprovePurchaseOrder)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


def _snapshot() -> Snapshot:
    return snapshot(
        link(
            load(
                ModuleDeclarations(Procurement, [PurchaseOrder, Money, ApprovePurchaseOrder]),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )
    )


def _snapshot_with_approval(when: object) -> Snapshot:
    class ApprovalAction(Action):
        identity = "procurement.approval_action"
        version = "1.0.0"
        order: ObjectRef[PurchaseOrder]
        permission = "order.approve"
        approval = Approval.conditional(when=when, role="finance_director", self_approval=False)

        def handler(self, ctx: object, order: PurchaseOrder) -> None:
            raise AssertionError("handler must never run")

    return snapshot(
        link(
            load(
                ModuleDeclarations(Procurement, [PurchaseOrder, Money, ApprovalAction]),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )
    )


def _approval_when(published: Snapshot) -> Expression:
    entry = published.lookup("procurement.approval_action", "1.0.0")
    assert entry.approval is not None
    return entry.approval.when


def test_lookup_requires_explicit_version_and_reports_available_versions() -> None:
    published = _snapshot()

    assert published.versions_of("finance.reserve_budget") == ("1.0.0",)
    assert published.versions_of("finance.unknown") == ()
    assert not hasattr(published, "latest")

    entry = published.lookup("finance.reserve_budget", "1.0.0")
    assert entry.identity == "finance.reserve_budget"
    assert entry.version == "1.0.0"
    assert entry.owner == "finance"
    assert entry.kind == "Action"
    assert DefinitionKey("finance.reserve_budget", "1.0.0") in published.entries

    with pytest.raises(UnknownDefinition) as error:
        published.lookup("finance.reserve_budget", "9.9.9")
    assert error.value.identity == "finance.reserve_budget"
    assert error.value.version == "9.9.9"
    assert error.value.available == ("1.0.0",)


def test_dependencies_record_declared_edges_and_governance() -> None:
    entry = _snapshot().lookup("procurement.approve_purchase_order", "1.1.0")
    edges = {
        (dep.field, dep.target_identity, dep.target_version, dep.target_kind)
        for dep in entry.dependencies
    }
    assert ("calls", "finance.reserve_budget", "1.0.0", "Action") in edges
    assert ("reads", "finance.budget", "1.0.0", "ObjectType") in edges
    assert ("writes", "procurement.purchase_order", "1.0.0", "ObjectType") in edges
    assert ("params.order", "procurement.purchase_order", "1.0.0", "ObjectType") in edges
    assert entry.permission == "purchase_order.approve"
    assert entry.commit_requirement == "ATOMIC"
    assert entry.approval is None


def test_snapshot_ignores_input_and_returned_collection_mutation() -> None:
    owned: list[type[Declaration]] = [PurchaseOrder, Money, ApprovePurchaseOrder]
    published = snapshot(
        link(
            load(
                ModuleDeclarations(Procurement, owned),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )
    )
    before = published.lookup("procurement.purchase_order", "1.0.0")

    owned.append(ReserveBudget)  # the author's list was copied at Load

    entries = cast(MutableMapping[DefinitionKey, object], published.entries)
    versions = cast(MutableMapping[str, object], published.versions)
    dependencies = cast(list[object], before.dependencies)
    with pytest.raises(TypeError):
        entries[DefinitionKey("injected", "1.0.0")] = object()
    with pytest.raises(TypeError):
        versions["finance"] = ()
    with pytest.raises(AttributeError):
        dependencies.append(object())

    assert published.lookup("procurement.purchase_order", "1.0.0") == before
    assert published.lookup("finance.reserve_budget", "1.0.0").owner == "finance"
    assert published.versions_of("procurement.purchase_order") == ("1.0.0",)


def test_snapshot_literal_is_detached_from_mutable_author_input() -> None:
    operands: dict[str, object] = {"limit": [100]}
    published = _snapshot_with_approval(Param("order").amount > operands)
    key = DefinitionKey("procurement.approval_action", "1.0.0")
    before = published.lookup(key.identity, key.version)

    cast(list[int], operands["limit"]).append(200)  # mutates the author's nested list

    after = published.lookup(key.identity, key.version)
    assert after == before
    assert isinstance(after.approval, ApprovalView)
    when = after.approval.when
    assert isinstance(when, ComparisonExpr)
    assert isinstance(when.right, LiteralValue)
    frozen = cast(Mapping[str, object], when.right.value)
    assert frozen["limit"] == (100,)


def test_approval_expressions_distinguish_comparison_operators() -> None:
    strict = _snapshot_with_approval(Param("order").amount > 100)
    loose = _snapshot_with_approval(Param("order").amount >= 100)

    strict_when = _approval_when(strict)
    loose_when = _approval_when(loose)

    assert isinstance(strict_when, ComparisonExpr)
    assert isinstance(loose_when, ComparisonExpr)
    assert strict_when.operator == ">"
    assert loose_when.operator == ">="
    assert strict_when.left == FieldPath("order", ("amount",))
    assert strict_when != loose_when
    assert strict.lookup("procurement.approval_action", "1.0.0") != loose.lookup(
        "procurement.approval_action", "1.0.0"
    )


def test_approval_expressions_preserve_nested_operator_shape() -> None:
    published = _snapshot_with_approval(
        all_of(Param("order").amount > 100, Param("order").amount >= 200)
    )
    when = _approval_when(published)
    assert isinstance(when, AllOfExpr)
    assert isinstance(when.parts[0], ComparisonExpr)
    assert isinstance(when.parts[1], ComparisonExpr)
    assert when.parts[0].operator == ">"
    assert when.parts[1].operator == ">="


def test_host_class_rename_keeps_identity_and_lookup() -> None:
    class RenamedReserveBudget(Action):
        identity = "finance.reserve_budget"
        version = "1.0.0"
        budget: ObjectRef[Budget]
        amount: Money
        reads = (Budget,)
        writes = (Budget,)
        permission = "budget.reserve"

        def handler(self, ctx: object, budget: Budget, amount: Money) -> None:
            raise AssertionError("handler must never run")

    class RenamedFinance(Module):
        identity = "finance"
        version = "1.0.0"
        exports = (Budget, RenamedReserveBudget)

    original = snapshot(
        link(
            load(
                ModuleDeclarations(Procurement, [PurchaseOrder, Money, ApprovePurchaseOrder]),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )
    )
    renamed = snapshot(
        link(
            load(
                ModuleDeclarations(Procurement, [PurchaseOrder, Money, ApprovePurchaseOrder]),
                ModuleDeclarations(RenamedFinance, [Budget, RenamedReserveBudget]),
            )
        )
    )

    assert original.entries.keys() == renamed.entries.keys()
    assert original.lookup("finance.reserve_budget", "1.0.0") == renamed.lookup(
        "finance.reserve_budget", "1.0.0"
    )
    assert original.versions_of("finance.reserve_budget") == ("1.0.0",)


def test_published_entries_do_not_claim_a_handler_digest() -> None:
    published = _snapshot()
    entry = published.lookup("finance.reserve_budget", "1.0.0")
    assert not hasattr(entry, "digest")
    assert not hasattr(entry, "handler_digest")
    assert not hasattr(published, "digest")


def test_snapshot_rejects_a_non_linked_input() -> None:
    with pytest.raises(TypeError):
        snapshot(cast(LinkedDeclarations, object()))
