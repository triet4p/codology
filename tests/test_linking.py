from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from codology.declarations import (
    Action,
    Declaration,
    DeclarationMeta,
    Link,
    Module,
    ObjectRef,
    ObjectType,
    Value,
)
from codology.linking import (
    HandlerMismatch,
    NotExported,
    ObjectRefMismatch,
    UnresolvedReference,
    WrongKind,
    link,
)
from codology.loading import ModuleDeclarations, load

_AMBIGUOUS_NAME = "Budget"
_BUDGET_ID = "finance.budget"
_MISSING_TARGET = "finance.not_defined"


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
    budget = Link["Budget", "one", "navigable"]
    amount: Money


class ReserveBudget(Action):
    identity = "finance.reserve_budget"
    version = "1.0.0"
    budget: ObjectRef[_BUDGET_ID]
    amount: Money
    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget, amount: Money) -> None:
        raise AssertionError("Link must never call a handler")


class ApprovePurchaseOrder(Action):
    identity = "procurement.approve_purchase_order"
    version = "1.1.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = ("finance.budget",)
    writes = (PurchaseOrder,)
    calls = ("finance.reserve_budget",)
    permission = "purchase_order.approve"

    def handler(self, ctx: object, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("Link must never call a handler")


class Procurement(Module):
    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApprovePurchaseOrder)


class Finance(Module):
    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


def _objectref_target(value: object) -> object:
    assert isinstance(value, type) and issubclass(value, ObjectRef)
    return value.target


def _procurement(*definitions: type[Declaration]) -> ModuleDeclarations:
    return ModuleDeclarations(Procurement, [PurchaseOrder, Money, *definitions])


def _composed() -> tuple[ModuleDeclarations, ModuleDeclarations]:
    return (
        _procurement(ApprovePurchaseOrder),
        ModuleDeclarations(Finance, [Budget, ReserveBudget]),
    )


def test_link_resolves_exported_cross_module_calls_and_forward_references() -> None:
    linked = link(load(*_composed()))

    approve = linked.definitions["procurement.approve_purchase_order"]
    assert approve.definition.declaration is ApprovePurchaseOrder
    order_contract = approve.hints["order"]
    assert isinstance(order_contract, type) and issubclass(order_contract, ObjectRef)
    assert order_contract.target is PurchaseOrder
    assert approve.handler_hints["order"] is PurchaseOrder

    edges = {(reference.field, reference.target.identity) for reference in approve.references}
    assert ("params.order", "procurement.purchase_order") in edges
    assert ("reads", "finance.budget") in edges
    assert ("writes", "procurement.purchase_order") in edges
    assert ("calls", "finance.reserve_budget") in edges

    order_edges = {
        (reference.field, reference.target.identity)
        for reference in linked.definitions["procurement.purchase_order"].references
    }
    assert ("links.budget", "finance.budget") in order_edges
    assert ("params.amount", None) in order_edges  # structural Value, not an identity

    reserve = linked.definitions["finance.reserve_budget"]
    assert _objectref_target(reserve.hints["budget"]) is Budget
    assert reserve.handler_hints["budget"] is Budget
    with pytest.raises(TypeError):
        cast(dict[str, object], linked.definitions)["other"] = object()


def test_two_modules_reference_each_other_without_runtime_import_cycles() -> None:
    class FinanceAudit(Action):
        identity = "finance.audit_order"
        version = "1.0.0"
        order: ObjectRef[PurchaseOrder]
        reads = ("procurement.purchase_order",)
        writes = ()
        permission = "finance.audit"

        def handler(self, ctx: object, order: PurchaseOrder) -> None:
            raise AssertionError("Link must never call a handler")

    class BidirectionalFinance(Module):
        identity = "finance"
        version = "1.0.0"
        exports = (Budget, ReserveBudget, FinanceAudit)

    linked = link(
        load(
            _procurement(ApprovePurchaseOrder),
            ModuleDeclarations(BidirectionalFinance, [Budget, ReserveBudget, FinanceAudit]),
        )
    )

    audit = linked.definitions["finance.audit_order"]
    assert _objectref_target(audit.hints["order"]) is PurchaseOrder
    assert audit.handler_hints["order"] is PurchaseOrder
    assert ("params.order", "procurement.purchase_order") in {
        (reference.field, reference.target.identity) for reference in audit.references
    }


