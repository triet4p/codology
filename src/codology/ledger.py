"""Core-owned request ledger for synchronous, durable invoke results.

A scoped request key and a canonical intent fingerprint travel with the
authoritative result. The uniqueness constraint and the result are stored by
the adapter in the same transaction as the business writes; a reader without a
trustworthy record gets no result and never infers a terminal business state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from codology.money import MinorMoney
from codology.ports import UnitOfWork
from codology.query import Principal, VersionedRef
from codology.snapshot import DefinitionKey

EXECUTION_READ_PERMISSION = "execution.read"

_MONEY_TAG = "__money__"
_DEFINITION_TAG = "__definition__"
_REF_TAG = "__ref__"


class UnsupportedIntent(ValueError):
    """An input has no canonical form, so no fingerprint may be claimed."""


class DuplicateRequest(Exception):
    """The scoped request key was already claimed by a committed record."""


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


@dataclass(frozen=True, slots=True)
class RequestScope:
    """The stability boundary of a key: tenant, requester and action identity."""

    tenant: str
    principal: str
    action: str

    def __post_init__(self) -> None:
        _require_text(self.tenant, "RequestScope.tenant")
        _require_text(self.principal, "RequestScope.principal")
        _require_text(self.action, "RequestScope.action")


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One authoritative committed result stored under a scoped request key."""

    scope: RequestScope
    request_key: str
    intent_fingerprint: str
    execution_id: str
    action_version: str
    status: Literal["COMMITTED"]
    payload: str

    def __post_init__(self) -> None:
        _require_text(self.request_key, "LedgerEntry.request_key")
        _require_text(self.intent_fingerprint, "LedgerEntry.intent_fingerprint")
        _require_text(self.execution_id, "LedgerEntry.execution_id")
        _require_text(self.action_version, "LedgerEntry.action_version")
        _require_text(self.payload, "LedgerEntry.payload")
        if self.status != "COMMITTED":
            raise ValueError("only an authoritative COMMITTED result is stored.")


class LedgerUnitOfWork(UnitOfWork, Protocol):
    """A transaction that can read and claim the ledger it commits with."""

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None: ...

    def record(self, entry: LedgerEntry) -> None: ...


class LedgerProvider(Protocol):
    """Read-only access to committed ledger records for reconciliation."""

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None: ...


def _as_mapping(value: object) -> dict[object, object] | None:
    if isinstance(value, dict):
        return cast(dict[object, object], value)
    return None


def _as_sequence(value: object) -> tuple[object, ...] | None:
    if isinstance(value, (list, tuple)):
        return cast(tuple[object, ...], value)
    return None


