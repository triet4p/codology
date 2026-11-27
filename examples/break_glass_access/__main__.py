"""Run the simulated break-glass example: Load, Link, Snapshot, and failures.

Run from the repository root:

    uv run python -m examples.break_glass_access
    uv run python -m examples.break_glass_access --runtime

Without arguments the example is static and touches no database. With
``--runtime`` each scenario opens its own seeded SQLite file, drives the public
engine ports and asserts the durable outcome, including a read back through
connections independent of the engine.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from codology import AnyOfExpr, ComparisonExpr, FieldPath, LiteralValue, RequiredApproval
from codology.engine import ActionResult
from codology.linking import LinkError
from codology.loading import LoadError
from examples.break_glass_access import consumer, database, wiring
from examples.break_glass_access.model import (
    GRANT_ACCESS_KEY,
    RECORD_SESSION_KEY,
    build_snapshot,
    link_model,
    load_model,
)
from examples.break_glass_access.scenarios import SCENARIOS, handler_is_not_executed

RUNTIME_DIRECTORY = Path(".tmp/break-glass-access")
REQUEST_KEY = f"{wiring.TENANT}:{wiring.REQUESTER}:grant:AGR-1:001"
AWAITING = "AWAITING_APPROVAL"
COMMITTED = "COMMITTED"


def describe(error: BaseException) -> str:
    """Render a static error with the context Load or Link attached to it."""
    if isinstance(error, LoadError | LinkError):
        return (
            f"{type(error).__name__} "
            f"[module={error.module!r}, identity={error.identity!r}, field={error.field!r}]: "
            f"{error}"
        )
    return f"{type(error).__name__}: {error}"


def _condition_label(condition: object) -> str:
    """Render one normalized approval comparison for the terminal."""
    if isinstance(condition, ComparisonExpr):
        left = condition.left
        right = condition.right
        if isinstance(left, FieldPath) and isinstance(right, LiteralValue):
            path = ".".join((left.parameter, *left.path))
            return f"{path} {condition.operator} {right.value!r}"
    return type(condition).__name__


def static_main() -> int:
    """Print the success path, the handler probe, and every expected failure."""
    loaded = load_model()
    print("== Load ==")
    for identity in sorted(loaded.definitions):
        item = loaded.definitions[identity]
        print(f"  {identity}@{item.version} owner={item.owner}")

    linked = link_model()
    print("== Link ==")
    for key in (GRANT_ACCESS_KEY, RECORD_SESSION_KEY):
        print(f"  {key.identity}@{key.version}:")
        for reference in linked.definitions[key.identity].references:
            target = (
                reference.target.identity
                if reference.target.identity is not None
                else reference.target.declaration.__qualname__
            )
            print(f"    {reference.field} -> {target}")

    published = build_snapshot()
    entry = published.lookup(GRANT_ACCESS_KEY.identity, GRANT_ACCESS_KEY.version)
    print("== Snapshot ==")
    print(f"  {entry.identity}@{entry.version} kind={entry.kind} owner={entry.owner}")
    print(f"  permission={entry.permission}")
    print(f"  commitRequirement={entry.commit_requirement} (declared metadata only)")
    approval = entry.approval
    if approval is not None:
        when = approval.when
        print(f"  approval role={approval.role!r} self_approval={approval.self_approval}")
        if isinstance(when, AnyOfExpr):
            print(f"  any_of branches={[_condition_label(part) for part in when.parts]}")
        else:
            print(f"  when={type(when).__name__}")
    print(f"  versions(security_audit.session)={published.versions_of('security_audit.session')}")
    print(f"  handler probe after Load/Link/Snapshot: {handler_is_not_executed()}")

    print("== Expected failures ==")
    for label, scenario in SCENARIOS:
        print(f"  {label}: {describe(scenario())}")
    return 0


def _show(label: str, actual: object, expected: object) -> None:
    assert actual == expected, f"{label}: expected {expected!r}, got {actual!r}"
    print(f"  {label}: {actual}")


def _open(directory: Path, name: str, **seed: object) -> tuple[Path, wiring.Host]:
    path = wiring.install(directory / name, **seed)
    return path, wiring.open_host(path)


def _awaiting(host: wiring.Host) -> tuple[ActionResult, str, RequiredApproval]:
    """Invoke the root once and return its waiting execution facts."""
    result = consumer.request_access(host, request_key=REQUEST_KEY)
    assert result.attempt.code == AWAITING, result.attempt
    assert result.execution is not None and result.execution.required_approval is not None
    return result, result.execution.execution_id, result.execution.required_approval


def _below_threshold(directory: Path) -> None:
    """A short, routine request commits both writes and its effect without approval."""
    print("\n[below threshold, not sensitive]")
    path, host = _open(directory, "below.sqlite3", duration_minutes=30)
    result = consumer.request_access(host, request_key=REQUEST_KEY)
    _show("invoke", result.attempt.code, COMMITTED)
    assert result.execution is not None
    execution_id = result.execution.execution_id
    _show("request row", database.grant_state(path), ("GRANTED", 30, "ROUTINE", 2))
    _show("session row", database.session_state(path), ("OPEN", 2))
    _show(
        "ledger status",
        [(row[0], row[1]) for row in database.ledger_state(path)],
        [("1.0.0", COMMITTED)],
    )
    _show("ledger execution", [row[2] for row in database.ledger_state(path)], [execution_id])
    _show("outbox rows", len(database.outbox_state(path)), 1)
    _show("decisions", database.count_rows(path, "approval_decisions"), 0)
    _show("relay", consumer.relay_once(host)[0].status, "DELIVERED")
    _show("notifications", database.count_rows(path, "local_notifications"), 1)
    _show("effect state", database.effect_state(path), [("DELIVERED", 1)])
    _show("relay replay", consumer.relay_once(host), ())
    _show(
        "handler not rerun",
        (database.grant_state(path), database.session_state(path)),
        (("GRANTED", 30, "ROUTINE", 2), ("OPEN", 2)),
    )


def _predicate_branches(directory: Path) -> None:
    """Two independent approval branches park the execution without any write."""
    print("\n[approval predicate branches]")
    branches = (
        ("duration.sqlite3", 60, "ROUTINE", "duration 60"),
        ("sensitivity.sqlite3", 15, "CRITICAL", "critical 15"),
    )
    for name, minutes, sensitivity, label in branches:
        path, host = _open(directory, name, duration_minutes=minutes, sensitivity=sensitivity)
        result, execution_id, approval = _awaiting(host)
        _show(f"{label} invoke", result.attempt.code, AWAITING)
        _show(f"{label} execution id", bool(execution_id), True)
        _show(f"{label} role", approval.role, wiring.APPROVAL_ROLE)
        _show(
            f"{label} request row",
            database.grant_state(path),
            ("PENDING", minutes, sensitivity, 1),
        )
        _show(f"{label} session row", database.session_state(path), ("NEW", 1))
        _show(f"{label} ledger", [row[1] for row in database.ledger_state(path)], [AWAITING])
        _show(f"{label} outbox", database.outbox_state(path), [])
        _show(f"{label} decisions", database.count_rows(path, "approval_decisions"), 0)
        _show(f"{label} relay", consumer.relay_once(host), ())


def _wrong_authority(directory: Path) -> None:
    """A denied callback neither claims the key nor ends the pending execution."""
    print("\n[wrong authority]")
    path, host = _open(directory, "wrong-authority.sqlite3", duration_minutes=90)
    _, execution_id, approval = _awaiting(host)
    denied = consumer.approve_access(
        host,
        execution_id,
        approval,
        principal=host.outsider,
        authority=wiring.HostAuthority(roles=(), permissions=()),
    )
    _show("decision", denied.attempt.code, "DENIED")
    _show("no decision stored", denied.decision, None)
    _show("ledger", [row[1] for row in database.ledger_state(path)], [AWAITING])
    _show(
        "business rows",
        (database.grant_state(path), database.session_state(path)),
        (("PENDING", 90, "ROUTINE", 1), ("NEW", 1)),
    )
    _show("outbox", database.outbox_state(path), [])
    _show("decisions", database.count_rows(path, "approval_decisions"), 0)
    _show("audited attempts", database.count_rows(path, "approval_audit"), 1)


def _approve_resume_replay_relay(directory: Path) -> None:
    """Approve without committing, then resume once and relay only after commit."""
    print("\n[approve, resume, replay, relay]")
    path, host = _open(directory, "flow.sqlite3", duration_minutes=90)
    request = consumer.grant_ref(host)
    session = consumer.session_ref(host)
    waiting = consumer.request_access(
        host, request_key=REQUEST_KEY, request=request, session=session
    )
    _show("invoke", waiting.attempt.code, AWAITING)
    assert waiting.execution is not None and waiting.execution.required_approval is not None
    execution_id = waiting.execution.execution_id
    approval = waiting.execution.required_approval
    _show("outbox while waiting", database.outbox_state(path), [])
    _show("relay while waiting", consumer.relay_once(host), ())

    approved = consumer.approve_access(host, execution_id, approval)
    _show("approve", approved.attempt.reason, "APPROVED")
    _show(
        "not committed yet",
        (database.grant_state(path), database.session_state(path)),
        (("PENDING", 90, "ROUTINE", 1), ("NEW", 1)),
    )
    _show("outbox after approve", database.outbox_state(path), [])
    _show("ledger after approve", [row[1] for row in database.ledger_state(path)], [AWAITING])

    finished = consumer.resume_access(host, execution_id, approval.callback_key)
    _show("resume", finished.attempt.code, COMMITTED)
    _show("request committed", database.grant_state(path), ("GRANTED", 90, "ROUTINE", 2))
    _show("session committed", database.session_state(path), ("OPEN", 2))
    _show(
        "ledger committed",
        [(row[0], row[1]) for row in database.ledger_state(path)],
        [("1.0.0", COMMITTED)],
    )
    _show("outbox committed", len(database.outbox_state(path)), 1)

    replay = consumer.request_access(
        host, request_key=REQUEST_KEY, request=request, session=session
    )
    _show("replay", replay.attempt.code, COMMITTED)
    _show(
        "same execution",
        replay.execution is not None and replay.execution.execution_id == execution_id,
        True,
    )
    _show(
        "deduplicated",
        replay.execution is not None and replay.execution.deduplicated,
        True,
    )
    _show(
        "replay wrote nothing",
        (
            database.grant_state(path),
            database.session_state(path),
            len(database.outbox_state(path)),
            database.count_rows(path, "approval_resume_outcomes"),
        ),
        (("GRANTED", 90, "ROUTINE", 2), ("OPEN", 2), 1, 1),
    )

    _show("relay", consumer.relay_once(host)[0].status, "DELIVERED")
    _show("notifications", database.count_rows(path, "local_notifications"), 1)
    _show("effect state", database.effect_state(path), [("DELIVERED", 1)])
    _show("relay replay", consumer.relay_once(host), ())
    _show(
        "handler not rerun by relay",
        (database.grant_state(path), database.session_state(path)),
        (("GRANTED", 90, "ROUTINE", 2), ("OPEN", 2)),
    )


def runtime_main(directory: Path | None = None) -> int:
    """Run every runtime scenario on its own seeded database."""
    target = directory or RUNTIME_DIRECTORY
    target.mkdir(parents=True, exist_ok=True)
    _below_threshold(target)
    _predicate_branches(target)
    _wrong_authority(target)
    _approve_resume_replay_relay(target)
    print("\nRUNTIME CHECKS PASSED")
    return 0


def main(argv: Sequence[str] | None = None, *, directory: Path | None = None) -> int:
    """Dispatch the static tour or the SQLite runtime scenarios."""
    arguments = list(argv or ())
    if arguments == ["--runtime"]:
        return runtime_main(directory)
    if arguments:
        raise SystemExit("usage: python -m examples.break_glass_access [--runtime]")
    return static_main()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
