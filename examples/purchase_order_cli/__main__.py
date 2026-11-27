"""Independent CLI consumer of the ``ApprovePurchaseOrder`` action contract.

The CLI calls the public engine ports only: an authorized ``query`` issues the
rows, ``row.as_ref()`` supplies the typed refs, and ``invoke``, ``approve``,
``resume``, ``reconcile``/``reconcile_execution`` and ``deliver_committed``
decide the outcome. The conditional-approval host supplies the linked graph,
the bound deployment, principals, read grants and live approver authority; the
CLI embeds no threshold, role/permission table, budget rule, SQL or fingerprint
builder, and it never imports the sample consumer.

Run from the repository root after ``uv sync``::

    uv run python -m examples.purchase_order_cli install --db .tmp/cli/orders.sqlite3
    uv run python -m examples.purchase_order_cli query --db .tmp/cli/orders.sqlite3
    uv run python -m examples.purchase_order_cli invoke --db .tmp/cli/orders.sqlite3 \\
        --order PO-1 --budget B-1 --reason "approved after budget check" \\
        --request-key tenant-a:alice:approve:PO-1:001

Each command prints one JSON document and exits 0 even for a legitimate
``AWAITING_APPROVAL``, ``DENIED`` or ``UNKNOWN`` envelope; usage and fixture
errors exit 2. An unconfirmed commit is answered with the ``reconcile`` call
that keeps the caller's original request key.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from codology import (
    AllOf,
    Comparison,
    DefinitionKey,
    OrderBy,
    QueryPredicate,
    QueryRow,
    query,
)
from codology.decision import approve
from codology.engine import invoke, reconcile
from codology.relay import deliver_committed, read_effect_status
from codology.resume import ResumeProvider, reconcile_execution, resume
from examples.conditional_approval import wiring
from examples.purchase_order_cli import envelopes
from examples.purchase_order_cli.host import CALLERS, Caller, CliHost, install, open_host

AWAITING = "AWAITING_APPROVAL"


class CliError(RuntimeError):
    """A command cannot proceed with the values the caller supplied."""


def _caller(host: CliHost, name: str | None, *, default: str) -> Caller:
    return host.caller(name or default)


def _granted(host: CliHost, caller: Caller, resource: str) -> tuple[DefinitionKey, type[object]]:
    definition, target = host.resource(resource)
    if definition not in caller.grants:
        raise CliError(
            f"caller {caller.name!r} has no host-issued read grant for "
            f"{definition.identity!r}; the host owns grants, not the CLI."
        )
    return definition, target


def _authorized_row(host: CliHost, caller: Caller, resource: str, key: str) -> QueryRow[object]:
    definition, target = _granted(host, caller, resource)
    page = query(
        provider=host.host.provider,
        principal=caller.principal,
        grant=caller.grants[definition],
        from_=definition,
        target=target,
        order=OrderBy("id"),
        predicate=Comparison("id", "==", key),
        limit=1,
        count_requested=True,
    )
    if not page.rows:
        raise CliError(f"{definition.identity}:{key} is not visible to caller {caller.name!r}.")
    return page.rows[0]


def _run_install(args: argparse.Namespace) -> dict[str, object]:
    path = install(args.db, amount=args.amount, status=args.status, ceiling=args.ceiling)
    return {
        "command": "install",
        "db": str(path),
        "seeded": {"amount": args.amount, "status": args.status, "ceiling": args.ceiling},
    }


def _run_query(args: argparse.Namespace) -> dict[str, object]:
    host = open_host(args.db)
    caller = _caller(host, args.as_principal, default="requester")
    definition, target = _granted(host, caller, args.resource)
    parts: list[Comparison] = []
    if args.id is not None:
        parts.append(Comparison("id", "==", args.id))
    if args.status is not None:
        if args.resource != "orders":
            raise CliError("--status filters orders only; budgets have no status column.")
        parts.append(Comparison("status", "==", args.status))
    predicate: QueryPredicate | None
    if not parts:
        predicate = None
    elif len(parts) == 1:
        predicate = parts[0]
    else:
        predicate = AllOf(tuple(parts))
    page = query(
        provider=host.host.provider,
        principal=caller.principal,
        grant=caller.grants[definition],
        from_=definition,
        target=target,
        order=OrderBy("id"),
        predicate=predicate,
        limit=args.limit,
        count_requested=True,
    )
    return {
        "command": "query",
        "db": str(host.path),
        "caller": caller.name,
        "resource": args.resource,
        "definition": envelopes.action_document(definition),
        "page": envelopes.page_document(page),
    }


def _run_invoke(args: argparse.Namespace) -> dict[str, object]:
    host = open_host(args.db)
    caller = _caller(host, args.as_principal, default="requester")
    order = _authorized_row(host, caller, "orders", args.order)
    budget = _authorized_row(host, caller, "budgets", args.budget)
    result = invoke(
        linked=host.host.graphs[0],
        action=wiring.ROOT_KEY,
        bound=host.host.bound,
        provider=host.host.provider,
        principal=caller.principal,
        grants=caller.grants,
        parameters={
            "order": order.as_ref(),
            "budget": budget.as_ref(),
            "reason": args.reason,
        },
        request_key=args.request_key,
    )
    return {
        "command": "invoke",
        "db": str(host.path),
        "caller": caller.name,
        "action": envelopes.action_document(wiring.ROOT_KEY),
        "request_key": args.request_key,
        "refs": {
            "order": envelopes.row_ref_document(order),
            "budget": envelopes.row_ref_document(budget),
        },
        "result": envelopes.action_result_document(result),
        "next": envelopes.next_step(result, request_key=args.request_key),
    }


def _run_approve(args: argparse.Namespace) -> dict[str, object]:
    if not args.reason.strip():
        raise CliError("--reason must name why the approver accepted; the decision gate stores it.")
    host = open_host(args.db)
    caller = _caller(host, args.as_principal, default="approver")
    result = approve(
        provider=host.host.provider,
        authority_provider=caller.authority,
        principal=caller.principal,
        execution_id=args.execution_id,
        callback_key=args.callback_key,
        expected_intent_fingerprint=args.fingerprint,
        reason=args.reason,
    )
    return {
        "command": "approve",
        "db": str(host.path),
        "caller": caller.name,
        "result": envelopes.decision_document(result),
        "next": envelopes.next_step(
            result,
            execution_id=args.execution_id,
            callback_key=args.callback_key,
        ),
    }


def _run_resume(args: argparse.Namespace) -> dict[str, object]:
    host = open_host(args.db)
    caller = _caller(host, args.as_principal, default="requester")
    provider: ResumeProvider = host.host.provider
    if args.simulate_lost_ack is not None:
        provider = cast(
            ResumeProvider,
            wiring.InterruptedProvider(host.path, mode=args.simulate_lost_ack),
        )
    result = resume(
        provider=provider,
        revisions=host.host.graphs,
        bound=host.host.bound,
        principal=caller.principal,
        grants=caller.grants,
        execution_id=args.execution_id,
        callback_key=args.callback_key,
        authority_provider=caller.authority,
    )
    return {
        "command": "resume",
        "db": str(host.path),
        "caller": caller.name,
        "simulated_lost_ack": args.simulate_lost_ack,
        "result": envelopes.action_result_document(result),
        "next": envelopes.next_step(
            result,
            execution_id=args.execution_id,
            callback_key=args.callback_key,
        ),
    }


def _run_reconcile(args: argparse.Namespace) -> dict[str, object]:
    host = open_host(args.db)
    if args.request_key is not None:
        result = reconcile(
            provider=host.host.provider,
            principal=host.host.reader,
            action=wiring.ROOT_KEY,
            request_key=args.request_key,
        )
        lookup: dict[str, object] = {"by": "request_key", "request_key": args.request_key}
    else:
        result = reconcile_execution(
            provider=host.host.provider,
            principal=host.host.reader,
            execution_id=args.execution_id,
        )
        lookup = {"by": "execution_id", "execution_id": args.execution_id}
    return {
        "command": "reconcile",
        "db": str(host.path),
        "lookup": lookup,
        "result": envelopes.action_result_document(result),
        "next": envelopes.next_step(
            result,
            execution_id=args.execution_id,
            request_key=args.request_key,
        ),
    }


def _run_relay(args: argparse.Namespace) -> dict[str, object]:
    host = open_host(args.db)
    deliveries = deliver_committed(host.host.store, host.host.receiver)
    document: dict[str, object] = {
        "command": "relay",
        "db": str(host.path),
        "deliveries": [envelopes.delivery_document(delivery) for delivery in deliveries],
    }
    if args.execution_id is not None:
        document["effects"] = [
            envelopes.effect_document(effect)
            for effect in read_effect_status(host.host.store, host.host.reader, args.execution_id)
        ]
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examples.purchase_order_cli",
        description=(
            "Independent CLI consumer of procurement.approve_purchase_order@2.0.0. "
            "The host supplies identities, grants, authority and binding."
        ),
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--db",
        type=Path,
        required=True,
        metavar="PATH",
        help="SQLite fixture created by the install command.",
    )
    common.add_argument(
        "--as",
        dest="as_principal",
        choices=CALLERS,
        default=None,
        help="Host-authored caller identity (default: requester; approve: approver).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    installer = commands.add_parser(
        "install", parents=[common], help="Create the host fixture and relay tables."
    )
    installer.add_argument("--amount", type=int, default=120_000, help="Order amount.")
    installer.add_argument("--status", default="PENDING", help="Seed order status.")
    installer.add_argument("--ceiling", type=int, default=1_000_000, help="Budget ceiling.")
    installer.set_defaults(run=_run_install)

    finder = commands.add_parser(
        "query", parents=[common], help="Read one policy-filtered page of rows."
    )
    finder.add_argument("--resource", choices=("orders", "budgets"), default="orders")
    finder.add_argument("--id", default=None, help="Filter by object key.")
    finder.add_argument("--status", default=None, help="Filter orders by status.")
    finder.add_argument("--limit", type=int, default=20)
    finder.set_defaults(run=_run_query)

    invoker = commands.add_parser(
        "invoke", parents=[common], help="Invoke the root action from query-issued refs."
    )
    invoker.add_argument("--order", required=True, help="Purchase-order key to read.")
    invoker.add_argument("--budget", required=True, help="Budget key to read.")
    invoker.add_argument("--reason", required=True, help="Business reason for the action.")
    invoker.add_argument(
        "--request-key",
        required=True,
        help="Caller-owned key scoped by tenant, principal and action identity.",
    )
    invoker.set_defaults(run=_run_invoke)

    approver = commands.add_parser(
        "approve", parents=[common], help="Approve with the engine-issued callback values."
    )
    approver.add_argument("--execution-id", required=True)
    approver.add_argument("--callback-key", required=True)
    approver.add_argument(
        "--fingerprint",
        required=True,
        help="The engine-issued intent fingerprint from the waiting envelope.",
    )
    approver.add_argument(
        "--reason",
        required=True,
        help="Why the approver accepted; the decision gate stores it.",
    )
    approver.set_defaults(run=_run_approve)

    resumer = commands.add_parser(
        "resume", parents=[common], help="Resume a recorded decision on pinned logic."
    )
    resumer.add_argument("--execution-id", required=True)
    resumer.add_argument("--callback-key", required=True)
    resumer.add_argument(
        "--simulate-lost-ack",
        choices=("before", "after"),
        default=None,
        help="Host-provided fault injection for the unconfirmed-commit path.",
    )
    resumer.set_defaults(run=_run_resume)

    reconciler = commands.add_parser(
        "reconcile", parents=[common], help="Read the authoritative execution without writing."
    )
    lookup = reconciler.add_mutually_exclusive_group(required=True)
    lookup.add_argument("--request-key", default=None, help="Original caller-owned key.")
    lookup.add_argument("--execution-id", default=None)
    reconciler.set_defaults(run=_run_reconcile)

    relay = commands.add_parser(
        "relay", parents=[common], help="Deliver committed outbox intents once."
    )
    relay.add_argument("--execution-id", default=None, help="Also report effect state.")
    relay.set_defaults(run=_run_relay)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command, print one JSON envelope and return its exit status."""
    parser = _parser()
    args = parser.parse_args(argv)
    run = cast(Callable[[argparse.Namespace], dict[str, object]], args.run)
    try:
        document = run(args)
    except (CliError, PermissionError, LookupError, FileNotFoundError) as error:
        failure = {"command": getattr(args, "command", None), "error": str(error)}
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(document, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
