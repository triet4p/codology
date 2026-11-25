"""Run the Procurement/Finance example: Load, Link, Snapshot, and failures.

Run from the repository root:

    uv run python -m examples.procurement_finance

The example touches no provider, database, credential, engine, or adapter.
"""

from __future__ import annotations

from codology import ComparisonExpr
from codology.linking import LinkError
from codology.loading import LoadError
from examples.procurement_finance.model import build_snapshot, link_model, load_model
from examples.procurement_finance.scenarios import SCENARIOS

APPROVE = "procurement.approve_purchase_order"
APPROVE_VERSION = "2.0.0"


def describe(error: BaseException) -> str:
    """Render a static error with the context Link/Load attached to it."""
    if isinstance(error, LoadError | LinkError):
        return (
            f"{type(error).__name__} "
            f"[module={error.module!r}, identity={error.identity!r}, field={error.field!r}]: "
            f"{error}"
        )
    return f"{type(error).__name__}: {error}"


def main() -> int:
    """Print the success path and every expected failure scenario."""
    loaded = load_model()
    print("== Load ==")
    for identity in sorted(loaded.definitions):
        item = loaded.definitions[identity]
        print(f"  {identity}@{item.version} owner={item.owner}")

    linked = link_model()
    print("== Link ==")
    approve = linked.definitions[APPROVE]
    for reference in approve.references:
        target = (
            reference.target.identity
            if reference.target.identity is not None
            else reference.target.declaration.__qualname__
        )
        print(f"  {reference.field} -> {target}")

    published = build_snapshot()
    entry = published.lookup(APPROVE, APPROVE_VERSION)
    print("== Snapshot ==")
    print(f"  {entry.identity}@{entry.version} kind={entry.kind}")
    print(f"  permission={entry.permission}")
    print(f"  commitRequirement={entry.commit_requirement} (declared metadata only)")
    if entry.approval is not None:
        when = entry.approval.when
        if isinstance(when, ComparisonExpr):
            print(
                f"  approval role={entry.approval.role!r} "
                f"operator={when.operator!r} self_approval={entry.approval.self_approval}"
            )
        else:
            print(f"  approval role={entry.approval.role!r} when={type(when).__name__}")
    print(f"  versions(finance.budget)={published.versions_of('finance.budget')}")

    print("== Expected failures ==")
    for label, scenario in SCENARIOS:
        print(f"  {label}: {describe(scenario())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
