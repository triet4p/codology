"""Local relay for committed outbox rows.

The relay runs after a business commit. It never calls a handler, opens a
business unit of work, or changes an execution. Delivery is at-least-once: a
durable receiver deduplicates by the stable outbox dedup ID so a repeated send
produces one local notification. Effect state is read through its own
authorized gate, independently of the execution record.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from codology.query import Principal

EffectStatus = Literal["PENDING", "PENDING_RETRY", "DELIVERED", "FAILED"]
DeliveryStatus = Literal["DELIVERED", "PENDING_RETRY", "FAILED"]

EFFECT_READ_PERMISSION = "effect.read"

_DELIVERABLE: frozenset[str] = frozenset({"PENDING", "PENDING_RETRY"})
_STATUSES: frozenset[str] = frozenset({"PENDING", "PENDING_RETRY", "DELIVERED", "FAILED"})
_DELIVERY_STATUSES: frozenset[str] = frozenset({"DELIVERED", "PENDING_RETRY", "FAILED"})


class RelayError(Exception):
    """A relay contract was violated before or during delivery."""


class InvalidOutboxMessage(RelayError, ValueError):
    """A row cannot be delivered as the outbox document it claims to be."""


class EffectReadDenied(PermissionError):
    """The caller has no live authority to observe effect state."""


class TransientDelivery(RelayError):
    """Delivery can be retried with the same dedup ID."""


class PermanentDelivery(RelayError):
    """Delivery cannot succeed; the effect must be handled without a retry."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidOutboxMessage(f"{label} must be a non-empty string.")
    return value


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    """A committed, typed outbox document handed to the local receiver."""

    id: str
    dedup_id: str
    document: Mapping[str, object]
    status: EffectStatus
    attempts: int

    def __post_init__(self) -> None:
        _text(self.id, "OutboxMessage.id")
        _text(self.dedup_id, "OutboxMessage.dedup_id")
        if self.status not in _DELIVERABLE:
            raise InvalidOutboxMessage("the relay only accepts pending outbox rows.")
        if type(self.attempts) is not int or self.attempts < 0:
            raise InvalidOutboxMessage("OutboxMessage.attempts must be a non-negative integer.")
        if self.document.get("id") != self.id or self.document.get("dedup_id") != self.dedup_id:
            raise InvalidOutboxMessage("the outbox document does not match its durable identity.")
        if not isinstance(self.document.get("payload"), Mapping):
            raise InvalidOutboxMessage("the outbox document has no typed payload snapshot.")


@dataclass(frozen=True, slots=True)
class Receipt:
    """A receiver's durable record of one effect dedup ID."""

    dedup_id: str
    notification_id: str
    replayed: bool

    def __post_init__(self) -> None:
        _text(self.dedup_id, "Receipt.dedup_id")
        _text(self.notification_id, "Receipt.notification_id")
        if type(self.replayed) is not bool:
            raise RelayError("Receipt.replayed must be a boolean.")


@dataclass(frozen=True, slots=True)
class EffectState:
    """The separate, observable state of one delivered effect."""

    id: str
    dedup_id: str
    status: EffectStatus
    attempts: int
    detail: str | None = None

    def __post_init__(self) -> None:
        _text(self.id, "EffectState.id")
        _text(self.dedup_id, "EffectState.dedup_id")
        if self.status not in _STATUSES:
            raise RelayError(f"unsupported effect status {self.status!r}.")
        if type(self.attempts) is not int or self.attempts < 0:
            raise RelayError("EffectState.attempts must be a non-negative integer.")


@dataclass(frozen=True, slots=True)
class Delivery:
    """The observable result of one relay send, including a lost receiver ack."""

    id: str
    dedup_id: str
    status: DeliveryStatus
    replayed: bool = False
    recorded: bool = False
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status not in _DELIVERY_STATUSES:
            raise RelayError(f"unsupported delivery status {self.status!r}.")


class RelayStore(Protocol):
    """Committed outbox rows and their separate effect state."""

    def committed_messages(self, limit: int = 20) -> tuple[OutboxMessage, ...]:
        """Return only rows whose business execution is durably committed."""
        ...

    def record_attempt(
        self, message: OutboxMessage, status: DeliveryStatus, detail: str | None
    ) -> bool:
        """Advance effect state once; False means another attempt already did."""
        ...

    def effect_states(self, execution_id: str, tenant: str) -> tuple[EffectState, ...]:
        """Read effect state scoped to a tenant, without an execution lookup by caller."""
        ...


class LocalReceiver(Protocol):
    """A durable local sink that deduplicates on the outbox dedup ID."""

    def receive(self, message: OutboxMessage) -> Receipt:
        """Return a receipt; a retry of the same dedup ID must not write twice."""
        ...


def deliver_committed(
    store: RelayStore,
    receiver: LocalReceiver,
    *,
    limit: int = 20,
) -> tuple[Delivery, ...]:
    """Send each committed pending row once per call; classify failures separately."""
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer.")
    deliveries: list[Delivery] = []
    for message in store.committed_messages(limit):
        replayed = False
        try:
            receipt = receiver.receive(message)
            if receipt.dedup_id != message.dedup_id:
                raise InvalidOutboxMessage("the receiver acknowledged a different dedup ID.")
            replayed = receipt.replayed
            status: DeliveryStatus = "DELIVERED"
            detail: str | None = receipt.notification_id
        except TransientDelivery as exc:
            status = "PENDING_RETRY"
            detail = str(exc) or "the receiver could not confirm delivery."
        except PermanentDelivery as exc:
            status = "FAILED"
            detail = str(exc) or "the receiver rejected the notification permanently."
        recorded = store.record_attempt(message, status, detail)
        deliveries.append(
            Delivery(
                message.id,
                message.dedup_id,
                status,
                replayed=replayed,
                recorded=recorded,
                detail=detail,
            )
        )
    return tuple(deliveries)


def read_effect_status(
    store: RelayStore,
    principal: Principal,
    execution_id: str,
) -> tuple[EffectState, ...]:
    """Observe effect state through a permission gate separate from execution reads."""
    if EFFECT_READ_PERMISSION not in principal.permissions:
        raise EffectReadDenied("effect.read permission is required to observe effect state.")
    _text(execution_id, "execution_id")
    return store.effect_states(execution_id, principal.tenant)


__all__ = [
    "Delivery",
    "DeliveryStatus",
    "EffectReadDenied",
    "EffectState",
    "EffectStatus",
    "EFFECT_READ_PERMISSION",
    "InvalidOutboxMessage",
    "LocalReceiver",
    "OutboxMessage",
    "PermanentDelivery",
    "Receipt",
    "RelayError",
    "RelayStore",
    "TransientDelivery",
    "deliver_committed",
    "read_effect_status",
]
