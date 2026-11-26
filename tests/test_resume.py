"""Resume gate: pinned logic, live revalidation, reapproval and terminal outcomes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from resume_support import (
    APPROVE_PERMISSION,
    RESERVE_KEY,
    ROLE,
    ROOT_KEY,
    approver,
    case,
    principal,
    resume_case,
    rows,
    update,
)

from codology import decode_manifest
from codology.decision import approve


def test_resume_commits_once_with_pinned_revisions_and_decision_outcome(tmp_path: Path) -> None:
    target = case(tmp_path)

    result = resume_case(target)

    assert result.attempt.code == "COMMITTED"
    assert result.execution is not None
    assert result.execution.status == "COMMITTED"
    assert result.execution.execution_id == target.execution_id
    assert result.execution.children == (RESERVE_KEY,)
    assert decode_manifest(result.execution.pinned_manifest or "").root.key == ROOT_KEY
    order = rows(target.path, "purchase_orders")[0]
    budget = rows(target.path, "budgets")[0]
    assert (order[3], order[6]) == ("APPROVED", 2)
    assert (budget[4], budget[5]) == (120_000, 2)
    assert rows(target.path, "request_ledger")[0][7] == "COMMITTED"
    assert len(rows(target.path, "outbox")) == 1

    outcomes = rows(target.path, "approval_resume_outcomes")
    assert len(outcomes) == 1 and outcomes[0][2] == "COMMITTED"


def test_replay_after_commit_returns_stored_result_without_another_write(tmp_path: Path) -> None:
    target = case(tmp_path)
    assert resume_case(target).attempt.code == "COMMITTED"

    second = resume_case(target)

    assert second.attempt.code == "COMMITTED"
    assert second.execution is not None
    assert second.execution.execution_id == target.execution_id
    assert second.execution.deduplicated is True
    assert len(rows(target.path, "approval_resume_outcomes")) == 1
    assert rows(target.path, "budgets")[0][4] == 120_000
    assert len(rows(target.path, "approval_decisions")) == 1


def test_resume_requires_live_requester_permission(tmp_path: Path) -> None:
    target = case(tmp_path)

    denied = resume_case(target, caller=principal())

    assert denied.attempt.code == "DENIED"
    assert rows(target.path, "request_ledger")[0][7] == "AWAITING_APPROVAL"
    assert rows(target.path, "approval_resume_outcomes") == []
    assert rows(target.path, "budgets")[0][4] == 0
    assert resume_case(target).attempt.code == "COMMITTED"


def test_resume_requires_live_approver_role_and_permission(tmp_path: Path) -> None:
    target = case(tmp_path)

    target.authority.roles = ()
    no_role = resume_case(target)
    target.authority.roles = (ROLE,)
    target.authority.permissions = ()
    no_permission = resume_case(target)

    assert no_role.attempt.code == "DENIED"
    assert no_permission.attempt.code == "DENIED"
    for _ in (no_role, no_permission):
        assert rows(target.path, "request_ledger")[0][7] == "AWAITING_APPROVAL"
        assert rows(target.path, "approval_resume_outcomes") == []
    target.authority.permissions = (APPROVE_PERMISSION,)
    assert resume_case(target).attempt.code == "COMMITTED"


def test_material_change_mints_new_approval_and_old_key_cannot_commit(tmp_path: Path) -> None:
    target = case(tmp_path)
    old_key, old_fingerprint = target.callback_key, target.fingerprint
    update(target.path, "UPDATE purchase_orders SET amount = 150000 WHERE id = 'PO-1'")

    changed = resume_case(target)

    assert changed.attempt.code == "AWAITING_APPROVAL"
    assert changed.execution is not None
    new_approval = changed.execution.required_approval
    assert new_approval is not None
    assert new_approval.callback_key != old_key
    assert new_approval.intent_fingerprint != old_fingerprint
    assert changed.attempt.reason == "REAPPROVAL_REQUIRED"
    assert rows(target.path, "request_ledger")[0][4] == target.waiting.attempt.intent_fingerprint
    assert rows(target.path, "approval_resume_outcomes")[0][2] == "REAPPROVAL"
    assert rows(target.path, "budgets")[0][4] == 0

    old = resume_case(target, callback_key=old_key)
    assert old.attempt.code == "DENIED" and old.attempt.reason == "KEY_MISUSE"
    stale_callback = approve(
        provider=target.provider,
        authority_provider=target.authority,
        principal=approver(),
        execution_id=target.execution_id,
        callback_key=old_key,
        expected_intent_fingerprint=old_fingerprint,
        reason="budget confirmed",
    )
    assert stale_callback.attempt.code == "AWAITING_APPROVAL"
    assert stale_callback.execution is not None and stale_callback.execution.deduplicated is True
    assert len(rows(target.path, "approval_decisions")) == 1

    approved = approve(
        provider=target.provider,
        authority_provider=target.authority,
        principal=approver(),
        execution_id=target.execution_id,
        callback_key=new_approval.callback_key,
        expected_intent_fingerprint=new_approval.intent_fingerprint,
        reason="budget confirmed at new amount",
    )
    assert approved.decision is not None
    committed = resume_case(target, callback_key=new_approval.callback_key)
    assert committed.attempt.code == "COMMITTED"
    assert rows(target.path, "budgets")[0][4] == 150_000


def test_expired_approval_mints_new_approval(tmp_path: Path) -> None:
    deadline = (datetime.now(UTC) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    target = case(tmp_path, expires_at=deadline)
    old_key, old_fingerprint = target.callback_key, target.fingerprint
    later = datetime.now(UTC) + timedelta(hours=2)

    expired = resume_case(target, now=later)

    assert expired.attempt.code == "AWAITING_APPROVAL"
    assert expired.execution is not None and expired.execution.required_approval is not None
    assert expired.execution.required_approval.callback_key != old_key
    assert expired.execution.required_approval.intent_fingerprint != old_fingerprint
    assert resume_case(target, callback_key=old_key, now=later).attempt.code == "DENIED"
    assert rows(target.path, "approval_resume_outcomes")[0][2] == "REAPPROVAL"
    assert rows(target.path, "budgets")[0][4] == 0


def test_revoked_approval_mints_new_approval(tmp_path: Path) -> None:
    target = case(tmp_path)
    old_key = target.callback_key
    target.authority.revoked.add(target.approval.approval_id)

    revoked = resume_case(target)

    assert revoked.attempt.code == "AWAITING_APPROVAL"
    assert revoked.execution is not None and revoked.execution.required_approval is not None
    new_approval = revoked.execution.required_approval
    assert new_approval.callback_key != old_key
    assert resume_case(target, callback_key=old_key).attempt.code == "DENIED"
    assert rows(target.path, "budgets")[0][4] == 0

    target.authority.revoked.clear()
    approved = approve(
        provider=target.provider,
        authority_provider=target.authority,
        principal=approver(),
        execution_id=target.execution_id,
        callback_key=new_approval.callback_key,
        expected_intent_fingerprint=new_approval.intent_fingerprint,
        reason="approval reinstated",
    )
    assert approved.decision is not None
    assert resume_case(target, callback_key=new_approval.callback_key).attempt.code == "COMMITTED"


def test_lost_precondition_terminates_rejected_without_business_write(tmp_path: Path) -> None:
    target = case(tmp_path)
    update(target.path, "UPDATE purchase_orders SET status = 'CANCELLED' WHERE id = 'PO-1'")

    rejected = resume_case(target)

    assert rejected.attempt.code == "REJECTED"
    assert rows(target.path, "request_ledger")[0][7] == "REJECTED"
    assert rows(target.path, "budgets")[0][4] == 0
    assert rows(target.path, "approval_resume_outcomes")[0][2] == "REJECTED"
    assert resume_case(target).attempt.code == "REJECTED"
    assert len(rows(target.path, "approval_resume_outcomes")) == 1
