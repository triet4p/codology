"""Tier-2 runtime contract for Procurement and Finance.

This is deliberately separate from the static tier-3 declarations in
``procurement.py``: no ``approval`` and no ``effects``, and handlers that run
inside a scoped unit of work. Amounts use exact ``MinorMoney`` values with one
pinned currency; the SQLite adapter stores integer minor units and rejects any
other currency at the write boundary.
"""

from __future__ import annotations

from codology.declarations import Action, CommitRequirement, Link, Module, ObjectRef, ObjectType
from codology.engine import HandlerCtx
from codology.money import MinorMoney


class PurchaseOrder(ObjectType):
    """An order owned by Procurement, linked to the Finance-owned budget."""

    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"

    status: str
    approved_amount: int
    budget = Link["finance.budget", "one", "navigable"]


class Budget(ObjectType):
    """A budget owned by Finance, holding integer minor units of one currency."""

    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"

    ceiling: int
    reserved: int


class ReserveBudget(Action):
    """The Finance-owned child action: the only writer of ``Budget``."""

    identity = "finance.reserve_budget"
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: MinorMoney
    expectedVersion: int

    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(
        self,
        ctx: HandlerCtx,
        budget: Budget,
        amount: MinorMoney,
        expectedVersion: int,
    ) -> None:
        ctx.require(amount.minor > 0, reason="amount_not_positive")
        available = budget.ceiling - budget.reserved
        ctx.require(available >= amount.minor, reason="budget_insufficient")
        ctx.uow.register_mutation(
            budget,
            reserved=budget.reserved + amount.minor,
            expectedVersion=expectedVersion,
        )


class ApprovePurchaseOrder(Action):
    """The tier-2 root: approves the order and delegates the reservation."""

    identity = "procurement.approve_purchase_order"
    version = "1.1.0"

    order: ObjectRef[PurchaseOrder]
    budget: ObjectRef[Budget]
    reason: str
    amount: MinorMoney

    reads = (PurchaseOrder, Budget)
    writes = (PurchaseOrder,)
    calls = ("finance.reserve_budget",)
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC

    def handler(
        self,
        ctx: HandlerCtx,
        order: PurchaseOrder,
        budget: Budget,
        reason: str,
        amount: MinorMoney,
    ) -> None:
        ctx.require(order.status == "PENDING_APPROVAL", reason="order_not_pending")
        ctx.require(bool(reason.strip()), reason="reason_required")
        ctx.call(
            "finance.reserve_budget",
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


class Procurement(Module):
    """Ownership boundary for the Procurement declarations above."""

    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApprovePurchaseOrder)


class Finance(Module):
    """Ownership boundary for the Finance declarations above."""

    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


__all__ = [
    "ApprovePurchaseOrder",
    "Budget",
    "Finance",
    "Procurement",
    "PurchaseOrder",
    "ReserveBudget",
]
