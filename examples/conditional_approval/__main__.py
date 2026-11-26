"""Executable conditional-approval consumer example.

Run from the repository root after ``uv sync``:

    uv run python -m examples.conditional_approval

Every scenario builds a fresh file-backed SQLite database, calls only public
engine ports through ``consumer``, and asserts the observed outcome. The CLI
reports the durable business facts through authorized reads; the matching
integration test additionally reads them from an independent connection.
"""

from __future__ import annotations

import threading
from pathlib import Path

from codology import DefinitionKey
from codology.engine import ActionResult
from codology.relay import PermanentDelivery, TransientDelivery
from examples.conditional_approval import consumer, database, wiring
from examples.conditional_approval import declarations as d

_directory = Path(".tmp/conditional-approval")
APPROVED = "APPROVED"
AWAITING = "AWAITING_APPROVAL"
COMMITTED = "COMMITTED"
ROOT_KEY = DefinitionKey(d.ROOT, "2.0.0")


def _show(label: str, actual: object, expected: object) -> None:
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"
    print(f"{label}: {actual}")


def _open(name: str, **seed: object) -> tuple[Path, wiring.Host]:
    path = wiring.install(_directory / name, **seed)
    return path, wiring.open_host(path)


def _refs(host: wiring.Host) -> tuple[object, object]:
    order = consumer.typed_ref(host, wiring.ORDER_KEY, d.PurchaseOrder, "PO-1")
    budget = consumer.typed_ref(host, wiring.BUDGET_KEY, d.Budget, "B-1")
    return order, budget


def _invoke(host: wiring.Host) -> ActionResult:
    order, budget = _refs(host)
    return consumer.request_approval(
        host,
        order=order,  # type: ignore[arg-type]
        budget=budget,  # type: ignore[arg-type]
        request_key=wiring.REQUEST_KEY,
        reason=wiring.REASON,
    )


def below_threshold() -> None:
    """A small order commits without an approval and its effect relays once."""
    print("\n[below threshold]")
    _, host = _open("below.sqlite3", amount=99_999)
    result = _invoke(host)
    _show("invoke", result.attempt.code, COMMITTED)
    assert result.execution is not None
    reconciled = consumer.reconcile_request(host, ROOT_KEY, wiring.REQUEST_KEY)
    _show("reconcile", reconciled.attempt.code, COMMITTED)
    _show(
        "same execution",
        reconciled.execution is not None
        and reconciled.execution.execution_id == result.execution.execution_id,
        True,
    )
    execution_id = result.execution.execution_id
    _show("effect before relay", consumer.effect_status(host, execution_id)[0].status, "PENDING")
    _show("relay", consumer.relay_once(host)[0].status, "DELIVERED")
    _show("effect after relay", consumer.effect_status(host, execution_id)[0].status, "DELIVERED")
    _show("orders visible", consumer.find_orders(host, status=APPROVED).count, 1)


def waiting_restart_and_pin() -> None:
    """Waiting survives a fresh host and a changed default revision."""
    print("\n[waiting, restart, pinned replay]")
    path, host = _open("waiting.sqlite3", amount=120_000)
    first = _invoke(host)
    _show("invoke", first.attempt.code, AWAITING)
    assert first.execution is not None and first.execution.required_approval is not None
    execution_id = first.execution.execution_id
    approval = first.execution.required_approval
    _show("outbox rows while waiting", database.count_rows(path, "outbox"), 0)
    _show("orders still pending", consumer.find_orders(host).count, 1)

    reopened = wiring.open_host(path)
    order, budget = _refs(reopened)
    replay = consumer.replay_on_new_default(
        reopened,
        order=order,  # type: ignore[arg-type]
        budget=budget,  # type: ignore[arg-type]
        request_key=wiring.REQUEST_KEY,
        reason=wiring.REASON,
    )
    _show("replay on newer default", replay.attempt.code, AWAITING)
    _show(
        "same execution",
        replay.execution is not None and replay.execution.execution_id == execution_id,
        True,
    )
    _show(
        "callback",
        consumer.decide(reopened, execution_id, approval).attempt.reason,
        "APPROVED",
    )
    finished = consumer.resume_execution(reopened, execution_id, approval.callback_key)
    _show("resume", finished.attempt.code, COMMITTED)
    _show("orders approved", consumer.find_orders(reopened, status=APPROVED).count, 1)


