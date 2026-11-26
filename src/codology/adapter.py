"""SQLite adapter: one file-backed session, one physical transaction, guarded writes."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from codology.binding import SessionPlan
from codology.money import MinorMoney
from codology.ports import (
    ApplyResult,
    CompareOp,
    GuardedWrite,
    SessionMismatch,
    StalePlan,
    UnitOfWork,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMPARE_SQL: dict[CompareOp, str] = {
    "==": "=",
    "!=": "!=",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}


class UnknownResource(ValueError):
    """No adapter mapping exists for a required resource."""


class InvalidColumn(ValueError):
    """A write names a column the resource mapping did not declare."""


class CurrencyMismatch(ValueError):
    """A money value uses a currency the resource does not pin."""


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


def _identifier(value: object, label: str) -> str:
    text = _require_text(value, label)
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{label} must be a plain SQL identifier; got {text!r}.")
    return text


@dataclass(frozen=True, slots=True)
class ResourceBinding:
    """Physical placement of one declared resource inside the session file."""

    identity: str
    table: str
    columns: tuple[str, ...]
    key_column: str = "id"
    version_column: str = "version"
    currency: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.identity, "ResourceBinding.identity")
        _identifier(self.table, "ResourceBinding.table")
        _identifier(self.key_column, "ResourceBinding.key_column")
        _identifier(self.version_column, "ResourceBinding.version_column")
        columns = tuple(self.columns)
        if not columns:
            raise ValueError("ResourceBinding.columns cannot be empty.")
        for column in columns:
            _identifier(column, "ResourceBinding.columns entry")
        if self.currency is not None:
            _require_text(self.currency, "ResourceBinding.currency")
        object.__setattr__(self, "columns", columns)


def _encode(value: object, binding: ResourceBinding) -> object:
    """Turn a declared value into an exact SQLite bind parameter."""
    if isinstance(value, MinorMoney):
        if binding.currency is None or value.currency != binding.currency:
            raise CurrencyMismatch(
                f"resource {binding.identity!r} pins currency {binding.currency!r}, "
                f"got {value.currency!r}."
            )
        return value.minor
    if isinstance(value, bool) or not isinstance(value, (int, str, bytes, type(None))):
        raise TypeError(
            f"guarded value for {binding.identity!r} must be int, str, bytes, None "
            f"or MinorMoney; got {type(value).__name__}."
        )
    return value


class SQLiteUnitOfWork:
    """One open ``BEGIN IMMEDIATE`` transaction on one SQLite connection."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        transaction: str,
        resources: Mapping[str, ResourceBinding],
    ) -> None:
        self._connection = connection
        self._transaction = transaction
        self._resources = resources
        self._closed = False

    @property
    def transaction(self) -> str:
        return self._transaction

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("the unit of work is closed.")

    def apply(self, write: GuardedWrite) -> ApplyResult:
        """Run one guarded ``UPDATE``; a mismatch changes nothing."""
        self._require_open()
        binding = self._resources.get(write.resource)
        if binding is None:
            raise UnknownResource(f"no adapter mapping for resource {write.resource!r}.")
        allowed = set(binding.columns)
        for column in [item.column for item in write.changes] + [
            item.column for item in write.conditions
        ]:
            if column not in allowed:
                raise InvalidColumn(
                    f"column {column!r} is not mapped for resource {binding.identity!r}."
                )

        assignments: list[str] = []
        parameters: list[object] = []
        for change in write.changes:
            if change.op == "add":
                assignments.append(f"{change.column} = {change.column} + ?")
            else:
                assignments.append(f"{change.column} = ?")
            parameters.append(_encode(change.value, binding))
        assignments.append(
            f"{binding.version_column} = {binding.version_column} + 1"
        )

        predicates = [f"{binding.key_column} = ?", f"{binding.version_column} = ?"]
        parameters.extend([write.key, write.expected_version])
        for condition in write.conditions:
            predicates.append(
                f"{condition.column} {_COMPARE_SQL[condition.op]} ?"
            )
            parameters.append(_encode(condition.value, binding))

        statement = (
            f"UPDATE {binding.table} SET {', '.join(assignments)} "
            f"WHERE {' AND '.join(predicates)}"
        )
        cursor = self._connection.execute(statement, parameters)
        result = ApplyResult(
            resource=write.resource,
            key=write.key,
            rowcount=cursor.rowcount,
            transaction=self._transaction,
        )
        if cursor.rowcount != 1:
            raise StalePlan(
                write.resource,
                write.key,
                write.expected_version,
                cursor.rowcount,
                self._transaction,
            )
        return result

    def commit(self) -> None:
        self._require_open()
        self._connection.commit()
        self._closed = True

    def rollback(self) -> None:
        if self._closed:
            return
        if self._connection.in_transaction:
            self._connection.rollback()
        self._closed = True

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True


class SQLiteProvider:
    """Opens the bound session as one file-backed SQLite transaction."""

    def __init__(
        self,
        database: str | Path,
        session: str,
        resources: Sequence[ResourceBinding],
    ) -> None:
        self.database = Path(database)
        self.session = _require_text(session, "session")
        bindings = tuple(resources)
        self.resources: dict[str, ResourceBinding] = {}
        for binding in bindings:
            if binding.identity in self.resources:
                raise ValueError(f"resource {binding.identity!r} is mapped twice.")
            self.resources[binding.identity] = binding

    def begin(self, plan: SessionPlan) -> UnitOfWork:
        """Open ``BEGIN IMMEDIATE`` only if the plan names this exact session."""
        if plan.session != self.session:
            raise SessionMismatch(
                f"bound session {plan.session!r} is not the session "
                f"{self.session!r} this provider opens."
            )
        for resource in plan.writes:
            if resource.identity not in self.resources:
                raise UnknownResource(
                    f"bound write {resource.identity!r} has no adapter mapping."
                )
        connection = sqlite3.connect(self.database, timeout=10.0, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("BEGIN IMMEDIATE")
        except BaseException:
            connection.close()
            raise
        transaction = f"{self.session}#{id(connection):x}"
        return SQLiteUnitOfWork(connection, transaction, self.resources)


__all__ = [
    "CurrencyMismatch",
    "InvalidColumn",
    "ResourceBinding",
    "SQLiteProvider",
    "SQLiteUnitOfWork",
    "UnknownResource",
]
