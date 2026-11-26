"""Core-owned outbox intents: typed snapshots, stable dedup and bound sessions.

An enqueue only registers a durable intent. Delivery is a separate concern:
nothing in this module sends a message, opens a network connection, or commits.
The engine hands the resulting intents to the one transaction that also owns
the business writes and the ledger, so an uncommitted preview cannot publish.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from codology.binding import BoundAction, BoundEffect, Capability
from codology.declarations import Action, Effect, Value
from codology.ledger import UnsupportedIntent, canonicalize, serialize
from codology.linking import LinkedDeclarations
from codology.ports import UnitOfWork
from codology.query import Principal
from codology.snapshot import DefinitionKey


class OutboxError(ValueError):
    """An outbox intent cannot be accepted without breaking its contract."""


class InvalidEffectDeclaration(OutboxError):
    """A declared effect has no typed payload or usable dedup contract."""


class UndeclaredEffect(OutboxError):
    """A handler tried to enqueue an effect its action did not declare."""


class InvalidEffectPayload(OutboxError):
    """An enqueue payload is not a typed snapshot of the declared value."""


class EffectNotBound(OutboxError):
    """The bound plan has no outbox capability, dedup store or shared session."""


class EffectConflict(OutboxError):
    """A dedup id already carries a different payload."""


@dataclass(frozen=True, slots=True)
class DeclaredEffect:
    """A declaration-level effect contract, resolved before any handler runs."""

    effect: type[Effect]
    key: DefinitionKey
    payload_type: type[Value]
    dedup_key: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EffectIntent:
    """A typed payload snapshot with its stable dedup identity."""

    effect: DefinitionKey
    payload: Mapping[str, object]
    dedup_id: str


@dataclass(frozen=True, slots=True)
class EffectEnvelope:
    """The durable row written beside the business commit, never a delivery."""

    intent: EffectIntent
    execution_id: str
    action: DefinitionKey
    approver: str | None

    @property
    def id(self) -> str:
        """One outbox row per execution and effect, independent of retries."""
        return f"{self.execution_id}:{self.intent.effect.identity}"

    def document(self) -> dict[str, object]:
        """A canonical, portable document for storage and reconciliation."""
        return {
            "id": self.id,
            "effect": {
                "identity": self.intent.effect.identity,
                "version": self.intent.effect.version,
            },
            "execution_id": self.execution_id,
            "action": {"identity": self.action.identity, "version": self.action.version},
            "approver": self.approver,
            "dedup_id": self.intent.dedup_id,
            "payload": dict(self.intent.payload),
        }


class OutboxUnitOfWork(UnitOfWork, Protocol):
    """The same transaction that applies writes can also claim outbox intents."""

    def record_effect(self, envelope: EffectEnvelope) -> bool:
        """Write one pending intent; return False when its dedup id already exists."""
        ...


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEffectDeclaration(f"{label} must be a non-empty string.")
    return value


def effect_key(effect: object) -> DefinitionKey:
    """Take an effect's exact identity and version from its declaration."""
    if not isinstance(effect, type) or not issubclass(effect, Effect):
        raise UndeclaredEffect("an enqueue must name an Effect declaration.")
    identity = _text(effect.identity, "Effect.identity")
    version = _text(effect.version, "Effect.version")
    return DefinitionKey(identity, version)


def _payload_type(effect: type[Effect], linked: LinkedDeclarations) -> type[Value]:
    raw: object = effect.payload
    if isinstance(raw, type) and issubclass(raw, Value):
        return raw
    if isinstance(raw, str):
        for reference in linked.references:
            if reference.identity != effect.identity or reference.field != "payload":
                continue
            target = reference.target.definition.declaration
            if isinstance(target, type) and issubclass(target, Value):
                return target
    raise InvalidEffectDeclaration(f"effect {effect.identity!r} has no linked Value payload type.")


def declared_effects(
    declaration: type[Action], linked: LinkedDeclarations
) -> tuple[DeclaredEffect, ...]:
    """Resolve every declared effect's typed payload and dedup fields before a handler."""
    specs: list[DeclaredEffect] = []
    seen: set[DefinitionKey] = set()
    for effect in declaration.effects:
        key = effect_key(effect)
        if key in seen:
            raise InvalidEffectDeclaration(f"effect {key.identity!r} is declared twice.")
        seen.add(key)
        payload_type = _payload_type(effect, linked)
        properties = set(payload_type.properties)
        if not properties:
            raise InvalidEffectDeclaration(
                f"effect {key.identity!r} declares a payload with no typed fields."
            )
        dedup_key = tuple(effect.dedupKey)
        unknown = tuple(name for name in dedup_key if name not in properties)
        if unknown:
            raise InvalidEffectDeclaration(
                f"effect {key.identity!r} dedups on undeclared payload field(s): "
                f"{', '.join(unknown)}."
            )
        specs.append(DeclaredEffect(effect, key, payload_type, dedup_key))
    return tuple(specs)


