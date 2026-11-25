"""A structural value shared by both modules of the example."""

from __future__ import annotations

from decimal import Decimal

from codology.declarations import Value


class Money(Value):
    """An amount with a currency; it has no lifecycle and no identity."""

    amount: Decimal
    currency: str
