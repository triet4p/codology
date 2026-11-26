"""Durable waiting state recorded by the invoke gate.

A declaration may carry a structured approval rule. The engine runs the handler
once as an in-memory preview, evaluates that rule against the values the preview
already resolved, and either continues to the atomic commit or discards the
preview and persists a waiting execution. This module owns the portable form of
that waiting execution: its canonical input, the pinned manifest, the material
intent the approver is shown, and the approval the engine requires.

No domain policy lives here. The amount threshold, the approver role and the
self-approval rule come from the declaration; the deadline is a mechanism the
host may override. Nothing in this module opens a transaction or keeps a lock:
storage and commit belong to the engine and the bound adapter.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast

from codology.binding import SessionPlan
from codology.declarations.behavior import (
    AllOf,
    AnyOf,
    Approval,
    Comparison,
    FieldRef,
    Predicate,
)
from codology.declarations.behavior import (
    Literal as PredicateLiteral,
)
from codology.ledger import (
    DuplicateRequest,
    LedgerEntry,
    LedgerUnitOfWork,
    RequestScope,
    deserialize,
    serialize,
)
from codology.linking import LinkedDeclarations
from codology.manifest import PinnedManifest, encode_manifest, manifest_digest, pin_manifest
from codology.ports import UnitOfWork
from codology.query import Principal
from codology.snapshot import DefinitionKey

AWAITING_STATUS: Literal["AWAITING_APPROVAL"] = "AWAITING_APPROVAL"
APPROVAL_TTL = timedelta(hours=24)

_COMPARISON_OPERATORS: frozenset[str] = frozenset({">", ">=", "<", "<=", "==", "!="})


class UnsupportedComparison(ValueError):
    """A declared predicate cannot be evaluated safely against the resolved input."""


class InvalidAwaitingRecord(ValueError):
    """A stored waiting document is malformed and must not be trusted."""


@dataclass(frozen=True, slots=True)
class ComparisonValue:
    """One field path and the value the preview observed at that path."""

    parameter: str
    path: tuple[str, ...]
    value: object

    def document(self) -> dict[str, object]:
        return {"parameter": self.parameter, "path": list(self.path), "value": self.value}


@dataclass(frozen=True, slots=True)
class ObjectVersion:
    """The live instance version of one resolved object the intent depends on."""

    identity: str
    key: str
    version: int

    def document(self) -> dict[str, object]:
        return {"identity": self.identity, "key": self.key, "version": self.version}


@dataclass(frozen=True, slots=True)
class MaterialIntent:
    """The durable content an approval is bound to, never a handler result."""

    canonical_input: Mapping[str, object]
    comparisons: tuple[ComparisonValue, ...]
    object_versions: tuple[ObjectVersion, ...]
    pinned_manifest: str
    manifest_digest: str
    children: tuple[str, ...]
    fingerprint: str
    cycle: int = 0

    @property
    def child_keys(self) -> tuple[DefinitionKey, ...]:
        """The pinned child revisions, without their digests, for consumers."""
        keys: list[DefinitionKey] = []
        for item in self.children:
            identity, version = item.split("#", 1)[0].rsplit("@", 1)
            keys.append(DefinitionKey(identity, version))
        return tuple(keys)

    def document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "canonical_input": self.canonical_input,
            "comparisons": [item.document() for item in self.comparisons],
            "object_versions": [item.document() for item in self.object_versions],
            "pinned_manifest": self.pinned_manifest,
            "manifest_digest": self.manifest_digest,
            "children": list(self.children),
            "fingerprint": self.fingerprint,
        }
        if self.cycle:
            document["cycle"] = self.cycle
        return document


@dataclass(frozen=True, slots=True)
class RequiredApproval:
    """The authority the engine still needs before it may commit."""

    approval_id: str
    role: str
    tenant: str
    scope: tuple[str, ...]
    requester: Principal
    expires_at: str
    self_approval: bool
    intent_fingerprint: str
    callback_key: str
    permission: str = ""

    def document(self) -> dict[str, object]:
        return {
            "approval_id": self.approval_id,
            "role": self.role,
            "tenant": self.tenant,
            "scope": list(self.scope),
            "requester": {
                "identity": self.requester.identity,
                "tenant": self.requester.tenant,
                "permissions": tuple(sorted(self.requester.permissions)),
            },
            "expires_at": self.expires_at,
            "self_approval": self.self_approval,
            "intent_fingerprint": self.intent_fingerprint,
            "callback_key": self.callback_key,
            "permission": self.permission,
        }


@dataclass(frozen=True, slots=True)
class AwaitingExecution:
    """One execution parked at the invoke gate, portable across restarts."""

    execution_id: str
    action: DefinitionKey
    requester: Principal
    canonical_input: Mapping[str, object]
    pinned_manifest: str
    material_intent: MaterialIntent
    required_approval: RequiredApproval
    created_at: str

    def document(self) -> dict[str, object]:
        return {
            "execution_id": self.execution_id,
            "action": {"identity": self.action.identity, "version": self.action.version},
            "requester": self.required_approval.document()["requester"],
            "canonical_input": self.canonical_input,
            "pinned_manifest": self.pinned_manifest,
            "material_intent": self.material_intent.document(),
            "required_approval": self.required_approval.document(),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class PredicateEvaluation:
    """Whether the approval rule fired and which values it compared."""

    matches: bool
    comparisons: tuple[ComparisonValue, ...]


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        if name in value:
            return cast(object, value[name])
        raise UnsupportedComparison(f"the compared value has no field {name!r}.")
    try:
        return getattr(value, name)
    except AttributeError as exc:
        raise UnsupportedComparison(f"the compared value has no field {name!r}.") from exc


def _operand_value(operand: FieldRef | PredicateLiteral, arguments: Mapping[str, object]) -> object:
    if isinstance(operand, PredicateLiteral):
        return operand.value
    if operand.parameter not in arguments:
        raise UnsupportedComparison(f"the predicate names unknown parameter {operand.parameter!r}.")
    value = arguments[operand.parameter]
    for part in operand.path:
        value = _field(value, part)
    return value


def _compare(operator: str, left: object, right: object) -> bool:
    if operator not in _COMPARISON_OPERATORS:
        raise UnsupportedComparison(f"unsupported comparison operator {operator!r}.")
    try:
        if operator == ">":
            return bool(left > right)  # type: ignore[operator]
        if operator == ">=":
            return bool(left >= right)  # type: ignore[operator]
        if operator == "<":
            return bool(left < right)  # type: ignore[operator]
        if operator == "<=":
            return bool(left <= right)  # type: ignore[operator]
        if operator == "==":
            return bool(left == right)
        return bool(left != right)
    except TypeError as exc:
        raise UnsupportedComparison(
            f"cannot compare {type(left).__name__} with {type(right).__name__}."
        ) from exc


def _evaluate(
    predicate: Predicate,
    arguments: Mapping[str, object],
    comparisons: list[ComparisonValue],
) -> bool:
    if isinstance(predicate, Comparison):
        left = _operand_value(predicate.left, arguments)
        right = _operand_value(predicate.right, arguments)
        comparisons.append(ComparisonValue(predicate.left.parameter, predicate.left.path, left))
        if isinstance(predicate.right, FieldRef):
            comparisons.append(
                ComparisonValue(predicate.right.parameter, predicate.right.path, right)
            )
        return _compare(predicate.operator, left, right)
    if isinstance(predicate, AllOf):
        return all(_evaluate(part, arguments, comparisons) for part in predicate.parts)
    if isinstance(predicate, AnyOf):
        return any(_evaluate(part, arguments, comparisons) for part in predicate.parts)
    return not _evaluate(predicate.operand, arguments, comparisons)


def evaluate_predicate(
    predicate: Predicate, arguments: Mapping[str, object]
) -> PredicateEvaluation:
    """Evaluate a structured rule on already resolved, authorized arguments."""
    comparisons: list[ComparisonValue] = []
    matches = _evaluate(predicate, arguments, comparisons)
    return PredicateEvaluation(matches, tuple(comparisons))


def build_material_intent(
    *,
    canonical_input: Mapping[str, object],
    comparisons: tuple[ComparisonValue, ...],
    object_versions: tuple[ObjectVersion, ...],
    pinned: PinnedManifest,
    cycle: int = 0,
) -> MaterialIntent:
    """Freeze what the approver sees, using the manifest T1 already pinned."""
    if type(cycle) is not int or cycle < 0:
        raise ValueError("a material intent cycle must be a non-negative integer.")
    children = tuple(f"{item.identity}@{item.version}#{item.digest}" for item in pinned.children)
    intent = MaterialIntent(
        canonical_input,
        comparisons,
        object_versions,
        encode_manifest(pinned),
        manifest_digest(pinned),
        children,
        "",
        cycle,
    )
    digest = hashlib.sha256(serialize({"material_intent": intent.document()}).encode("utf-8"))
    return MaterialIntent(
        intent.canonical_input,
        intent.comparisons,
        intent.object_versions,
        intent.pinned_manifest,
        intent.manifest_digest,
        intent.children,
        digest.hexdigest(),
        cycle,
    )


def approval_deadline(expires_at: str | None, *, now: datetime | None = None) -> str:
    """Return a UTC ISO deadline; the host may supply its own validity window."""
    if expires_at is None:
        moment = (now or datetime.now(UTC)) + APPROVAL_TTL
    else:
        if not expires_at.strip():
            raise ValueError("approval_expires_at must be a non-empty ISO timestamp.")
        raw = expires_at.strip().replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("approval_expires_at must be an ISO timestamp.") from exc
        if moment.tzinfo is None:
            raise ValueError("approval_expires_at must carry a time zone.")
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def new_approval(
    *,
    role: str,
    tenant: str,
    scope: tuple[str, ...],
    requester: Principal,
    expires_at: str,
    self_approval: bool,
    intent_fingerprint: str,
    execution_id: str,
    permission: str = "",
) -> RequiredApproval:
    """Mint one approval identity and the callback key derived from it."""
    approval_id = "AP-" + uuid.uuid4().hex
    return RequiredApproval(
        approval_id,
        role,
        tenant,
        tuple(sorted(set(scope))),
        requester,
        expires_at,
        self_approval,
        intent_fingerprint,
        f"{execution_id}:{approval_id}",
        permission,
    )


def encode_awaiting(execution: AwaitingExecution) -> str:
    """Encode one waiting execution as the canonical ledger payload."""
    return serialize(execution.document())


def encode_approval(approval: RequiredApproval) -> str:
    """Encode one approval requirement beside the decision it authorizes."""
    return serialize(approval.document())


def decode_approval(payload: str) -> RequiredApproval | None:
    """Decode a pinned approval, returning None when it cannot be trusted."""
    document = deserialize(payload)
    if document is None:
        return None
    try:
        decoded = _decode_required_approval(document)
    except (InvalidAwaitingRecord, KeyError, TypeError, ValueError):
        return None
    return decoded


def _exact(document: Mapping[str, object], keys: frozenset[str], label: str) -> None:
    if frozenset(document) != keys:
        raise InvalidAwaitingRecord(f"{label} has unexpected or missing fields.")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidAwaitingRecord(f"{label} must be a non-empty string.")
    return value


def _principal(value: object, label: str) -> Principal:
    document = _as_document(value, label)
    _exact(document, frozenset({"identity", "tenant", "permissions"}), label)
    permissions = _sequence(document["permissions"], f"{label}.permissions")
    return Principal(
        _text(document["identity"], f"{label}.identity"),
        _text(document["tenant"], f"{label}.tenant"),
        frozenset(_text(item, f"{label}.permission") for item in permissions),
    )


def _as_document(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise InvalidAwaitingRecord(f"{label} must be a document.")
    return cast(Mapping[str, object], value)


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise InvalidAwaitingRecord(f"{label} must be a sequence.")
    return cast(Sequence[object], value)


def _decode_comparison(value: object) -> ComparisonValue:
    document = _as_document(value, "comparison")
    _exact(document, frozenset({"parameter", "path", "value"}), "comparison")
    path = tuple(
        _text(item, "comparison.path") for item in _sequence(document["path"], "comparison.path")
    )
    return ComparisonValue(
        _text(document["parameter"], "comparison.parameter"), path, document["value"]
    )


def _decode_object_version(value: object) -> ObjectVersion:
    document = _as_document(value, "object_version")
    _exact(document, frozenset({"identity", "key", "version"}), "object_version")
    version = document["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise InvalidAwaitingRecord("object_version.version must be an integer.")
    return ObjectVersion(
        _text(document["identity"], "object_version.identity"),
        _text(document["key"], "object_version.key"),
        version,
    )


def _decode_material_intent(value: object) -> MaterialIntent:
    document = _as_document(value, "material_intent")
    keys = frozenset(document)
    required = frozenset(
        {
            "canonical_input",
            "comparisons",
            "object_versions",
            "pinned_manifest",
            "manifest_digest",
            "children",
            "fingerprint",
        }
    )
    if keys not in (required, required | {"cycle"}):
        raise InvalidAwaitingRecord("material_intent has unexpected or missing fields.")
    canonical = _as_document(document["canonical_input"], "material_intent.canonical_input")
    comparisons = tuple(
        _decode_comparison(item)
        for item in _sequence(document["comparisons"], "material_intent.comparisons")
    )
    versions = tuple(
        _decode_object_version(item)
        for item in _sequence(document["object_versions"], "material_intent.object_versions")
    )
    children = tuple(
        _text(item, "material_intent.children")
        for item in _sequence(document["children"], "material_intent.children")
    )
    cycle = document.get("cycle", 0)
    if type(cycle) is not int or cycle < 0:
        raise InvalidAwaitingRecord("material_intent.cycle must be a non-negative integer.")
    return MaterialIntent(
        canonical,
        comparisons,
        versions,
        _text(document["pinned_manifest"], "material_intent.pinned_manifest"),
        _text(document["manifest_digest"], "material_intent.manifest_digest"),
        children,
        _text(document["fingerprint"], "material_intent.fingerprint"),
        cycle,
    )


def _decode_required_approval(value: object) -> RequiredApproval:
    document = _as_document(value, "required_approval")
    keys = frozenset(document)
    required_keys = frozenset(
        {
            "approval_id",
            "role",
            "tenant",
            "scope",
            "requester",
            "expires_at",
            "self_approval",
            "intent_fingerprint",
            "callback_key",
        }
    )
    if keys not in (required_keys, required_keys | {"permission"}):
        raise InvalidAwaitingRecord("required_approval has unexpected or missing fields.")
    scope = tuple(
        _text(item, "required_approval.scope")
        for item in _sequence(document["scope"], "required_approval.scope")
    )
    self_approval = document["self_approval"]
    if not isinstance(self_approval, bool):
        raise InvalidAwaitingRecord("required_approval.self_approval must be a boolean.")
    return RequiredApproval(
        _text(document["approval_id"], "required_approval.approval_id"),
        _text(document["role"], "required_approval.role"),
        _text(document["tenant"], "required_approval.tenant"),
        scope,
        _principal(document["requester"], "required_approval.requester"),
        _text(document["expires_at"], "required_approval.expires_at"),
        self_approval,
        _text(document["intent_fingerprint"], "required_approval.intent_fingerprint"),
        _text(document["callback_key"], "required_approval.callback_key"),
        (
            _text(document["permission"], "required_approval.permission")
            if "permission" in document
            else ""
        ),
    )


def decode_awaiting(payload: str) -> AwaitingExecution | None:
    """Decode a waiting execution, returning None when it cannot be trusted."""
    document = deserialize(payload)
    if document is None:
        return None
    try:
        _exact(
            document,
            frozenset(
                {
                    "execution_id",
                    "action",
                    "requester",
                    "canonical_input",
                    "pinned_manifest",
                    "material_intent",
                    "required_approval",
                    "created_at",
                }
            ),
            "awaiting",
        )
        action = _as_document(document["action"], "awaiting.action")
        _exact(action, frozenset({"identity", "version"}), "awaiting.action")
        intent = _decode_material_intent(document["material_intent"])
        required = _decode_required_approval(document["required_approval"])
        canonical = _as_document(document["canonical_input"], "awaiting.canonical_input")
        return AwaitingExecution(
            _text(document["execution_id"], "awaiting.execution_id"),
            DefinitionKey(
                _text(action["identity"], "awaiting.action.identity"),
                _text(action["version"], "awaiting.action.version"),
            ),
            _principal(document["requester"], "awaiting.requester"),
            canonical,
            _text(document["pinned_manifest"], "awaiting.pinned_manifest"),
            intent,
            required,
            _text(document["created_at"], "awaiting.created_at"),
        )
    except (InvalidAwaitingRecord, KeyError, TypeError, ValueError):
        return None


class WaitingProvider(Protocol):
    """The part of a transaction provider the waiting gate needs."""

    def begin(self, plan: SessionPlan) -> UnitOfWork: ...

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None: ...


def build_awaiting(
    *,
    approval: Approval,
    arguments: Mapping[str, object],
    canonical_input: Mapping[str, object],
    object_versions: tuple[ObjectVersion, ...],
    linked: LinkedDeclarations,
    action: DefinitionKey,
    principal: Principal,
    scopes: tuple[str, ...],
    expires_at: str | None,
    permission: str,
) -> AwaitingExecution | None:
    """Freeze a waiting execution when the declaration's predicate fires."""
    evaluation = evaluate_predicate(approval.when, arguments)
    if not evaluation.matches:
        return None
    pinned = pin_manifest(linked, action)
    intent = build_material_intent(
        canonical_input=canonical_input,
        comparisons=evaluation.comparisons,
        object_versions=object_versions,
        pinned=pinned,
    )
    moment = datetime.now(UTC)
    execution_id = uuid.uuid4().hex
    required = new_approval(
        role=approval.role,
        tenant=principal.tenant,
        scope=scopes,
        requester=principal,
        expires_at=approval_deadline(expires_at, now=moment),
        self_approval=approval.self_approval,
        intent_fingerprint=intent.fingerprint,
        execution_id=execution_id,
        permission=permission,
    )
    return AwaitingExecution(
        execution_id,
        action,
        principal,
        canonical_input,
        encode_manifest(pinned),
        intent,
        required,
        moment.isoformat().replace("+00:00", "Z"),
    )


