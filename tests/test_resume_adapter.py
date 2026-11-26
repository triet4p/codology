"""Resume adapter edges: races, interrupted commits, replay and failed pin resolution."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import cast

from resume_support import (
    LATER_GRAPH,
    REQUEST_KEY,
    ROOT_KEY,
    HookedProvider,
    HostAuthority,
    case,
    reader,
    resume_case,
    rows,
    sqlite,
    update,
)

from codology.engine import ActionResult, reconcile
from codology.ledger import deserialize, serialize
from codology.resume import reconcile_execution


def test_budget_race_yields_stale_plan_and_retry_commits(tmp_path: Path) -> None:
    target = case(tmp_path)

    def competing_writer() -> None:
        update(target.path, "UPDATE budgets SET reserved = 1 WHERE id = 'B-1'")

    raced = resume_case(
        target, pro=HookedProvider(sqlite(target.path), before_unit=competing_writer)
    )

    assert raced.attempt.code == "StalePlan"
    assert rows(target.path, "budgets")[0][4] == 1
    assert rows(target.path, "purchase_orders")[0][3] == "PENDING"
    assert rows(target.path, "request_ledger")[0][7] == "AWAITING_APPROVAL"
    assert rows(target.path, "approval_resume_outcomes") == []

    assert resume_case(target).attempt.code == "COMMITTED"
    assert rows(target.path, "budgets")[0][4] == 120_001


def test_lost_commit_ack_reconciles_without_running_handler_again(tmp_path: Path) -> None:
    target = case(tmp_path)

    uncertain = resume_case(target, pro=HookedProvider(sqlite(target.path), commit_mode="after"))

    assert uncertain.attempt.code == "UNKNOWN"
    reconciled = reconcile(
        provider=target.provider,
        principal=reader(),
        action=ROOT_KEY,
        request_key=REQUEST_KEY,
    )
    assert reconciled.attempt.code == "COMMITTED"
    assert (
        reconciled.execution is not None
        and reconciled.execution.execution_id == target.execution_id
    )
    by_id = reconcile_execution(
        provider=target.provider, principal=reader(), execution_id=target.execution_id
    )
    assert by_id.execution is not None and by_id.execution.status == "COMMITTED"
    replayed = resume_case(target)
    assert replayed.attempt.code == "COMMITTED" and replayed.execution is not None
    assert replayed.execution.execution_id == target.execution_id
    assert rows(target.path, "budgets")[0][4] == 120_000
    assert len(rows(target.path, "approval_resume_outcomes")) == 1


def test_interrupted_before_commit_leaves_no_claim_and_allows_retry(tmp_path: Path) -> None:
    target = case(tmp_path)

    interrupted = resume_case(target, pro=HookedProvider(sqlite(target.path), commit_mode="before"))

    assert interrupted.attempt.code == "UNKNOWN"
    assert rows(target.path, "request_ledger")[0][7] == "AWAITING_APPROVAL"
    assert rows(target.path, "approval_resume_outcomes") == []
    assert rows(target.path, "budgets")[0][4] == 0
    assert resume_case(target).attempt.code == "COMMITTED"
    assert len(rows(target.path, "approval_resume_outcomes")) == 1


def test_two_resumes_cannot_double_commit_or_overspend(tmp_path: Path) -> None:
    target = case(tmp_path)
    authority = HostAuthority(barrier=threading.Barrier(2))
    results: list[ActionResult] = []

    def run() -> None:
        results.append(resume_case(target, authority=authority))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not any(thread.is_alive() for thread in threads)
    assert len(results) == 2
    assert sum(item.attempt.code == "COMMITTED" for item in results) >= 1
    assert all(
        item.execution is not None and item.execution.execution_id == target.execution_id
        for item in results
        if item.attempt.code == "COMMITTED"
    )
    assert rows(target.path, "purchase_orders")[0][3] == "APPROVED"
    assert rows(target.path, "budgets")[0][4] == 120_000
    assert rows(target.path, "budgets")[0][5] == 2
    assert len(rows(target.path, "approval_resume_outcomes")) == 1


def test_missing_pinned_revision_fails_closed(tmp_path: Path) -> None:
    target = case(tmp_path)

    denied = resume_case(target, revisions=(LATER_GRAPH,))

    assert denied.attempt.code == "DENIED"
    assert rows(target.path, "request_ledger")[0][7] == "AWAITING_APPROVAL"
    assert rows(target.path, "approval_resume_outcomes") == []
    assert rows(target.path, "budgets")[0][4] == 0


def test_tampered_manifest_digest_fails_closed(tmp_path: Path) -> None:
    target = case(tmp_path)
    ledger = rows(target.path, "request_ledger")[0]
    document = deserialize(str(ledger[8]))
    assert document is not None
    raw_intent = document["material_intent"]
    assert isinstance(raw_intent, dict)
    intent = dict(cast(dict[str, object], raw_intent))
    intent["manifest_digest"] = "sha256:" + "0" * 64
    tampered = dict(document)
    tampered["material_intent"] = intent
    update(
        target.path,
        "UPDATE request_ledger SET payload = ? WHERE execution_id = ?",
        (serialize(tampered), target.execution_id),
    )

    denied = resume_case(target)

    assert denied.attempt.code == "DENIED"
    assert rows(target.path, "request_ledger")[0][7] == "AWAITING_APPROVAL"
    assert rows(target.path, "approval_resume_outcomes") == []
