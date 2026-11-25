from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from codology.declarations import (
    Action,
    AllOf,
    AnyOf,
    Approval,
    CommitRequirement,
    Comparison,
    DeclarationError,
    Effect,
    Function,
    Literal,
    Negate,
    ObjectRef,
    ObjectType,
    Param,
    UnsupportedApprovalExpression,
    Value,
    all_of,
    not_,
    validate_predicate,
)


class Money(Value):
    amount: Decimal
    currency: str


class Budget(ObjectType):
    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"
    limit: Money
    reserved: Money


class PurchaseOrder(ObjectType):
    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"
    amount: Money
    budget: ObjectRef[Budget]


class ApprovePurchaseOrder(Action):
    """Tier 1: identity, typed params, access scope, permission, handler."""

    identity = "procurement.approve_purchase_order"
    version = "1.0.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = (PurchaseOrder,)
    writes = (PurchaseOrder,)
    permission = "purchase_order.approve"

    def handler(self, ctx: object, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("declaration creation must never execute a handler")


class ReserveBudget(Action):
    identity = "finance.reserve_budget"
    version = "1.0.0"
    budget: ObjectRef[Budget]
    amount: Money
    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget, amount: Money) -> None:
        raise AssertionError("declaration creation must never execute a handler")


class ApprovePurchaseOrderCrossModule(Action):
    """Tier 2: same params and handler, only additive cross-module metadata."""

    identity = "procurement.approve_purchase_order"
    version = "1.1.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = (PurchaseOrder, "Budget")
    writes = (PurchaseOrder,)
    calls = ("finance.reserve_budget",)
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC

    def handler(self, ctx: object, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("declaration creation must never execute a handler")


class OrderApprovedPayload(Value):
    order: ObjectRef[PurchaseOrder]
    approved_amount: Money


class NotifyWarehouseOrderApproved(Effect):
    identity = "procurement.warehouse_order_approved"
    version = "1.0.0"
    payload = OrderApprovedPayload
    dedupKey = ("order",)


class ApproveWithApproval(Action):
    """Tier 3: approval and effects are added without touching tier 1 fields."""

    identity = "procurement.approve_purchase_order"
    version = "2.0.0"
    order: ObjectRef[PurchaseOrder]
    reason: str
    reads = (PurchaseOrder, "Budget")
    writes = (PurchaseOrder,)
    calls = ("finance.reserve_budget",)
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC
    approval = Approval.conditional(
        when=Param("order").normalized_amount >= 100_000,
        role="finance_director",
        self_approval=False,
    )
    effects = (NotifyWarehouseOrderApproved,)

    def handler(self, ctx: object, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("declaration creation must never execute a handler")


def test_tier_one_action_stays_lean_and_keeps_only_declared_metadata() -> None:
    assert ApprovePurchaseOrder.identity == "procurement.approve_purchase_order"
    assert ApprovePurchaseOrder.version == "1.0.0"
    assert tuple(ApprovePurchaseOrder.params) == ("order", "reason")
    assert ApprovePurchaseOrder.params["order"] == "ObjectRef[PurchaseOrder]"
    assert ApprovePurchaseOrder.reads == (PurchaseOrder,)
    assert ApprovePurchaseOrder.writes == (PurchaseOrder,)
    assert ApprovePurchaseOrder.calls == ()
    assert ApprovePurchaseOrder.permission == "purchase_order.approve"
    assert ApprovePurchaseOrder.commitRequirement is None
    assert ApprovePurchaseOrder.approval is None
    assert ApprovePurchaseOrder.effects == ()
    assert ApprovePurchaseOrder.handler.__name__ == "handler"


def test_tier_two_expresses_forward_reference_call_and_atomic_requirement() -> None:
    action = ApprovePurchaseOrderCrossModule

    assert action.reads == (PurchaseOrder, "Budget")
    assert action.params["order"] == ApprovePurchaseOrder.params["order"]
    assert action.calls == (ReserveBudget.identity,)
    assert action.commitRequirement is CommitRequirement.ATOMIC
    assert action.approval is None
    assert action.effects == ()


def test_tier_three_approval_and_effect_metadata_are_structured() -> None:
    approval = ApproveWithApproval.approval
    assert isinstance(approval, Approval)
    assert approval.role == "finance_director"
    assert approval.self_approval is False

    predicate = approval.when
    assert isinstance(predicate, Comparison)
    assert predicate.operator == ">="
    assert predicate.left.parameter == "order"
    assert predicate.left.path == ("normalized_amount",)
    assert isinstance(predicate.right, Literal)
    assert predicate.right.value == 100_000

    assert ApproveWithApproval.effects == (NotifyWarehouseOrderApproved,)
    assert NotifyWarehouseOrderApproved.payload is OrderApprovedPayload
    assert NotifyWarehouseOrderApproved.dedupKey == ("order",)


def test_greater_than_and_greater_or_equal_remain_distinct() -> None:
    strict = Param("order").amount > 100_000
    inclusive = Param("order").amount >= 100_000

    assert strict.operator == ">"
    assert inclusive.operator == ">="
    assert strict != inclusive
    assert strict == (Param("order").amount > 100_000)
    assert strict.right == Literal(100_000)


def test_boolean_combinators_produce_only_structured_predicates() -> None:
    first = Param("order").amount > 100_000
    second = Param("order").status == "PENDING"
    combined = all_of(first, second).or_(not_(first))

    assert isinstance(combined, AnyOf)
    assert len(combined.parts) == 2
    assert isinstance(combined.parts[0], AllOf)
    assert isinstance(combined.parts[1], Negate)
    assert validate_predicate(combined) is combined


def test_behavior_declarations_copy_inputs_and_reject_mutation() -> None:
    input_reads: list[object] = [PurchaseOrder]

    class LocalAction(Action):
        identity = "local.action"
        version = "1.0.0"
        order: ObjectRef[PurchaseOrder]
        reads = cast(tuple[type[ObjectType] | str, ...], input_reads)
        writes = ()
        permission = "local.act"

        def handler(self, ctx: object, order: PurchaseOrder) -> None:
            pass

    input_reads.append(Budget)
    assert LocalAction.reads == (PurchaseOrder,)
    with pytest.raises(AttributeError):
        LocalAction.permission = "other"
    with pytest.raises(TypeError):
        cast(dict[str, object], LocalAction.params)["extra"] = str


def test_read_only_function_carries_result_and_no_mutation_fields() -> None:
    class RemainingBudget(Function):
        identity = "finance.remaining_budget"
        version = "1.0.0"
        budget: ObjectRef[Budget]
        result = Money
        reads = (Budget,)

        def handler(self, ctx: object, budget: Budget) -> Money:
            raise AssertionError("declaration creation must never execute a handler")

    assert RemainingBudget.result is Money
    assert tuple(RemainingBudget.params) == ("budget",)
    assert RemainingBudget.reads == (Budget,)
    assert not hasattr(RemainingBudget, "writes")
    assert not hasattr(RemainingBudget, "approval")
    assert not hasattr(RemainingBudget, "effects")


def test_lambda_in_approval_is_rejected_with_a_clear_error() -> None:
    with pytest.raises(UnsupportedApprovalExpression, match="lambda"):
        Approval.conditional(
            when=lambda: True,
            role="finance_director",
            self_approval=False,
        )


def test_unstructured_expressions_and_operations_are_rejected() -> None:
    with pytest.raises(UnsupportedApprovalExpression, match="bool"):
        Approval.conditional(when=True, role="finance_director", self_approval=False)
    with pytest.raises(UnsupportedApprovalExpression, match="Method calls"):
        assert validate_predicate(Param("order").amount.lower() > "USD")
    with pytest.raises(UnsupportedApprovalExpression, match="Arithmetic"):
        assert validate_predicate(Param("order").amount + 1 > 100_000)
    with pytest.raises(UnsupportedApprovalExpression, match="not supported"):
        all_of(Param("order").amount > 1, True)


def test_approval_requires_explicit_role_and_self_approval() -> None:
    with pytest.raises(DeclarationError, match="role"):
        Approval.conditional(
            when=Param("order").amount > 1,
            role=cast(str, "  "),
            self_approval=False,
        )
    with pytest.raises(DeclarationError, match="self_approval"):
        Approval.conditional(
            when=Param("order").amount > 1,
            role="finance_director",
            self_approval=cast(bool, "no"),
        )


def test_approval_cannot_reference_an_undeclared_parameter() -> None:
    with pytest.raises(DeclarationError, match="undeclared parameter"):

        class InvalidApproval(Action):  # pyright: ignore[reportUnusedClass]
            identity = "procurement.invalid_approval"
            version = "1.0.0"
            order: ObjectRef[PurchaseOrder]
            reads = (PurchaseOrder,)
            writes = ()
            permission = "purchase_order.approve"
            approval = Approval.conditional(
                when=Param("missing").amount > 1,
                role="finance_director",
                self_approval=False,
            )

            def handler(self, ctx: object, order: PurchaseOrder) -> None:
                pass


def test_invalid_action_and_effect_fields_are_rejected_with_context() -> None:
    with pytest.raises(DeclarationError, match="permission"):

        class MissingPermission(Action):  # pyright: ignore[reportUnusedClass]
            identity = "local.missing_permission"
            version = "1.0.0"
            order: ObjectRef[PurchaseOrder]
            reads = (PurchaseOrder,)

            def handler(self, ctx: object, order: PurchaseOrder) -> None:
                pass

    with pytest.raises(DeclarationError, match="reads"):

        class InvalidReads(Action):  # pyright: ignore[reportUnusedClass]
            identity = "local.invalid_reads"
            version = "1.0.0"
            reads = cast(tuple[type[ObjectType] | str, ...], (str,))
            writes = ()
            permission = "local.act"

            def handler(self, ctx: object) -> None:
                pass

    with pytest.raises(DeclarationError, match="calls"):

        class InvalidCalls(Action):  # pyright: ignore[reportUnusedClass]
            identity = "local.invalid_calls"
            version = "1.0.0"
            calls = ("",)
            reads = ()
            writes = ()
            permission = "local.act"

            def handler(self, ctx: object) -> None:
                pass

    with pytest.raises(DeclarationError, match="commitRequirement"):

        class InvalidCommit(Action):  # pyright: ignore[reportUnusedClass]
            identity = "local.invalid_commit"
            version = "1.0.0"
            commitRequirement = cast(CommitRequirement, "ATOMIC")
            reads = ()
            writes = ()
            permission = "local.act"

            def handler(self, ctx: object) -> None:
                pass

    with pytest.raises(DeclarationError, match="effects"):

        class InvalidEffects(Action):  # pyright: ignore[reportUnusedClass]
            identity = "local.invalid_effects"
            version = "1.0.0"
            effects = cast(tuple[type[Effect], ...], (Money,))
            reads = ()
            writes = ()
            permission = "local.act"

            def handler(self, ctx: object) -> None:
                pass

    with pytest.raises(DeclarationError, match="payload"):

        class InvalidEffect(Effect):  # pyright: ignore[reportUnusedClass]
            identity = "local.invalid_effect"
            version = "1.0.0"
            payload = cast(type[Value], int)


def test_read_only_function_rejects_mutation_and_governance_fields() -> None:
    with pytest.raises(DeclarationError, match="read-only"):

        class MutatingFunction(Function):  # pyright: ignore[reportUnusedClass]
            identity = "finance.mutating"
            version = "1.0.0"
            result = Money
            writes = (Budget,)

            def handler(self, ctx: object) -> Money:
                raise AssertionError("never executed")
