"""Executable Procurement/Finance example: authorized read then atomic invoke.

Run from the repository root:

    uv run python -m examples.atomic_approval

The script builds a fresh file-backed SQLite database, reads a pending order
through ``query``, takes its typed ref, and invokes the tier-2 approval action.
It then replays the same request key, reconciles the stored result from a fresh
connection, and shows the refusal paths. Every expected outcome is asserted, so
a regression makes the process exit non-zero instead of printing success.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from codology import (
    MinorMoney,
    NoSharedTransaction,
    OrderBy,
    ReadDenied,
    UnsupportedSecureQuery,
    bind_action,
    query,
)
from codology.engine import reconcile
from examples.atomic_approval import consumer
from examples.atomic_approval.database import build_database
from examples.atomic_approval.wiring import (
    APPROVE_KEY,
    BUDGET_KEY,
    ORDER_KEY,
    alice,
    bob,
    bound_approval,
    grants_for,
    linked_graph,
    outsider,
    published_snapshot,
    split_deployment,
    sqlite_provider,
)
from examples.procurement_finance import runtime

DEFAULT_DATABASE = Path(".tmp/atomic_approval/approval.sqlite3")
REQUEST_KEY = "tenant-a:alice:approve:PO-1:001"
AMOUNT = MinorMoney.from_decimal(Decimal("40000"), "USD")


def _field(values: Mapping[str, object], name: str) -> object:
    return values[name]


def main(database: Path | None = None) -> int:
    """Run the documented consumer flow and print every observed outcome."""
    path = build_database(database if database is not None else DEFAULT_DATABASE)
    print(f"database: {path}")
    linked = linked_graph()
    bound = bound_approval()
    provider = sqlite_provider(path)
    principal = alice()
    grants = grants_for(principal)

    print("== Query ==")
    pending = consumer.find_orders(provider, principal, grants)
    assert pending.count == 2, pending.count
    print(f"visible PENDING_APPROVAL count={pending.count}")
    for row in pending.rows:
        values = row.values
        print(
            f"  {row.key} status={_field(values, 'status')!r} "
            f"approved_amount={_field(values, 'approved_amount')!r} "
            f"version={row.instance_version}"
        )
    order_row = next(row for row in pending.rows if row.key == "PO-1")
    budget_row = consumer.find_budget(provider, principal, grants)
    print(
        f"budget {budget_row.key} ceiling={_field(budget_row.values, 'ceiling')} "
        f"reserved={_field(budget_row.values, 'reserved')} version={budget_row.instance_version}"
    )

    order_ref = order_row.as_ref()
    budget_ref = budget_row.as_ref()

    print("== Invoke (tier-2 ATOMIC) ==")
    result = consumer.approve(
        provider=provider,
        linked=linked,
        bound=bound,
        principal=principal,
        grants=grants,
        order=order_ref,
        budget=budget_ref,
        reason="approved after budget check",
        amount=AMOUNT,
        request_key=REQUEST_KEY,
    )
    assert result.attempt.code == "COMMITTED", result.attempt
    assert result.execution is not None
    assert len(result.writes) == 2
    assert all(write.rowcount == 1 for write in result.writes)
    assert len({write.transaction for write in result.writes}) == 1
    print(f"code={result.attempt.code} execution={result.execution.execution_id}")
    print(
        "children="
        + ", ".join(f"{key.identity}@{key.version}" for key in result.execution.children)
    )
    for write in result.writes:
        print(f"write {write.resource}/{write.key} rowcount={write.rowcount}")
    print("shared_transaction=True")

    print("== Replay same key/intent ==")
    replay = consumer.approve(
        provider=provider,
        linked=linked,
        bound=bound,
        principal=principal,
        grants=grants,
        order=order_ref,
        budget=budget_ref,
        reason="approved after budget check",
        amount=AMOUNT,
        request_key=REQUEST_KEY,
    )
    assert replay.attempt.code == "COMMITTED", replay.attempt
    assert replay.execution is not None and replay.execution.deduplicated
    assert replay.writes == ()
    assert result.execution is not None
    assert replay.execution.execution_id == result.execution.execution_id
    print(
        f"code={replay.attempt.code} deduplicated={replay.execution.deduplicated} "
        f"execution={replay.execution.execution_id} writes={len(replay.writes)}"
    )

    print("== Reconcile from a fresh connection ==")
    stored = reconcile(
        provider=sqlite_provider(path),
        principal=principal,
        action=APPROVE_KEY,
        request_key=REQUEST_KEY,
    )
    assert stored.execution is not None and stored.execution.deduplicated
    assert stored.execution.execution_id == result.execution.execution_id
    print(f"code={stored.attempt.code} execution={stored.execution.execution_id}")

    print("== Query after commit ==")
    still_pending = consumer.find_orders(provider, principal, grants)
    approved = consumer.find_orders(provider, principal, grants, status="APPROVED")
    assert still_pending.count == 1 and still_pending.rows[0].key == "PO-2"
    assert approved.count == 1 and approved.rows[0].key == "PO-1"
    print(
        f"PENDING_APPROVAL count={still_pending.count}; APPROVED count={approved.count} "
        f"(PO-1 approved_amount={_field(approved.rows[0].values, 'approved_amount')} "
        f"version={approved.rows[0].instance_version})"
    )

    print("== Refusals ==")
    try:
        consumer.find_orders(provider, outsider(), grants_for(outsider()))
    except ReadDenied:
        print("read without a live grant: ReadDenied")
    else:
        raise AssertionError("a principal without a read permission was allowed to query")

    narrow = consumer.find_orders(provider, principal, grants_for(principal, scopes=("team-2",)))
    assert narrow.rows == () and narrow.count == 0
    print("query outside the granted scope: rows=0 count=0")

    try:
        query(
            provider=provider,
            principal=principal,
            grant=grants[ORDER_KEY],
            from_=ORDER_KEY,
            target=runtime.PurchaseOrder,
            order=OrderBy("created_at"),
            predicate=None,
            traverse="budget",
        )
    except UnsupportedSecureQuery:
        print("unsupported traversal: UnsupportedSecureQuery")
    else:
        raise AssertionError("an unsupported traversal returned data")

    bob_grants = grants_for(bob())
    denied = consumer.approve(
        provider=provider,
        linked=linked,
        bound=bound,
        principal=bob(),
        grants=bob_grants,
        order=order_ref,
        budget=budget_ref,
        reason="approved after budget check",
        amount=AMOUNT,
        request_key="tenant-a:bob:approve:PO-1:001",
    )
    assert denied.attempt.code == "DENIED" and denied.execution is None
    print(f"invoke without approve: {denied.attempt.code} (execution=None)")

    try:
        bind_action(published_snapshot(), split_deployment(), APPROVE_KEY)
    except NoSharedTransaction:
        print("split binding: NoSharedTransaction")
    else:
        raise AssertionError("binding accepted two independent sessions")

    unlocked = query(
        provider=provider,
        principal=principal,
        grant=grants[BUDGET_KEY],
        from_=BUDGET_KEY,
        target=runtime.Budget,
        order=OrderBy("id"),
        limit=5,
        count_requested=True,
    )
    assert unlocked.count == 1 and unlocked.rows[0].key == "B-1"
    print(f"tenant isolation: budget count={unlocked.count}")

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
