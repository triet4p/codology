"""Runtime declarations for the conditional-approval consumer example.

The threshold, role and self-approval policy live here in the declaration, not
in the engine or the consumer. Handlers own the business rules; the example's
consumer only calls engine ports. A second revision set has handlers that must
never run, so replay can prove that the pinned manifest wins over a new
default version.
"""

from __future__ import annotations

from typing import cast

from codology import payload_of
from codology.declarations import Action, Effect, Module, ObjectRef, ObjectType, Value, all_of
from codology.declarations.behavior import Approval, Param
from codology.engine import HandlerCtx, ResolvedObject

ORDER = "procurement.purchase_order"
BUDGET = "finance.budget"
ROOT = "procurement.approve_purchase_order"
RESERVE = "finance.reserve_budget"
PAYLOAD = "procurement.order_approved_payload"
EFFECT = "procurement.warehouse_order_approved"

APPROVE_PERMISSION = "purchase_order.approve"
RESERVE_PERMISSION = "budget.reserve"
APPROVAL_ROLE = "finance_director"
APPROVAL_THRESHOLD = 100_000


class PurchaseOrder(ObjectType):
    """An order owned by Procurement; its budget arrives as a typed ref."""

    identity = ORDER
    version = "1.0.0"
    keyType = "PO"

    status: str
    amount: int


class Budget(ObjectType):
    """A budget owned by Finance, holding integer minor units of one currency."""

    identity = BUDGET
    version = "1.0.0"
    keyType = "B"

    ceiling: int
    reserved: int


class ReserveBudget(Action):
    """Finance's child action: the only writer of ``Budget``."""

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
    """A newer default child whose handler must never run on a pinned replay."""

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


class OrderApprovedPayload(Value):
    """Typed snapshot carried by the post-commit warehouse notification."""

    identity = PAYLOAD
    version = "1.0.0"

    order: ObjectRef[PurchaseOrder]
    approved_amount: int


class NotifyWarehouse(Effect):
    """Outbox intent shape; delivery is owned by the relay, not this handler."""

    identity = EFFECT
    version = "1.0.0"
    payload = OrderApprovedPayload
    dedupKey = ("order",)


class ApprovePurchaseOrder(Action):
    """The tier-3 root: conditional approval, child call and one outbox intent."""

    identity = ROOT
    version = "2.0.0"

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]
    reason: str

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (RESERVE,)
    permission = APPROVE_PERMISSION
    effects = (NotifyWarehouse,)

    approval = Approval.conditional(
        when=all_of(
            Param("order").amount >= APPROVAL_THRESHOLD,
            Param("reason") != "",
        ),
        role=APPROVAL_ROLE,
        self_approval=False,
    )

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget, reason: str) -> None:
        ctx.require(order.status == "PENDING", reason="order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")
        ctx.call(RESERVE, budget=budget, amount=order.amount, expectedVersion=budget.version)
        ctx.uow.register_mutation(order, status="APPROVED", expectedVersion=order.version)
        ctx.uow.enqueue_effect(
            NotifyWarehouse,
            payload=payload_of(
                OrderApprovedPayload,
                order=cast(ResolvedObject[PurchaseOrder], order).ref,
                approved_amount=order.amount,
            ),
        )


class ApprovePurchaseOrderLater(Action):
    """A newer default root whose handler must never run on a pinned replay."""

    identity = ROOT
    version = "2.1.0"

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]
    reason: str

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = (RESERVE,)
    permission = APPROVE_PERMISSION
    effects = (NotifyWarehouse,)

    approval = Approval.conditional(
        when=all_of(
            Param("order").amount >= APPROVAL_THRESHOLD,
            Param("reason") != "",
        ),
        role=APPROVAL_ROLE,
        self_approval=False,
    )

    def handler(self, ctx: HandlerCtx, order: PurchaseOrder, budget: Budget, reason: str) -> None:
        raise AssertionError("the unpinned root handler must not run")


class Procurement(Module):
    """Ownership boundary for the pinned Procurement revision set."""

    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApprovePurchaseOrder, OrderApprovedPayload, NotifyWarehouse)


class ProcurementLater(Module):
    """Ownership boundary for the newer default Procurement revision set."""

    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApprovePurchaseOrderLater, OrderApprovedPayload, NotifyWarehouse)


class Finance(Module):
    """Ownership boundary for the pinned Finance revision set."""

    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


class FinanceLater(Module):
    """Ownership boundary for the newer default Finance revision set."""

    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudgetLater)


__all__ = [
    "APPROVAL_ROLE",
    "APPROVAL_THRESHOLD",
    "APPROVE_PERMISSION",
    "BUDGET",
    "EFFECT",
    "Finance",
    "FinanceLater",
    "ORDER",
    "PAYLOAD",
    "Procurement",
    "ProcurementLater",
    "RESERVE",
    "RESERVE_PERMISSION",
    "ROOT",
    "ApprovePurchaseOrder",
    "ApprovePurchaseOrderLater",
    "Budget",
    "NotifyWarehouse",
    "OrderApprovedPayload",
    "PurchaseOrder",
    "ReserveBudget",
    "ReserveBudgetLater",
]
