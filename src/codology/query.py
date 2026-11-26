"""Engine read boundary: authorize a query, push it down, then paginate and count.

A consumer never reads rows from an adapter directly. The engine checks the
principal's live read grant, accepts only a small predicate language with a
provable pushdown, and binds each cursor to the authorized query context. Rows
and counts are produced by the adapter from the same filtered set; the engine
adds no silent postfilter and exposes no unfiltered count.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, cast

from codology.money import MinorMoney
from codology.snapshot import DefinitionKey

CompareOp = Literal["==", "!=", ">", ">=", "<", "<="]
Direction = Literal["asc", "desc"]
TraversalKind = Literal["navigable", "internal"]

_COMPARE_OPS = frozenset({"==", "!=", ">", ">=", "<", "<="})
_DIRECTIONS = frozenset({"asc", "desc"})
_TRAVERSALS = frozenset({"navigable", "internal"})
_ISSUE_TOKEN = object()


class UnsupportedSecureQuery(ValueError):
    """A query cannot be answered without leaking rows outside the policy."""


class ReadDenied(PermissionError):
    """The principal does not hold the live read grant for this definition."""


class InvalidCursor(ValueError):
    """A cursor is malformed or belongs to a different authorized query."""


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated caller whose permissions are checked at query time."""

    identity: str
    tenant: str
    permissions: frozenset[str]

    def __post_init__(self) -> None:
        _require_text(self.identity, "Principal.identity")
        _require_text(self.tenant, "Principal.tenant")
        permissions = frozenset(self.permissions)
        for permission in permissions:
            _require_text(permission, "Principal.permissions entry")
        object.__setattr__(self, "permissions", permissions)


@dataclass(frozen=True, slots=True)
class ReadGrant:
    """Host-issued read authority, checked against the principal on every query."""

    principal: str
    definition: DefinitionKey
    tenant: str
    scopes: tuple[str, ...]
    permission: str

    def __post_init__(self) -> None:
        _require_text(self.principal, "ReadGrant.principal")
        if type(self.definition) is not DefinitionKey:
            raise TypeError("ReadGrant.definition must be a version-explicit DefinitionKey.")
        _require_text(self.tenant, "ReadGrant.tenant")
        _require_text(self.permission, "ReadGrant.permission")
        scopes = tuple(self.scopes)
        if not scopes:
            raise ValueError("ReadGrant.scopes must name at least one permitted scope.")
        for scope in scopes:
            _require_text(scope, "ReadGrant.scopes entry")
        object.__setattr__(self, "scopes", scopes)


@dataclass(frozen=True, slots=True)
class Comparison:
    """One supported, fully pushdown-able field comparison."""

    field: str
    op: CompareOp
    value: object

    def __post_init__(self) -> None:
        _require_text(self.field, "Comparison.field")
        if self.op not in _COMPARE_OPS:
            raise UnsupportedSecureQuery(
                f"comparison operator {self.op!r} has no verified pushdown."
            )
        if not _is_scalar(self.value):
            raise UnsupportedSecureQuery("comparison values must be str, int, None or MinorMoney.")


@dataclass(frozen=True, slots=True)
class AllOf:
    """Conjunction of supported comparisons."""

    parts: tuple[QueryPredicate, ...]

    def __post_init__(self) -> None:
        parts = tuple(self.parts)
        if not parts:
            raise UnsupportedSecureQuery("all_of needs at least one predicate.")
        for part in parts:
            if type(part) is not Comparison and type(part) is not AllOf:
                raise UnsupportedSecureQuery(f"unsupported predicate node {type(part).__name__}.")
        object.__setattr__(self, "parts", parts)


type QueryPredicate = Comparison | AllOf


@dataclass(frozen=True, slots=True)
class OrderBy:
    """Explicit total-order prefix; the adapter always adds the key as tie-break."""

    field: str
    direction: Direction = "asc"

    def __post_init__(self) -> None:
        _require_text(self.field, "OrderBy.field")
        if self.direction not in _DIRECTIONS:
            raise UnsupportedSecureQuery(f"unsupported sort direction {self.direction!r}.")