def deny_duplicate_and_reject() -> None:
    """Denied callbacks never claim the key; duplicates and reject stay bounded."""
    print("\n[callback deny, duplicate, reject]")
    path, host = _open("callbacks.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    approval = pending.execution.required_approval

    _show(
        "outsider",
        consumer.decide(
            host,
            execution_id,
            approval,
            principal=wiring.outsider(),
            authority=wiring.HostAuthority(roles=(), permissions=()),
        ).attempt.code,
        "DENIED",
    )
    _show(
        "changed payload",
        consumer.decide(host, execution_id, approval, fingerprint="0" * 64).attempt.reason,
        "KEY_MISUSE",
    )
    reconciled = consumer.reconcile_execution(host, execution_id)
    _show(
        "still waiting",
        reconciled.execution is not None and reconciled.execution.status == AWAITING,
        True,
    )

    consumer.decide(host, execution_id, approval)
    repeat = consumer.decide(host, execution_id, approval)
    _show(
        "duplicate decision", repeat.execution is not None and repeat.execution.deduplicated, True
    )
    _show("decision rows", database.count_rows(path, "approval_decisions"), 1)

    _, other = _open("reject.sqlite3", amount=120_000)
    waiting = _invoke(other)
    assert waiting.execution is not None and waiting.execution.required_approval is not None
    rejected = consumer.decide(
        other,
        waiting.execution.execution_id,
        waiting.execution.required_approval,
        decision="REJECT",
        reason="budget withdrawn",
    )
    _show("reject", rejected.attempt.code, "REJECTED")
    _show("rejected business writes", database.count_rows(other.path, "outbox"), 0)


def reapproval() -> None:
    """A changed material intent mints a new approval before committing."""
    print("\n[reapproval]")
    path, host = _open("reapproval.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    old = pending.execution.required_approval
    consumer.decide(host, execution_id, old)

    database.update_amount(path, 150_000)
    changed = consumer.resume_execution(host, execution_id, old.callback_key)
    _show("resume after change", changed.attempt.code, AWAITING)
    _show("reason", changed.attempt.reason, "REAPPROVAL_REQUIRED")
    assert changed.execution is not None and changed.execution.required_approval is not None
    new = changed.execution.required_approval
    _show("new callback key", new.callback_key != old.callback_key, True)
    _show(
        "old key",
        consumer.resume_execution(host, execution_id, old.callback_key).attempt.reason,
        "KEY_MISUSE",
    )

    consumer.decide(host, execution_id, new)
    finished = consumer.resume_execution(host, execution_id, new.callback_key)
    _show("resume with new approval", finished.attempt.code, COMMITTED)
    _show("reserved", consumer.find_budget(host).values["reserved"], 150_000)


def contention() -> None:
    """Two resumes of one approval cannot reserve the budget twice."""
    print("\n[resume contention]")
    path, host = _open("contention.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    key = pending.execution.required_approval.callback_key
    consumer.decide(host, execution_id, pending.execution.required_approval)
    host.authority = wiring.HostAuthority(barrier=threading.Barrier(2))

    results: list[ActionResult] = []

    def run() -> None:
        results.append(consumer.resume_execution(host, execution_id, key))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not any(thread.is_alive() for thread in threads)
    committed = [item for item in results if item.attempt.code == COMMITTED]
    assert len(committed) >= 1, f"no resume committed: {[item.attempt for item in results]}"
    print(f"committed resumes: {len(committed)} (one commit, later ones replayed)")
    _show(
        "same execution",
        committed[0].execution is not None and committed[0].execution.execution_id == execution_id,
        True,
    )
    _show("resume outcomes", database.count_rows(path, "approval_resume_outcomes"), 1)
    _show("budget version", consumer.find_budget(host).instance_version, 2)


def lost_ack() -> None:
    """A lost commit acknowledgement reconciles to the durable commit."""
    print("\n[lost commit acknowledgement]")
    path, host = _open("lost-ack.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    approval = pending.execution.required_approval
    consumer.decide(host, execution_id, approval)

    uncertain = consumer.resume_execution(
        host,
        execution_id,
        approval.callback_key,
        provider=wiring.InterruptedProvider(path, mode="after"),  # type: ignore[arg-type]
    )
    _show("uncertain resume", uncertain.attempt.code, "UNKNOWN")
    fresh = wiring.open_host(path)
    by_key = consumer.reconcile_request(fresh, ROOT_KEY, wiring.REQUEST_KEY)
    _show("reconcile by key", by_key.attempt.code, COMMITTED)
    by_id = consumer.reconcile_execution(fresh, execution_id)
    _show(
        "reconcile by id", by_id.execution is not None and by_id.execution.status == COMMITTED, True
    )
    retry = consumer.resume_execution(fresh, execution_id, approval.callback_key)
    _show("retry", retry.attempt.code, COMMITTED)
    _show("deduplicated", retry.execution is not None and retry.execution.deduplicated, True)
    _show("resume outcomes", database.count_rows(path, "approval_resume_outcomes"), 1)


def relay_failures() -> None:
    """Transient, permanent and lost-ack deliveries keep the execution committed."""
    print("\n[relay failures]")
    path, host = _open("relay.sqlite3", amount=120_000)
    pending = _invoke(host)
    assert pending.execution is not None and pending.execution.required_approval is not None
    execution_id = pending.execution.execution_id
    approval = pending.execution.required_approval
    consumer.decide(host, execution_id, approval)
    _show(
        "resume",
        consumer.resume_execution(host, execution_id, approval.callback_key).attempt.code,
        COMMITTED,
    )

    calls: list[int] = []

    def transient(message: object) -> Exception | None:
        calls.append(1)
        return TransientDelivery("receiver temporarily unavailable") if len(calls) == 1 else None

    failed_store = wiring.SQLiteRelayStore(path)
    failed_receiver = wiring.SQLiteLocalReceiver(path, before_write=transient)
    deliveries = consumer.relay_once(host, store=failed_store, receiver=failed_receiver)
    _show("transient", deliveries[0].status, "PENDING_RETRY")
    _show(
        "effect status",
        consumer.effect_status(host, execution_id, store=failed_store)[0].status,
        "PENDING_RETRY",
    )
    _show("retry", consumer.relay_once(host)[0].status, "DELIVERED")
    _show("notifications", database.count_rows(path, "local_notifications"), 1)

    permanent_path, permanent_host = _open("permanent.sqlite3", amount=120_000)
    waiting = _invoke(permanent_host)
    assert waiting.execution is not None and waiting.execution.required_approval is not None
    consumer.decide(
        permanent_host, waiting.execution.execution_id, waiting.execution.required_approval
    )
    consumer.resume_execution(
        permanent_host,
        waiting.execution.execution_id,
        waiting.execution.required_approval.callback_key,
    )
    permanent_receiver = wiring.SQLiteLocalReceiver(
        permanent_path,
        before_write=lambda message: PermanentDelivery("sink rejected the notification"),
    )
    permanent_delivery = consumer.relay_once(
        permanent_host, store=wiring.SQLiteRelayStore(permanent_path), receiver=permanent_receiver
    )
    _show("permanent", permanent_delivery[0].status, "FAILED")
    _show(
        "notifications after permanent",
        database.count_rows(permanent_path, "local_notifications"),
        0,
    )

    ack_path, ack_host = _open("relay-ack.sqlite3", amount=120_000)
    waiting = _invoke(ack_host)
    assert waiting.execution is not None and waiting.execution.required_approval is not None
    consumer.decide(ack_host, waiting.execution.execution_id, waiting.execution.required_approval)
    consumer.resume_execution(
        ack_host, waiting.execution.execution_id, waiting.execution.required_approval.callback_key
    )
    acks: list[int] = []

    def lost_ack(message: object) -> Exception | None:
        acks.append(1)
        return TransientDelivery("ack lost after durable write") if len(acks) == 1 else None

    ack_store = wiring.SQLiteRelayStore(ack_path)
    first = consumer.relay_once(
        ack_host,
        store=ack_store,
        receiver=wiring.SQLiteLocalReceiver(ack_path, after_write=lost_ack),
    )
    _show("lost relay ack", first[0].status, "PENDING_RETRY")
    _show("durable notification", database.count_rows(ack_path, "local_notifications"), 1)
    replay = consumer.relay_once(ack_host, store=ack_store)
    _show("relay replay", replay[0].replayed, True)
    _show("notifications after replay", database.count_rows(ack_path, "local_notifications"), 1)


def main(directory: Path | None = None) -> int:
    """Run every documented scenario; a wrong outcome raises before success."""
    global _directory
    _directory = directory or _directory
    _directory.mkdir(parents=True, exist_ok=True)
    below_threshold()
    waiting_restart_and_pin()
    deny_duplicate_and_reject()
    reapproval()
    contention()
    lost_ack()
    relay_failures()
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
