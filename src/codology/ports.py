"""Core-owned ports for physical transactions and guarded writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast

from codology.binding import SessionPlan

SetOp = Literal["set", "add"]
CompareOp = Literal["==", "!=", ">", ">=", "<", "<="]

_COMPARE_OPS = frozenset({"==", "!=", ">", ">=", "<", "<="})
_SET_OPS = frozenset({"set", "add"})


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


@dataclass(frozen=True, slots=True)
class Assignment:
    """One column change: ``set`` to a value or ``add`` a signed delta."""

    column: str
    op: SetOp
    value: object

    def __post_init__(self) -> None:
        _require_text(self.column, "Assignment.column")
        if self.op not in _SET_OPS:
            raise ValueError(f"unsupported assignment operator {self.op!r}.")


@dataclass(frozen=True, slots=True)
class Condition:
    """One predicate checked atomically with the write it guards."""

    column: str
    op: CompareOp
    value: object

    def __post_init__(self) -> None:
        _require_text(self.column, "Condition.column")
        if self.op not in _COMPARE_OPS:
            raise ValueError(f"unsupported comparison operator {self.op!r}.")


@dataclass(frozen=True, slots=True)
class GuardedWrite:
    """One conditional mutation: apply it entirely or change nothing."""

    resource: str
    key: str
    expected_version: int
    changes: tuple[Assignment, ...]
    conditions: tuple[Condition, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.resource, "GuardedWrite.resource")
        _require_text(self.key, "GuardedWrite.key")
        expected_version = cast(object, self.expected_version)
        if isinstance(expected_version, bool) or not isinstance(expected_version, int):
            raise TypeError("GuardedWrite.expected_version must be an integer.")
        if self.expected_version < 0:
            raise ValueError("GuardedWrite.expected_version cannot be negative.")
        changes = tuple(self.changes)
        if not changes:
            raise ValueError("a guarded write needs at least one assignment.")
        object.__setattr__(self, "changes", changes)
        object.__setattr__(self, "conditions", tuple(self.conditions))


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Observable outcome of one accepted write inside a transaction."""

    resource: str
    key: str
    rowcount: int
    transaction: str


class StalePlan(Exception):
    """A guarded write matched no row, so no value was overwritten."""

    def __init__(
        self,
        resource: str,
        key: str,
        expected_version: int,
        rowcount: int,
        transaction: str,
    ) -> None:
        super().__init__(
            f"stale plan: guarded write to {resource!r} key {key!r} at version "
            f"{expected_version} matched {rowcount} row(s) in transaction {transaction}; "
            "re-read and recompute."
        )
        self.resource = resource
        self.key = key
        self.expected_version = expected_version
        self.rowcount = rowcount
        self.transaction = transaction


class TransactionUnavailable(Exception):
    """The bound transaction could not be opened or used before a commit attempt.

    Raised when the physical session is missing, locked by another writer, or
    otherwise unable to take the work. No commit was attempted, so nothing can
    have become durable through this unit.
    """


class CommitOutcomeUnknown(Exception):
    """A commit was attempted but did not report a definite outcome.

    The writes may or may not be durable. A caller must reconcile instead of
    assuming a rollback or retrying blindly.
    """


class SessionMismatch(TransactionUnavailable):
    """A bound plan names a physical session the provider did not open."""


class UnitOfWork(Protocol):
    """One open transaction, owned by the engine until it commits or rolls back."""

    @property
    def transaction(self) -> str:
        """Opaque identity of the physical transaction."""
        ...

    def apply(self, write: GuardedWrite) -> ApplyResult:
        """Apply one guarded write on this transaction's session."""
        ...

    def commit(self) -> None:
        """Make every applied write durable in one commit."""
        ...

    def rollback(self) -> None:
        """Discard every applied write."""
        ...

    def close(self) -> None:
        """Release the session; never writes after this."""
        ...


class TransactionProvider(Protocol):
    """Opens the enlisted physical transaction named by a bound session plan."""

    def begin(self, plan: SessionPlan) -> UnitOfWork:
        """Open one transaction on the plan's session."""
        ...