@dataclass(frozen=True, slots=True)
class LinkBinding:
    """Declared traversal kind for one link of a mapped resource."""

    name: str
    target: DefinitionKey
    traversal: TraversalKind
    foreign_key: str

    def __post_init__(self) -> None:
        _require_text(self.name, "LinkBinding.name")
        _require_text(self.foreign_key, "LinkBinding.foreign_key")
        if self.traversal not in _TRAVERSALS:
            raise ValueError(f"unsupported traversal kind {self.traversal!r}.")


@dataclass(frozen=True, slots=True)
class VersionedRef[T]:
    """Reference issued from an authorized row: definition, version and row version."""

    definition: DefinitionKey
    key: str
    instance_version: int
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _ISSUE_TOKEN:
            raise ValueError("references are issued by authorized query rows only.")
        if type(self.definition) is not DefinitionKey:
            raise TypeError("VersionedRef.definition must be a DefinitionKey.")
        _require_text(self.key, "VersionedRef.key")
        if type(self.instance_version) is not int:
            raise TypeError("VersionedRef.instance_version must be an integer.")

    @classmethod
    def issue(
        cls,
        definition: DefinitionKey,
        key: str,
        instance_version: int,
    ) -> VersionedRef[object]:
        """Issue a ref from a row; in-process only, carrying no authority by itself."""
        return cls(definition, key, instance_version, _ISSUE_TOKEN)


@dataclass(frozen=True, slots=True)
class QueryRow[T]:
    """One authorized row; ``as_ref`` is the only way to obtain a versioned ref."""

    definition: DefinitionKey
    key: str
    instance_version: int
    values: Mapping[str, object]
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _ISSUE_TOKEN:
            raise ValueError("query rows are issued by the query adapter only.")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @classmethod
    def issue(
        cls,
        definition: DefinitionKey,
        key: str,
        instance_version: int,
        values: Mapping[str, object],
    ) -> QueryRow[object]:
        return cls(definition, key, instance_version, values, _ISSUE_TOKEN)

    def as_ref(self) -> VersionedRef[T]:
        return cast(
            VersionedRef[T],
            VersionedRef.issue(self.definition, self.key, self.instance_version),
        )


@dataclass(frozen=True, slots=True)
class QueryPage[T]:
    """Rows, optional filtered count, and an opaque cursor for the next page."""

    rows: tuple[QueryRow[T], ...]
    count: int | None
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class CursorPosition:
    """The last row's order value and key, decoded from an opaque cursor."""

    order_value: str | int
    key: str


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """The complete, already-authorized request handed to a read adapter."""

    definition: DefinitionKey
    grant: ReadGrant
    predicate: QueryPredicate | None
    order: OrderBy
    after: CursorPosition | None
    limit: int
    count_requested: bool
    traverse: str | None
    cursor_scope: str


class SecureQueryProvider(Protocol):
    """Core-owned read port: fetch only rows allowed by the request's grant."""

    def fetch(self, request: QueryRequest) -> QueryPage[object]:
        """Return policy-filtered rows and count; never expose a raw query."""
        ...


def query[T](
    *,
    provider: SecureQueryProvider,
    principal: Principal,
    grant: ReadGrant,
    from_: DefinitionKey,
    target: type[T],
    order: OrderBy,
    predicate: QueryPredicate | None = None,
    cursor: str | None = None,
    limit: int = 20,
    count_requested: bool = False,
    traverse: str | None = None,
) -> QueryPage[T]:
    """Authorize, validate and push down one typed read of the allowed set."""
    _authorize(principal, grant, from_)
    if (
        getattr(target, "identity", None) != from_.identity
        or getattr(target, "version", None) != from_.version
    ):
        raise UnsupportedSecureQuery(
            f"target type does not match {from_.identity!r}@{from_.version!r}."
        )
    if type(limit) is not int or limit < 1:
        raise UnsupportedSecureQuery("limit must be a positive integer.")
    if predicate is not None:
        _validate_predicate(predicate)
    if traverse is not None:
        _require_text(traverse, "traverse")

    scope = _cursor_scope(from_, grant, predicate, order, traverse)
    after = _decode_cursor(cursor, scope) if cursor is not None else None
    request = QueryRequest(
        definition=from_,
        grant=grant,
        predicate=predicate,
        order=order,
        after=after,
        limit=limit,
        count_requested=count_requested,
        traverse=traverse,
        cursor_scope=scope,
    )
    page = provider.fetch(request)
    if page.next_cursor is not None:
        _decode_cursor(page.next_cursor, scope)
    return cast(QueryPage[T], page)


