"""Procurement-side declarations: the order and the approval action.

Cross-module names are written as declared identities
(``"finance.budget"``, ``"finance.reserve_budget"``), so this module never
imports Finance at run time and the graph is composed by Load and Link.
"""

from __future__ import annotations

from codology.declarations import (
    Action,
    Approval,
    CommitRequirement,
    Declaration,
    Effect,
    Link,
    Module,
    ObjectRef,
    ObjectType,
    Param,
    Value,
    all_of,
)
from examples.procurement_finance.common import Money


class PurchaseOrder(ObjectType):
    """A purchase order; it references Finance's budget by declared identity."""

    identity = "procurement.purchase_order"
    version = "1.0.0"
    keyType = "PO"

    status: str
    amount: Money
    budget = Link["finance.budget", "one", "navigable"]


class OrderApprovedPayload(Value):
    """Payload carried by the post-commit warehouse notification effect."""

    order: ObjectRef[PurchaseOrder]
    approved_amount: Money


class NotifyWarehouseOrderApproved(Effect):
    """Outbox intent shape; nothing here delivers it."""

    identity = "procurement.warehouse_order_approved"
    version = "1.0.0"
    payload = OrderApprovedPayload
    dedupKey = ("order",)


class ApprovePurchaseOrder(Action):
    """Approve an order, calling into Finance when the budget threshold is met."""

    identity = "procurement.approve_purchase_order"
    version = "2.0.0"

    order: ObjectRef[PurchaseOrder]
    reason: str

    reads = (PurchaseOrder, "finance.budget")
    writes = (PurchaseOrder,)
    calls = ("finance.reserve_budget",)
    permission = "purchase_order.approve"
    commitRequirement = CommitRequirement.ATOMIC
    approval = Approval.conditional(
        when=all_of(
            Param("order").amount >= 100_000,
            Param("reason") != "",
        ),
        role="finance_director",
        self_approval=False,
    )
    effects = (NotifyWarehouseOrderApproved,)

    def handler(self, ctx: object, order: PurchaseOrder, reason: str) -> None:
        raise AssertionError("static example: handlers are never executed")


class Procurement(Module):
    """Ownership boundary for the Procurement definitions above."""

    identity = "procurement"
    version = "1.0.0"
    exports = (PurchaseOrder, ApprovePurchaseOrder, NotifyWarehouseOrderApproved)


DEFINITIONS: tuple[type[Declaration], ...] = (
    PurchaseOrder,
    OrderApprovedPayload,
    NotifyWarehouseOrderApproved,
    ApprovePurchaseOrder,
)

__all__ = [
    "DEFINITIONS",
    "ApprovePurchaseOrder",
    "NotifyWarehouseOrderApproved",
    "OrderApprovedPayload",
    "Procurement",
    "PurchaseOrder",
]