def claim_awaiting_key(
    provider: WaitingProvider,
    plan: SessionPlan,
    scope: RequestScope,
    request_key: str,
    fingerprint: str,
    action_version: str,
    execution: AwaitingExecution,
) -> LedgerEntry | None:
    """Claim one ledger key, or return the entry another invoke already claimed."""
    unit = provider.begin(plan)
    try:
        ledger = cast(LedgerUnitOfWork, unit)
        existing = ledger.lookup(scope, request_key)
        if existing is not None:
            return existing
        ledger.record(
            LedgerEntry(
                scope,
                request_key,
                fingerprint,
                execution.execution_id,
                action_version,
                AWAITING_STATUS,
                encode_awaiting(execution),
            )
        )
        unit.commit()
        return None
    except DuplicateRequest:
        return provider.lookup(scope, request_key)
    finally:
        unit.close()


__all__ = [
    "APPROVAL_TTL",
    "AWAITING_STATUS",
    "AwaitingExecution",
    "ComparisonValue",
    "InvalidAwaitingRecord",
    "MaterialIntent",
    "ObjectVersion",
    "PredicateEvaluation",
    "RequiredApproval",
    "UnsupportedComparison",
    "approval_deadline",
    "build_material_intent",
    "decode_awaiting",
    "encode_awaiting",
    "decode_approval",
    "encode_approval",
    "evaluate_predicate",
    "new_approval",
]
