"""Finance-side declarations: the budget object and its reservation action."""

from __future__ import annotations

from codology.declarations import Action, Declaration, Module, ObjectRef, ObjectType
from examples.procurement_finance.common import Money


class Budget(ObjectType):
    """The budget an order draws from; owned by Finance."""

    identity = "finance.budget"
    version = "1.0.0"
    keyType = "B"

    limit: Money
    reserved: Money


class ReserveBudget(Action):
    """Reserve part of a budget; callable from another module once exported."""

    identity = "finance.reserve_budget"
    version = "1.0.0"

    budget: ObjectRef[Budget]
    amount: Money

    reads = (Budget,)
    writes = (Budget,)
    permission = "budget.reserve"

    def handler(self, ctx: object, budget: Budget, amount: Money) -> None:
        raise AssertionError("static example: handlers are never executed")


class Finance(Module):
    """Ownership boundary for the Finance definitions above."""

    identity = "finance"
    version = "1.0.0"
    exports = (Budget, ReserveBudget)


DEFINITIONS: tuple[type[Declaration], ...] = (Money, Budget, ReserveBudget)

__all__ = ["DEFINITIONS", "Budget", "Finance", "ReserveBudget"]
