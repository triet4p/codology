"""SQLite adapter: one file-backed session, one physical transaction, guarded writes."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
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
from codology.query import (
    AllOf,
    Comparison,
    LinkBinding,
    QueryPage,
    QueryPredicate,
    QueryRequest,
    QueryRow,
    UnsupportedSecureQuery,
    issue_cursor,
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
    """Physical placement of one declared resource version inside the session file."""

    identity: str
    version: str
    table: str
    columns: tuple[str, ...]
    key_column: str = "id"
    version_column: str = "version"
    currency: str | None = None
    tenant_column: str | None = None
    scope_column: str | None = None
    links: tuple[LinkBinding, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.identity, "ResourceBinding.identity")
        _require_text(self.version, "ResourceBinding.version")
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
        if self.tenant_column is not None:
            _identifier(self.tenant_column, "ResourceBinding.tenant_column")
        if self.scope_column is not None:
            _identifier(self.scope_column, "ResourceBinding.scope_column")
        links = tuple(self.links)
        seen: set[str] = set()
        for link in links:
            if link.name in seen:
                raise ValueError(f"link {link.name!r} is mapped twice on {self.identity!r}.")
            seen.add(link.name)
            _identifier(link.name, "ResourceBinding.links name")
            _identifier(link.foreign_key, "ResourceBinding.links foreign key")
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "links", links)


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


def _pushdown_predicate(
    predicate: QueryPredicate,
    readable: tuple[str, ...],
    binding: ResourceBinding,
) -> tuple[str, tuple[object, ...]]:
    if isinstance(predicate, Comparison):
        if predicate.field not in readable or predicate.op not in _COMPARE_SQL:
            raise UnsupportedSecureQuery(
                f"predicate on {predicate.field!r} with {predicate.op!r} has no verified pushdown."
            )
        column = _identifier(predicate.field, "predicate field")
        return f"{column} {_COMPARE_SQL[predicate.op]} ?", (_encode(predicate.value, binding),)
    if type(predicate) is AllOf:
        clauses: list[str] = []
        values: list[object] = []
        for part in predicate.parts:
            clause, part_values = _pushdown_predicate(part, readable, binding)
            clauses.append(clause)
            values.extend(part_values)
        return f"({' AND '.join(clauses)})", tuple(values)
    raise UnsupportedSecureQuery(f"unsupported predicate type {type(predicate).__name__}.")


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
        assignments.append(f"{binding.version_column} = {binding.version_column} + 1")

        predicates = [f"{binding.key_column} = ?", f"{binding.version_column} = ?"]
        parameters.extend([write.key, write.expected_version])
        for condition in write.conditions:
            predicates.append(f"{condition.column} {_COMPARE_SQL[condition.op]} ?")
            parameters.append(_encode(condition.value, binding))

        statement = (
            f"UPDATE {binding.table} SET {', '.join(assignments)} WHERE {' AND '.join(predicates)}"
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
                raise UnknownResource(f"bound write {resource.identity!r} has no adapter mapping.")
        connection = sqlite3.connect(self.database, timeout=10.0, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("BEGIN IMMEDIATE")
        except BaseException:
            connection.close()
            raise
        transaction = f"{self.session}#{id(connection):x}"
        return SQLiteUnitOfWork(connection, transaction, self.resources)

    def fetch(self, request: QueryRequest) -> QueryPage[object]:
        """Answer one authorized query with a single policy-filtered read."""
        binding = self.resources.get(request.definition.identity)
        if binding is None or binding.version != request.definition.version:
            raise UnsupportedSecureQuery(
                f"no conformance-proven read mapping for "
                f"{request.definition.identity!r}@{request.definition.version!r}."
            )
        if request.traverse is not None:
            link = next((item for item in binding.links if item.name == request.traverse), None)
            if link is None:
                raise UnsupportedSecureQuery(
                    f"link {request.traverse!r} is not mapped for {request.definition.identity!r}."
                )
            if link.traversal == "internal":
                raise UnsupportedSecureQuery(
                    f"link {request.traverse!r} is internal and is never traversable."
                )
            raise UnsupportedSecureQuery(
                f"navigable link {request.traverse!r} has no conformance-proven pushdown "
                "in this adapter."
            )
        if binding.tenant_column is None or binding.scope_column is None:
            raise UnsupportedSecureQuery(
                f"resource {binding.identity!r} has no tenant/scope read mapping."
            )

        key_column = _identifier(binding.key_column, "key column")
        version_column = _identifier(binding.version_column, "version column")
        tenant_column = _identifier(binding.tenant_column, "tenant column")
        scope_column = _identifier(binding.scope_column, "scope column")
        order_column = _identifier(request.order.field, "order column")
        table = _identifier(binding.table, "table")
        selected = tuple(
            dict.fromkeys(
                [
                    key_column,
                    version_column,
                    *binding.columns,
                    tenant_column,
                    scope_column,
                    order_column,
                ]
            )
        )
        readable = selected

        predicates = [f"{tenant_column} = ?"]
        parameters: list[object] = [request.grant.tenant]
        placeholders = ", ".join("?" for _ in request.grant.scopes)
        predicates.append(f"{scope_column} IN ({placeholders})")
        parameters.extend(request.grant.scopes)
        if order_column != key_column:
            predicates.append(f"{order_column} IS NOT NULL")
        if request.predicate is not None:
            clause, values = _pushdown_predicate(request.predicate, readable, binding)
            predicates.append(clause)
            parameters.extend(values)
        filtered_where = " AND ".join(predicates)
        filtered_parameters = tuple(parameters)

        paged_where = filtered_where
        if request.after is not None:
            operator = ">" if request.order.direction == "asc" else "<"
            paged_where = (
                f"{filtered_where} AND "
                f"({order_column} {operator} ? OR "
                f"({order_column} = ? AND {key_column} > ?))"
            )
            parameters.extend(
                [request.after.order_value, request.after.order_value, request.after.key]
            )
        direction = "ASC" if request.order.direction == "asc" else "DESC"
        statement = (
            f"SELECT {', '.join(selected)} FROM {table} WHERE {paged_where} "
            f"ORDER BY {order_column} {direction}, {key_column} ASC LIMIT ?"
        )

        count: int | None = None
        with closing(sqlite3.connect(self.database, timeout=10.0, isolation_level=None)) as conn:
            conn.execute("PRAGMA query_only = ON")
            if request.count_requested:
                found = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {filtered_where}",
                    filtered_parameters,
                ).fetchone()
                assert found is not None
                count = int(found[0])
            fetched = conn.execute(statement, (*parameters, request.limit + 1)).fetchall()

        page = fetched[: request.limit]
        rows = tuple(
            QueryRow.issue(
                request.definition,
                str(record[selected.index(key_column)]),
                int(record[selected.index(version_column)]),
                {name: record[index] for index, name in enumerate(selected)},
            )
            for record in page
        )
        next_cursor: str | None = None
        if len(fetched) > request.limit and rows:
            next_cursor = issue_cursor(
                request.cursor_scope,
                page[-1][selected.index(order_column)],
                rows[-1].key,
            )
        return QueryPage(rows=rows, count=count, next_cursor=next_cursor)


__all__ = [
    "CurrencyMismatch",
    "InvalidColumn",
    "ResourceBinding",
    "SQLiteProvider",
    "SQLiteUnitOfWork",
    "UnknownResource",
]
