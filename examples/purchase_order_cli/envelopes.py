"""JSON-ready envelopes reported by the purchase-order CLI.

Every field is copied from an engine result, an engine-issued approval, an
authorized query row or a relay observation. The CLI recomputes no intent
fingerprint, policy decision or durable state; when an outcome is not final the
envelope adds the public call that resolves it, keeping the caller's original
request key.
"""

from __future__ import annotations

from codology import QueryPage, QueryRow
from codology.decision import DecisionResult
from codology.engine import ActionResult
from codology.relay import Delivery, EffectState
from codology.results import CommittedChange, ExecutionRecord
from codology.snapshot import DefinitionKey
from codology.waiting import RequiredApproval


def action_document(definition: DefinitionKey) -> dict[str, str]:
    """Name one version-explicit action identity."""
    return {"identity": definition.identity, "version": definition.version}


def approval_document(approval: RequiredApproval | None) -> dict[str, object] | None:
    """Report the engine-issued callback key and fingerprint unchanged."""
    return None if approval is None else approval.document()


def row_ref_document[T](row: QueryRow[T]) -> dict[str, object]:
    """Report the provenance of a ref taken from an authorized row."""
    return {"id": row.key, "instance_version": row.instance_version}


def page_document[T](page: QueryPage[T]) -> dict[str, object]:
    """Report an authorized page; the count is the engine's filtered count."""
    return {
        "count": page.count,
        "rows": [
            {
                "id": row.key,
                "instance_version": row.instance_version,
                "values": dict(row.values),
            }
            for row in page.rows
        ],
        "next_cursor": page.next_cursor,
    }


def change_document(change: CommittedChange) -> dict[str, object]:
    """Report one committed business change as the engine recorded it."""
    return {
        "resource": change.resource,
        "key": change.key,
        "version": change.version,
        "changes": [
            {"column": item.column, "op": item.op, "value": item.value} for item in change.changes
        ],
    }


def execution_document(execution: ExecutionRecord | None) -> dict[str, object] | None:
    """Report the authoritative execution, or ``None`` when none was created."""
    if execution is None:
        return None
    return {
        "execution_id": execution.execution_id,
        "status": execution.status,
        "action": action_document(execution.action),
        "deduplicated": execution.deduplicated,
        "pinned_manifest": execution.pinned_manifest,
        "committed": [change_document(change) for change in execution.committed],
        "children": [action_document(child) for child in execution.children],
        "required_approval": approval_document(execution.required_approval),
    }


def attempt_document(result: ActionResult) -> dict[str, object]:
    """Report the attempt code and the engine's reason for it."""
    attempt = result.attempt
    return {
        "code": attempt.code,
        "reason": attempt.reason,
        "detail": attempt.detail,
        "request_key": attempt.request_key,
        "intent_fingerprint": attempt.intent_fingerprint,
    }


def action_result_document(result: ActionResult) -> dict[str, object]:
    """Report one invoke/decision/resume result without recomputing anything."""
    return {
        "attempt": attempt_document(result),
        "execution": execution_document(result.execution),
        "writes": [
            {
                "resource": write.resource,
                "key": write.key,
                "rowcount": write.rowcount,
                "transaction": write.transaction,
            }
            for write in result.writes
        ],
    }


def decision_document(result: DecisionResult) -> dict[str, object]:
    """Report a callback attempt plus the decision the gate actually stored."""
    document = action_result_document(result)
    decision = result.decision
    document["decision"] = (
        None
        if decision is None
        else {
            "callback_key": decision.callback_key,
            "execution_id": decision.execution_id,
            "approval_id": decision.approval_id,
            "decision": decision.decision,
            "intent_fingerprint": decision.intent_fingerprint,
            "reason": decision.reason,
            "approved_by": {
                "identity": decision.principal.identity,
                "tenant": decision.principal.tenant,
            },
            "authority_revision": decision.authority_revision,
            "recorded_at": decision.recorded_at,
        }
    )
    return document


def delivery_document(delivery: Delivery) -> dict[str, object]:
    """Report one relay observation."""
    return {
        "id": delivery.id,
        "dedup_id": delivery.dedup_id,
        "status": delivery.status,
        "replayed": delivery.replayed,
        "recorded": delivery.recorded,
        "detail": delivery.detail,
    }


def effect_document(effect: EffectState) -> dict[str, object]:
    """Report one effect state read through the separate effect gate."""
    return {
        "id": effect.id,
        "dedup_id": effect.dedup_id,
        "status": effect.status,
        "attempts": effect.attempts,
        "detail": effect.detail,
    }


def next_step(
    result: ActionResult,
    *,
    execution_id: str | None = None,
    request_key: str | None = None,
    callback_key: str | None = None,
) -> dict[str, object] | None:
    """Name the public call that resolves a non-final outcome.

    A waiting execution points at ``approve`` with the engine-issued values; a
    recorded decision points at ``resume``; an unconfirmed commit points at
    ``reconcile`` with the original key or execution id, never a new key.
    """
    attempt = result.attempt
    if attempt.code == "AWAITING_APPROVAL":
        if attempt.reason == "APPROVED" and execution_id is not None:
            return {
                "command": "resume",
                "execution_id": execution_id,
                "callback_key": callback_key,
                "note": "the decision is recorded; nothing is committed until resume.",
            }
        approval = result.execution.required_approval if result.execution is not None else None
        if approval is not None and result.execution is not None:
            return {
                "command": "approve",
                "execution_id": result.execution.execution_id,
                "callback_key": approval.callback_key,
                "intent_fingerprint": approval.intent_fingerprint,
                "note": "approve only with the engine-issued callback key and fingerprint.",
            }
        return None
    if attempt.code == "UNKNOWN":
        document: dict[str, object] = {
            "command": "reconcile",
            "note": (
                "the commit outcome is not confirmed: reconcile with the original "
                "request key or execution id; do not mint a new request key from a timeout."
            ),
        }
        target = execution_id or (result.execution.execution_id if result.execution else None)
        if target is not None:
            document["execution_id"] = target
        if request_key is not None:
            document["request_key"] = request_key
        return document
    if attempt.code == "COMMITTED":
        return {
            "command": "relay",
            "note": (
                "reconcile with the original request key returns the same execution without writes."
            ),
        }
    return None


__all__ = [
    "action_document",
    "action_result_document",
    "approval_document",
    "attempt_document",
    "change_document",
    "decision_document",
    "delivery_document",
    "effect_document",
    "execution_document",
    "next_step",
    "page_document",
    "row_ref_document",
]
