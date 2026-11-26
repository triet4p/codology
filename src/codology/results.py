"""Authoritative invoke outcomes and their durable replay.

An attempt outcome is not an execution. Only a stored ledger record can become
an execution, and only a reader with record authority may replay it. This
module owns that representation so the invoke gate can stay small; it opens no
transaction and makes no business decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from codology.gate_support import request_scope
from codology.ledger import (
    EXECUTION_READ_PERMISSION,
    LedgerEntry,
    LedgerProvider,
    RequestScope,
    StoredChange,
    StoredResult,
    decode_result,
)
from codology.ports import ApplyResult, Assignment, SetOp
from codology.query import Principal
from codology.snapshot import DefinitionKey
from codology.waiting import MaterialIntent, RequiredApproval, decode_awaiting

InvokeCode = Literal["COMMITTED", "AWAITING_APPROVAL", "DENIED", "REJECTED", "StalePlan", "UNKNOWN"]
ExecutionStatus = Literal["COMMITTED", "REJECTED", "AWAITING_APPROVAL"]

KEY_MISUSE_DETAIL = "the request key and intent do not match the stored result."
UNKNOWN_DETAIL = "no authoritative result is available for this request."


class LedgerReader(Protocol):
    """Read access to a committed ledger record through a scoped key."""

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None: ...


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """What the caller may know about one invoke attempt."""

    code: InvokeCode
    detail: str | None
    request_key: str | None = None
    intent_fingerprint: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CommittedChange:
    """One accepted mutation plan, without exposing handler internals."""

    resource: str
    key: str
    version: int
    changes: tuple[Assignment, ...]


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """The authoritative outcome of one accepted execution, replayable from the ledger."""

    execution_id: str
    status: ExecutionStatus
    action: DefinitionKey
    requester: Principal
    committed: tuple[CommittedChange, ...] = ()
    children: tuple[DefinitionKey, ...] = ()
    deduplicated: bool = False
    pinned_manifest: str | None = None
    material_intent: MaterialIntent | None = None
    required_approval: RequiredApproval | None = None
    canonical_input: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    """An attempt outcome plus an execution only when one was actually created."""

    attempt: AttemptOutcome
    execution: ExecutionRecord | None = None
    writes: tuple[ApplyResult, ...] = ()


def outcome(
    code: InvokeCode,
    detail: str | None,
    *,
    reason: str | None = None,
    request_key: str | None = None,
    intent_fingerprint: str | None = None,
) -> ActionResult:
    return ActionResult(AttemptOutcome(code, detail, request_key, intent_fingerprint, reason))


def key_misuse(request_key: str | None, fingerprint: str | None) -> ActionResult:
    return outcome(
        "DENIED",
        KEY_MISUSE_DETAIL,
        reason="KEY_MISUSE",
        request_key=request_key,
        intent_fingerprint=fingerprint,
    )


def stored_result(record: ExecutionRecord) -> StoredResult:
    """Convert an accepted execution into its portable committed form."""
    changes = tuple(
        StoredChange(
            item.resource,
            item.key,
            item.version,
            tuple((c.column, c.op, c.value) for c in item.changes),
        )
        for item in record.committed
    )
    return StoredResult(
        record.execution_id, "COMMITTED", record.action, record.requester, changes, record.children
    )


def replay(stored: LedgerEntry) -> ActionResult | None:
    """Rebuild an execution from a trusted ledger record, or fail closed."""
    if stored.status in ("AWAITING_APPROVAL", "REJECTED"):
        waiting = decode_awaiting(stored.payload)
        if waiting is None:
            return None
        intent = waiting.material_intent
        return ActionResult(
            AttemptOutcome(stored.status, None, stored.request_key, stored.intent_fingerprint),
            ExecutionRecord(
                waiting.execution_id,
                stored.status,
                waiting.action,
                waiting.requester,
                (),
                intent.child_keys,
                True,
                waiting.pinned_manifest,
                intent,
                waiting.required_approval,
                waiting.canonical_input,
            ),
        )
    result = decode_result(stored.payload)
    if result is None:
        return None
    changes = tuple(
        CommittedChange(
            item.resource,
            item.key,
            item.version,
            tuple(Assignment(c, cast(SetOp, op), value) for c, op, value in item.changes),
        )
        for item in result.committed
    )
    return ActionResult(
        AttemptOutcome("COMMITTED", None, stored.request_key, stored.intent_fingerprint),
        ExecutionRecord(
            result.execution_id,
            "COMMITTED",
            result.action,
            result.requester,
            changes,
            result.children,
            True,
        ),
    )


def stored_replay(stored: LedgerEntry, request_key: str, fingerprint: str) -> ActionResult:
    """Replay a claimed key, or deny a key whose intent no longer matches."""
    if stored.intent_fingerprint != fingerprint:
        return key_misuse(request_key, fingerprint)
    result = replay(stored)
    if result is not None:
        return result
    return outcome(
        "DENIED",
        "the stored execution cannot be verified.",
        request_key=request_key,
        intent_fingerprint=fingerprint,
    )


def duplicate_outcome(
    provider: LedgerReader,
    scope: RequestScope | None,
    request_key: str | None,
    fingerprint: str | None,
) -> ActionResult:
    """Describe a duplicate claim without exposing another execution's details."""
    if scope is not None and request_key is not None and fingerprint is not None:
        stored = provider.lookup(scope, request_key)
        if stored is not None and stored.intent_fingerprint == fingerprint:
            replayed = replay(stored)
            if replayed is not None:
                return replayed
        return key_misuse(request_key, fingerprint)
    return outcome("DENIED", "invoke request was refused by the engine gate.")


def reconcile(
    *,
    provider: LedgerProvider,
    principal: Principal,
    action: DefinitionKey,
    request_key: str,
) -> ActionResult:
    """Return a stored authoritative result only to a reader with record authority."""
    if EXECUTION_READ_PERMISSION not in principal.permissions:
        return outcome("DENIED", "read authority for execution records is required.")
    if not request_key.strip():
        return outcome("UNKNOWN", UNKNOWN_DETAIL)
    stored = provider.lookup(request_scope(principal, action), request_key)
    if stored is None:
        return outcome("UNKNOWN", UNKNOWN_DETAIL)
    replayed = replay(stored)
    return replayed if replayed is not None else outcome("UNKNOWN", UNKNOWN_DETAIL)


__all__ = [
    "ActionResult",
    "AttemptOutcome",
    "CommittedChange",
    "ExecutionRecord",
    "ExecutionStatus",
    "InvokeCode",
    "duplicate_outcome",
    "key_misuse",
    "outcome",
    "reconcile",
    "replay",
    "stored_replay",
    "stored_result",
]
