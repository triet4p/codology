"""Exact money values as integer minor units under one pinned currency."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

__all__ = ["MinorMoney"]


@dataclass(frozen=True, slots=True)
class MinorMoney:
    """An exact amount: ``minor`` integer units of ``currency``."""

    currency: str
    minor: int

    def __post_init__(self) -> None:
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("MinorMoney.currency must be a non-empty string.")
        if isinstance(self.minor, bool) or not isinstance(self.minor, int):
            raise TypeError("MinorMoney.minor must be an integer count of minor units.")
        object.__setattr__(self, "currency", self.currency.strip())

    def __neg__(self) -> MinorMoney:
        return MinorMoney(self.currency, -self.minor)

    @classmethod
    def from_decimal(cls, value: Decimal, currency: str, *, exponent: int = 0) -> MinorMoney:
        """Convert an exact decimal amount; reject lossy scaling and float input."""
        if not isinstance(value, Decimal):
            raise TypeError("MinorMoney.from_decimal() expects Decimal, never float.")
        if not value.is_finite():
            raise ValueError("MinorMoney.from_decimal() needs a finite amount.")
        if isinstance(exponent, bool) or not isinstance(exponent, int) or exponent < 0:
            raise ValueError("exponent must be a non-negative integer.")
        sign, digits, decimal_exponent = value.as_tuple()
        scale = int(decimal_exponent) + exponent
        raw = int("".join(str(digit) for digit in digits)) if digits else 0
        if scale >= 0:
            minor = raw * (10**scale)
        else:
            divisor = 10 ** (-scale)
            if raw % divisor:
                raise ValueError(f"amount {value} is not exact at exponent {exponent}.")
            minor = raw // divisor
        return cls(currency, -minor if sign else minor)