def test_typo_in_call_fails_at_link_with_module_identity_and_field() -> None:
    class TypoAction(Action):
        identity = "procurement.typo_action"
        version = "1.0.0"
        calls = ("finance.reserve_budgett",)
        permission = "local.act"

        def handler(self, ctx: object) -> None:
            pass

    with pytest.raises(UnresolvedReference) as error:
        link(
            load(
                _procurement(TypoAction),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )

    assert error.value.module == "procurement"
    assert error.value.identity == "procurement.typo_action"
    assert error.value.field == "calls"
    assert "finance.reserve_budgett" in str(error.value)


def test_unexported_finance_action_is_rejected_at_link() -> None:
    class InternalFinance(Module):
        identity = "finance"
        version = "1.0.0"
        exports = (Budget,)

    with pytest.raises(NotExported) as error:
        link(
            load(
                _procurement(ApprovePurchaseOrder),
                ModuleDeclarations(InternalFinance, [Budget, ReserveBudget]),
            )
        )

    assert error.value.field == "calls"
    assert error.value.module == "procurement"
    assert "finance.reserve_budget" in str(error.value)
    assert "exports" in str(error.value)


def test_call_to_wrong_kind_is_rejected_at_link() -> None:
    class WrongKindAction(Action):
        identity = "procurement.wrong_kind_action"
        version = "1.0.0"
        calls = ("finance.budget",)
        permission = "local.act"

        def handler(self, ctx: object) -> None:
            pass

    with pytest.raises(WrongKind) as error:
        link(
            load(
                _procurement(WrongKindAction),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )

    assert error.value.field == "calls"
    assert "finance.budget" in str(error.value)
    assert "Action" in str(error.value)


def test_reads_of_a_callable_are_rejected_as_wrong_kind() -> None:
    class WrongReads(Action):
        identity = "procurement.wrong_reads"
        version = "1.0.0"
        reads = ("finance.reserve_budget",)
        writes = ()
        permission = "local.act"

        def handler(self, ctx: object) -> None:
            pass

    with pytest.raises(WrongKind) as error:
        link(
            load(
                _procurement(WrongReads),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )

    assert error.value.field == "reads"
    assert "ObjectType" in str(error.value)


def test_objectref_target_mismatch_is_rejected_against_handler_annotation() -> None:
    class MismatchedRef(Action):
        identity = "procurement.mismatched_ref"
        version = "1.0.0"
        order: ObjectRef[PurchaseOrder]
        permission = "local.act"

        def handler(self, ctx: object, order: Budget) -> None:
            pass

    with pytest.raises(ObjectRefMismatch) as error:
        link(
            load(
                _procurement(MismatchedRef),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )

    assert error.value.field == "handler"
    assert "PurchaseOrder" in str(error.value)
    assert "Budget" in str(error.value)


def test_bare_object_type_parameter_is_rejected_at_link() -> None:
    class BareObjectParam(Action):
        identity = "procurement.bare_object_param"
        version = "1.0.0"
        order: PurchaseOrder
        permission = "local.act"

        def handler(self, ctx: object, order: PurchaseOrder) -> None:
            pass

    with pytest.raises(ObjectRefMismatch) as error:
        link(
            load(
                _procurement(BareObjectParam),
                ModuleDeclarations(Finance, [Budget, ReserveBudget]),
            )
        )

    assert error.value.field == "params.order"
    assert "ObjectRef" in str(error.value)


def test_unresolved_objectref_target_fails_at_link() -> None:
    class MissingRef(Action):
        identity = "procurement.missing_ref"
        version = "1.0.0"
        order: ObjectRef[_MISSING_TARGET]
        permission = "local.act"

        def handler(self, ctx: object, order: PurchaseOrder) -> None:
            pass

    with pytest.raises(UnresolvedReference) as error:
        link(load(_procurement(MissingRef), ModuleDeclarations(Finance, [Budget, ReserveBudget])))

    assert error.value.field == "params.order"
    assert "finance.not_defined" in str(error.value)


def test_handler_parameter_names_must_match_declared_params() -> None:
    class BadNames(Action):
        identity = "procurement.bad_names"
        version = "1.0.0"
        order: ObjectRef[PurchaseOrder]
        permission = "local.act"

        def handler(self, ctx: object, wrong_name: PurchaseOrder) -> None:
            pass

    with pytest.raises(HandlerMismatch) as error:
        link(load(_procurement(BadNames), ModuleDeclarations(Finance, [Budget, ReserveBudget])))

    assert error.value.field == "handler"
    assert "wrong_name" in str(error.value)
    assert "order" in str(error.value)


def test_handler_must_follow_the_single_convention_at_link() -> None:
    class LegacyHandle(Action):
        identity = "procurement.legacy_handle"
        version = "1.0.0"
        permission = "local.act"

        def handle(self, ctx: object) -> None:
            pass

    with pytest.raises(HandlerMismatch) as error:
        link(load(_procurement(LegacyHandle), ModuleDeclarations(Finance, [Budget, ReserveBudget])))

    assert error.value.field == "handler"
    assert "Found 'handle'" in str(error.value)


def test_ambiguous_host_name_requires_a_full_identity() -> None:
    class AmbiguousRef(Action):
        identity = "procurement.ambiguous_ref"
        version = "1.0.0"
        budget: ObjectRef[_AMBIGUOUS_NAME]  # pyright: ignore[reportInvalidTypeForm]
        permission = "local.act"

        def handler(self, ctx: object, budget: object) -> None:
            pass

    finance_budget = cast(
        type[ObjectType],
        DeclarationMeta(
            "Budget",
            (ObjectType,),
            {"identity": "finance.other_budget", "version": "1.0.0"},
        ),
    )
    procurement_budget = cast(
        type[ObjectType],
        DeclarationMeta(
            "Budget",
            (ObjectType,),
            {"identity": "procurement.other_budget", "version": "1.0.0"},
        ),
    )

    with pytest.raises(UnresolvedReference) as error:
        link(
            load(
                ModuleDeclarations(Procurement, [AmbiguousRef, procurement_budget]),
                ModuleDeclarations(Finance, [finance_budget]),
            )
        )

    assert error.value.field == "params.budget"
    assert "ambiguous" in str(error.value)
    assert "finance.other_budget" in str(error.value)
    assert "procurement.other_budget" in str(error.value)
