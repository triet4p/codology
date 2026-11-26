"""Engine-owned commit boundary for bound, guarded writes and one ledger entry."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from codology.binding import SessionPlan
from codology.ledger import DuplicateRequest, LedgerEntry, LedgerUnitOfWork
from codology.ports import ApplyResult, GuardedWrite, TransactionProvider, UnitOfWork


class UnboundWriteAttempt(ValueError):
    """A write was submitted that the bound session plan does not contain."""


def commit_guarded_writes(
    provider: TransactionProvider,
    plan: SessionPlan,
    writes: Sequence[GuardedWrite],
    *,
    entry: LedgerEntry | None = None,
    unit: UnitOfWork | None = None,
) -> tuple[ApplyResult, ...]:
    """Apply every write and the optional ledger entry, then commit exactly once.

    The caller receives only results; neither commit nor rollback is exposed to
    a handler. Any failure before commit rolls the whole unit back. A caller may
    hand over an already opened unit so the ledger can be claimed before a
    handler runs.
    """
    pending = tuple(writes)
    if not pending:
        raise ValueError("at least one guarded write is required.")
    bound = {resource.identity for resource in plan.writes}
    for write in pending:
        if write.resource not in bound:
            raise UnboundWriteAttempt(
                f"write to {write.resource!r} is not in the bound write set {sorted(bound)!r}."
            )

    active = provider.begin(plan) if unit is None else unit
    try:
        ledger = cast(LedgerUnitOfWork, active)
        if entry is not None and ledger.lookup(entry.scope, entry.request_key) is not None:
            raise DuplicateRequest(f"request key {entry.request_key!r} is already committed.")
        results = tuple(active.apply(write) for write in pending)
        if entry is not None:
            ledger.record(entry)
        active.commit()
        return results
    except BaseException:
        active.rollback()
        raise
    finally:
        active.close()