def canonicalize(value: object) -> object:
    """Give one value a single meaning, independent of Python container order."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, MinorMoney):
        return {_MONEY_TAG: [value.currency, value.minor]}
    if isinstance(value, DefinitionKey):
        return {_DEFINITION_TAG: [value.identity, value.version]}
    if isinstance(value, VersionedRef):
        return {_REF_TAG: [canonicalize(value.definition), value.key, value.instance_version]}
    document = _as_mapping(value)
    if document is not None:
        return {
            str(key): canonicalize(item)
            for key, item in sorted(document.items(), key=lambda pair: str(pair[0]))
        }
    sequence = _as_sequence(value)
    if sequence is not None:
        return [canonicalize(item) for item in sequence]
    raise UnsupportedIntent(f"no canonical form for {type(value).__name__}.")


def _restore(value: object) -> object:
    document = _as_mapping(value)
    if document is not None:
        if len(document) == 1 and _MONEY_TAG in document:
            parts = _as_sequence(document[_MONEY_TAG])
            if (
                parts is not None
                and len(parts) == 2
                and isinstance(parts[0], str)
                and isinstance(parts[1], int)
                and not isinstance(parts[1], bool)
            ):
                return MinorMoney(parts[0], parts[1])
            raise ValueError("a stored money value is malformed.")
        if len(document) == 1 and _DEFINITION_TAG in document:
            parts = _as_sequence(document[_DEFINITION_TAG])
            if (
                parts is not None
                and len(parts) == 2
                and isinstance(parts[0], str)
                and isinstance(parts[1], str)
            ):
                return DefinitionKey(parts[0], parts[1])
            raise ValueError("a stored definition value is malformed.")
        if _REF_TAG in document or len(document) != len({str(key) for key in document}):
            raise ValueError("a stored object value is malformed.")
        return {str(key): _restore(item) for key, item in document.items()}
    sequence = _as_sequence(value)
    if sequence is not None:
        return tuple(_restore(item) for item in sequence)
    return value


def serialize(document: Mapping[str, object]) -> str:
    """Encode a canonical document for storage or hashing."""
    return json.dumps(
        canonicalize(document), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def deserialize(payload: str) -> Mapping[str, object] | None:
    """Decode a stored document, or return None when it is not trustworthy."""
    try:
        decoded: object = json.loads(payload)
        document = _as_mapping(decoded)
        if document is None:
            return None
        return cast(Mapping[str, object], _restore(document))
    except (TypeError, ValueError, UnicodeError):
        return None


def intent_fingerprint(action: DefinitionKey, parameters: Mapping[str, object]) -> str:
    """Hash the canonical action and caller parameters, never a handler body."""
    document = {
        "action": {"identity": action.identity, "version": action.version},
        "parameters": dict(parameters),
    }
    return hashlib.sha256(serialize(document).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredChange:
    """One persisted mutation, with its exact assignment triples."""

    resource: str
    key: str
    version: int
    changes: tuple[tuple[str, str, object], ...]


@dataclass(frozen=True, slots=True)
class StoredResult:
    """The portable form of an authoritative execution result."""

    execution_id: str
    status: Literal["COMMITTED"]
    action: DefinitionKey
    requester: Principal
    committed: tuple[StoredChange, ...]
    children: tuple[DefinitionKey, ...]


def _stored_key(value: object) -> DefinitionKey:
    document = _as_mapping(value)
    if document is None:
        raise TypeError("a stored definition is not a document.")
    return DefinitionKey(str(document["identity"]), str(document["version"]))


def encode_result(result: StoredResult) -> str:
    """Serialize an authoritative result with canonical value encoding."""
    return serialize(
        {
            "execution_id": result.execution_id,
            "status": result.status,
            "action": {"identity": result.action.identity, "version": result.action.version},
            "requester": {
                "identity": result.requester.identity,
                "tenant": result.requester.tenant,
                "permissions": tuple(sorted(result.requester.permissions)),
            },
            "committed": [
                {
                    "resource": change.resource,
                    "key": change.key,
                    "version": change.version,
                    "changes": [
                        {"column": column, "op": op, "value": value}
                        for column, op, value in change.changes
                    ],
                }
                for change in result.committed
            ],
            "children": [
                {"identity": key.identity, "version": key.version} for key in result.children
            ],
        }
    )


def decode_result(payload: str) -> StoredResult | None:
    """Decode a stored result, or return None when it is not trustworthy."""
    document = deserialize(payload)
    if document is None:
        return None
    try:
        if document["status"] != "COMMITTED":
            return None
        requester = _as_mapping(document["requester"])
        if requester is None:
            return None
        permissions = _as_sequence(requester["permissions"])
        if permissions is None:
            return None
        principal = Principal(
            str(requester["identity"]),
            str(requester["tenant"]),
            frozenset(str(item) for item in permissions),
        )
        items = _as_sequence(document["committed"])
        if items is None:
            return None
        committed: list[StoredChange] = []
        for item in items:
            entry = _as_mapping(item)
            if entry is None:
                return None
            changes = _as_sequence(entry["changes"])
            if changes is None:
                return None
            assignments: list[tuple[str, str, object]] = []
            for change in changes:
                triple = _as_mapping(change)
                if triple is None:
                    return None
                assignments.append((str(triple["column"]), str(triple["op"]), triple["value"]))
            committed.append(
                StoredChange(
                    str(entry["resource"]),
                    str(entry["key"]),
                    int(str(entry["version"])),
                    tuple(assignments),
                )
            )
        stored_children = _as_sequence(document["children"])
        if stored_children is None:
            return None
        children = tuple(_stored_key(key) for key in stored_children)
        return StoredResult(
            str(document["execution_id"]),
            "COMMITTED",
            _stored_key(document["action"]),
            principal,
            tuple(committed),
            children,
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


__all__ = [
    "EXECUTION_READ_PERMISSION",
    "DuplicateRequest",
    "LedgerEntry",
    "LedgerProvider",
    "LedgerUnitOfWork",
    "RequestScope",
    "StoredChange",
    "StoredResult",
    "UnsupportedIntent",
    "canonicalize",
    "decode_result",
    "deserialize",
    "encode_result",
    "intent_fingerprint",
    "serialize",
]