def require_outbox_binding(bound: BoundAction, specs: Sequence[DeclaredEffect]) -> None:
    """Fail closed before a handler if effects are not bound to this exact session."""
    if not specs:
        return
    session = bound.session
    if session is None or Capability.OUTBOX not in session.capabilities:
        raise EffectNotBound("the bound session has no outbox capability.")
    bound_effects: dict[DefinitionKey, BoundEffect] = {
        item.definition: item for item in bound.effects
    }
    for spec in specs:
        item = bound_effects.get(spec.key)
        if item is None:
            raise EffectNotBound(
                f"effect {spec.key.identity!r}@{spec.key.version!r} has no outbox binding."
            )
        if item.session != session.session or item.provider != session.provider:
            raise EffectNotBound(
                f"effect {spec.key.identity!r} is enlisted outside the business session."
            )
        if not item.dedup:
            raise EffectNotBound(f"effect {spec.key.identity!r} has no durable dedup binding.")


def payload_of(payload_type: type[Value], **fields: object) -> Value:
    """Create a typed payload value from its declared fields, without live handles."""
    if not isinstance(payload_type, type) or not issubclass(payload_type, Value):
        raise InvalidEffectPayload("a payload type must be a declared Value.")
    if set(fields) != set(payload_type.properties):
        raise InvalidEffectPayload("payload fields must match the declared Value properties.")
    value = object.__new__(payload_type)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _snapshot(spec: DeclaredEffect, payload: object) -> dict[str, object]:
    if not isinstance(payload, spec.payload_type):
        raise InvalidEffectPayload(
            f"effect {spec.key.identity!r} needs a "
            f"{spec.payload_type.__name__} payload, got {type(payload).__name__}."
        )
    snapshot: dict[str, object] = {}
    for name in spec.payload_type.properties:
        try:
            value = getattr(payload, name)
        except AttributeError as exc:
            raise InvalidEffectPayload(
                f"effect payload is missing its declared field {name!r}."
            ) from exc
        try:
            snapshot[name] = canonicalize(value)
        except UnsupportedIntent as exc:
            raise InvalidEffectPayload(
                f"effect payload field {name!r} is not a durable value: {exc}"
            ) from exc
    return snapshot


def _dedup_id(spec: DeclaredEffect, snapshot: Mapping[str, object], execution_id: str) -> str:
    if spec.dedup_key:
        parts: list[object] = [spec.key.identity, spec.key.version]
        parts.extend(snapshot[name] for name in spec.dedup_key)
    else:
        parts = [spec.key.identity, spec.key.version, execution_id]
    material = serialize({"dedup": parts})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def enqueue(
    specs: Sequence[DeclaredEffect],
    effect: object,
    payload: object,
    execution_id: str,
) -> EffectIntent:
    """Validate and snapshot one declared effect; nothing is sent or written here."""
    key = effect_key(effect)
    spec = next((item for item in specs if item.key == key and item.effect is effect), None)
    if spec is None:
        raise UndeclaredEffect(f"effect {key.identity!r}@{key.version!r} is not declared.")
    snapshot = _snapshot(spec, payload)
    return EffectIntent(key, snapshot, _dedup_id(spec, snapshot, execution_id))


def envelope(
    intent: EffectIntent,
    *,
    execution_id: str,
    action: DefinitionKey,
    approver: Principal | None,
) -> EffectEnvelope:
    """Add the engine-owned envelope fields at commit time, never from a handler."""
    return EffectEnvelope(
        intent, execution_id, action, None if approver is None else approver.identity
    )


def require_envelopes_bound(bound: BoundAction, intents: Sequence[EffectEnvelope]) -> None:
    """Check the runtime plan against the same capability/session gate as binding."""
    if not intents:
        return
    session = bound.session
    if session is None or Capability.OUTBOX not in session.capabilities:
        raise EffectNotBound("the bound session has no outbox capability.")
    bound_effects = {item.definition: item for item in bound.effects}
    seen: set[str] = set()
    for intent in intents:
        item = bound_effects.get(intent.intent.effect)
        if item is None or item.session != session.session or item.provider != session.provider:
            raise EffectNotBound(
                f"effect {intent.intent.effect.identity!r} is not bound to this session."
            )
        if intent.id in seen:
            raise EffectConflict(f"effect {intent.id!r} was enqueued twice.")
        seen.add(intent.id)


__all__ = [
    "DeclaredEffect",
    "EffectConflict",
    "EffectEnvelope",
    "EffectIntent",
    "EffectNotBound",
    "InvalidEffectDeclaration",
    "InvalidEffectPayload",
    "OutboxError",
    "OutboxUnitOfWork",
    "UndeclaredEffect",
    "declared_effects",
    "envelope",
    "payload_of",
    "require_envelopes_bound",
    "require_outbox_binding",
]