def issue_cursor(scope: str, order_value: object, key: str) -> str:
    """Create an opaque cursor bound to one authorized query context."""
    if type(order_value) is not str and type(order_value) is not int:
        raise UnsupportedSecureQuery("a cursor needs a str or int order value.")
    _require_text(key, "cursor key")
    payload = json.dumps(
        [scope, [order_value, key]], separators=(",", ":"), ensure_ascii=False
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _authorize(principal: Principal, grant: ReadGrant, from_: DefinitionKey) -> None:
    if (
        grant.principal != principal.identity
        or grant.tenant != principal.tenant
        or grant.definition != from_
        or grant.permission not in principal.permissions
    ):
        raise ReadDenied(
            f"principal {principal.identity!r} has no live read grant for "
            f"{from_.identity!r}@{from_.version!r}."
        )


def _is_scalar(value: object) -> bool:
    return value is None or (
        isinstance(value, str | int | MinorMoney) and not isinstance(value, bool)
    )


def _validate_predicate(predicate: QueryPredicate) -> None:
    if type(predicate) is Comparison:
        if predicate.op not in _COMPARE_OPS or not _is_scalar(predicate.value):
            raise UnsupportedSecureQuery("predicate has no verified pushdown.")
        return
    if type(predicate) is AllOf:
        for part in predicate.parts:
            _validate_predicate(part)
        return
    raise UnsupportedSecureQuery(f"unsupported predicate type {type(predicate).__name__}.")


def _canonical(value: object) -> object:
    if isinstance(value, MinorMoney):
        return {"money": [value.currency, value.minor]}
    if value is None or isinstance(value, str | int):
        return value
    raise UnsupportedSecureQuery("cursor context contains a non-canonical value.")


def _canonical_predicate(predicate: QueryPredicate | None) -> object:
    if predicate is None:
        return None
    if type(predicate) is Comparison:
        return ["cmp", predicate.field, predicate.op, _canonical(predicate.value)]
    if type(predicate) is AllOf:
        return ["all", [_canonical_predicate(part) for part in predicate.parts]]
    raise UnsupportedSecureQuery(f"unsupported predicate type {type(predicate).__name__}.")


def _cursor_scope(
    definition: DefinitionKey,
    grant: ReadGrant,
    predicate: QueryPredicate | None,
    order: OrderBy,
    traverse: str | None,
) -> str:
    payload = json.dumps(
        [
            [definition.identity, definition.version],
            [grant.principal, grant.tenant, list(grant.scopes), grant.permission],
            _canonical_predicate(predicate),
            [order.field, order.direction],
            traverse,
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _decode_cursor(cursor: str, scope: str) -> CursorPosition:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        found_scope, position = payload
        order_value, key = position
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursor("cursor is malformed.") from exc
    if found_scope != scope or not isinstance(key, str):
        raise InvalidCursor("cursor does not belong to this authorized query.")
    if type(order_value) is not str and type(order_value) is not int:
        raise InvalidCursor("cursor position is invalid.")
    return CursorPosition(order_value, key)


__all__ = [
    "AllOf",
    "Comparison",
    "CursorPosition",
    "InvalidCursor",
    "LinkBinding",
    "OrderBy",
    "Principal",
    "QueryPage",
    "QueryPredicate",
    "QueryRequest",
    "QueryRow",
    "ReadDenied",
    "ReadGrant",
    "SecureQueryProvider",
    "UnsupportedSecureQuery",
    "VersionedRef",
    "issue_cursor",
    "query",
]
