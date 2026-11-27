"""Cross-layer checks for the break-glass runtime slice.

Each case owns its SQLite file and drives only public engine ports through the
example's caller module. Every API result is paired with a read from a
connection independent of the engine and relay, while the waiting cases also
prove nothing durable was written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codology import NoSharedTransaction, bind_action
from codology.engine import ActionResult
from codology.waiting import RequiredApproval
from examples.break_glass_access import consumer, database, wiring
from examples.break_glass_access.__main__ import main

GRANT = "access_control.grant_request"
AUDIT = "security_audit.session"
AWAITING = "AWAITING_APPROVAL"
COMMITTED = "COMMITTED"
REQUEST_KEY = f"{wiring.TENANT}:{wiring.REQUESTER}:grant:AGR-1:001"


def _host(tmp_path: Path, name: str, **seed: object) -> tuple[Path, wiring.Host]:
    path = wiring.install(tmp_path / name, **seed)
    return path, wiring.open_host(path)


def _waiting(host: wiring.Host) -> tuple[ActionResult, str, RequiredApproval]:
    result = consumer.request_access(host, request_key=REQUEST_KEY)
    assert result.attempt.code == AWAITING, result.attempt
    assert result.execution is not None and result.execution.required_approval is not None
    return result, result.execution.execution_id, result.execution.required_approval


def test_documented_runtime_entrypoint_reports_every_scenario(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--runtime"], directory=tmp_path / "cli") == 0
    output = capsys.readouterr().out
    assert "RUNTIME CHECKS PASSED" in output
    for label in (
        "[below threshold, not sensitive]",
        "[approval predicate branches]",
        "[wrong authority]",
        "[approve, resume, replay, relay]",
    ):
        assert label in output


def test_below_threshold_request_commits_both_writes_ledger_and_outbox(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "below.sqlite3", duration_minutes=30)
    result = consumer.request_access(host, request_key=REQUEST_KEY)
    assert result.attempt.code == COMMITTED
    assert result.execution is not None
    execution_id = result.execution.execution_id

    assert database.grant_state(path) == ("GRANTED", 30, "ROUTINE", 2)
    assert database.session_state(path) == ("OPEN", 2)
    assert database.ledger_state(path) == [("1.0.0", COMMITTED, execution_id)]
    assert len(database.outbox_state(path)) == 1
    assert database.count_rows(path, "approval_decisions") == 0

    assert consumer.relay_once(host)[0].status == "DELIVERED"
    assert database.count_rows(path, "local_notifications") == 1
    assert database.count_rows(path, "notification_inbox") == 1
    assert database.effect_state(path) == [("DELIVERED", 1)]
    assert consumer.relay_once(host) == ()

    assert database.grant_state(path) == ("GRANTED", 30, "ROUTINE", 2)
    assert database.session_state(path) == ("OPEN", 2)


def test_duration_threshold_branch_waits_without_business_or_outbox_writes(
    tmp_path: Path,
) -> None:
    path, host = _host(tmp_path, "duration.sqlite3", duration_minutes=60)
    result, execution_id, approval = _waiting(host)

    assert result.attempt.code == AWAITING
    assert approval.role == wiring.APPROVAL_ROLE
    assert database.grant_state(path) == ("PENDING", 60, "ROUTINE", 1)
    assert database.session_state(path) == ("NEW", 1)
    assert database.ledger_state(path) == [("1.0.0", AWAITING, execution_id)]
    assert database.outbox_state(path) == []
    assert database.count_rows(path, "approval_decisions") == 0
    assert consumer.relay_once(host) == ()


def test_sensitive_below_threshold_branch_waits_independently(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "sensitive.sqlite3", duration_minutes=15, sensitivity="CRITICAL")
    result, execution_id, approval = _waiting(host)

    assert result.attempt.code == AWAITING
    assert approval.role == wiring.APPROVAL_ROLE
    assert database.grant_state(path) == ("PENDING", 15, "CRITICAL", 1)
    assert database.session_state(path) == ("NEW", 1)
    assert database.ledger_state(path) == [("1.0.0", AWAITING, execution_id)]
    assert database.outbox_state(path) == []
    assert database.count_rows(path, "approval_decisions") == 0
    assert consumer.relay_once(host) == ()


def test_wrong_authority_is_denied_and_the_execution_stays_pending(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "denied.sqlite3", duration_minutes=90)
    _, execution_id, approval = _waiting(host)

    denied = consumer.approve_access(
        host,
        execution_id,
        approval,
        principal=host.outsider,
        authority=wiring.HostAuthority(roles=(), permissions=()),
    )
    assert denied.attempt.code == "DENIED"
    assert denied.decision is None
    assert database.ledger_state(path) == [("1.0.0", AWAITING, execution_id)]
    assert database.grant_state(path) == ("PENDING", 90, "ROUTINE", 1)
    assert database.session_state(path) == ("NEW", 1)
    assert database.outbox_state(path) == []
    assert database.count_rows(path, "approval_decisions") == 0
    assert database.count_rows(path, "approval_audit") == 1

    approved = consumer.approve_access(host, execution_id, approval)
    assert approved.attempt.reason == "APPROVED"
    assert consumer.resume_access(host, execution_id, approval.callback_key).attempt.code == (
        COMMITTED
    )


def test_valid_approval_does_not_commit_until_resume_commits_both_writes(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "approve.sqlite3", duration_minutes=90)
    _, execution_id, approval = _waiting(host)

    approved = consumer.approve_access(host, execution_id, approval)
    assert approved.attempt.code == AWAITING
    assert approved.attempt.reason == "APPROVED"
    assert approved.decision is not None
    assert database.grant_state(path) == ("PENDING", 90, "ROUTINE", 1)
    assert database.session_state(path) == ("NEW", 1)
    assert database.ledger_state(path) == [("1.0.0", AWAITING, execution_id)]
    assert database.outbox_state(path) == []
    assert database.count_rows(path, "approval_decisions") == 1

    finished = consumer.resume_access(host, execution_id, approval.callback_key)
    assert finished.attempt.code == COMMITTED
    assert database.grant_state(path) == ("GRANTED", 90, "ROUTINE", 2)
    assert database.session_state(path) == ("OPEN", 2)
    assert database.ledger_state(path) == [("1.0.0", COMMITTED, execution_id)]
    assert len(database.outbox_state(path)) == 1
    assert database.count_rows(path, "approval_resume_outcomes") == 1


def test_replay_after_commit_returns_the_same_execution_and_writes_nothing(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "replay.sqlite3", duration_minutes=90)
    request = consumer.grant_ref(host)
    session = consumer.session_ref(host)
    waiting = consumer.request_access(
        host, request_key=REQUEST_KEY, request=request, session=session
    )
    assert waiting.execution is not None and waiting.execution.required_approval is not None
    execution_id = waiting.execution.execution_id
    approval = waiting.execution.required_approval
    consumer.approve_access(host, execution_id, approval)
    assert consumer.resume_access(host, execution_id, approval.callback_key).attempt.code == (
        COMMITTED
    )

    replay = consumer.request_access(
        host, request_key=REQUEST_KEY, request=request, session=session
    )
    assert replay.attempt.code == COMMITTED
    assert replay.execution is not None and replay.execution.execution_id == execution_id
    assert replay.execution.deduplicated is True

    assert database.grant_state(path) == ("GRANTED", 90, "ROUTINE", 2)
    assert database.session_state(path) == ("OPEN", 2)
    assert database.ledger_state(path) == [("1.0.0", COMMITTED, execution_id)]
    assert len(database.outbox_state(path)) == 1
    assert database.count_rows(path, "approval_decisions") == 1
    assert database.count_rows(path, "approval_resume_outcomes") == 1


def test_relay_delivers_only_after_commit_and_never_reruns_the_handler(tmp_path: Path) -> None:
    path, host = _host(tmp_path, "relay.sqlite3", duration_minutes=90)
    _, execution_id, approval = _waiting(host)
    assert consumer.relay_once(host) == ()

    consumer.approve_access(host, execution_id, approval)
    assert consumer.relay_once(host) == ()
    assert database.count_rows(path, "local_notifications") == 0

    assert consumer.resume_access(host, execution_id, approval.callback_key).attempt.code == (
        COMMITTED
    )
    delivery = consumer.relay_once(host)
    assert [item.status for item in delivery] == ["DELIVERED"]
    assert database.count_rows(path, "local_notifications") == 1
    assert database.count_rows(path, "notification_inbox") == 1
    assert database.effect_state(path) == [("DELIVERED", 1)]
    assert consumer.relay_once(host) == ()

    assert database.grant_state(path) == ("GRANTED", 90, "ROUTINE", 2)
    assert database.session_state(path) == ("OPEN", 2)
    assert database.ledger_state(path) == [("1.0.0", COMMITTED, execution_id)]


def test_binding_puts_both_writes_and_the_outbox_in_one_session() -> None:
    bound = wiring.bound_root()

    assert bound.action == wiring.ROOT_KEY
    assert bound.commit_requirement == "ATOMIC"
    assert bound.session is not None
    assert bound.session.session == wiring.SESSION
    assert {write.identity for write in bound.session.writes} == {GRANT, AUDIT}
    assert {effect.session for effect in bound.effects} == {wiring.SESSION}
    assert [(item.caller, item.callee, item.permission) for item in bound.delegations] == [
        (wiring.ROOT_KEY, wiring.CHILD_KEY, wiring.SESSION_PERMISSION)
    ]


def test_split_session_binding_is_rejected_before_any_handler_runs(tmp_path: Path) -> None:
    path = wiring.install(tmp_path / "split.sqlite3")

    with pytest.raises(NoSharedTransaction):
        bind_action(wiring.published_snapshot(), wiring.split_deployment(), wiring.ROOT_KEY)

    assert database.grant_state(path) == ("PENDING", 30, "ROUTINE", 1)
    assert database.session_state(path) == ("NEW", 1)
    assert database.ledger_state(path) == []
    assert database.outbox_state(path) == []
