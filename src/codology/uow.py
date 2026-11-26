"""Engine-owned commit boundary for bound, guarded writes."""

from __future__ import annotations

from collections.abc import Sequence

from codology.binding import SessionPlan
from codology.ports import ApplyResult, GuardedWrite, TransactionProvider


class UnboundWriteAttempt(ValueError):
    """A write was submitted that the bound session plan does not contain."""


def commit_guarded_writes(
    provider: TransactionProvider,
    plan: SessionPlan,
    writes: Sequence[GuardedWrite],
) -> tuple[ApplyResult, ...]:
    """Apply every write in one transaction, then commit exactly once.

    The caller receives only results; neither commit nor rollback is exposed to
    a handler. Any failure before commit rolls the whole unit back.
    """
    pending = tuple(writes)
    if not pending:
        raise ValueError("at least one guarded write is required.")
    bound = {resource.identity for resource in plan.writes}
    for write in pending:
        if write.resource not in bound:
            raise UnboundWriteAttempt(
                f"write to {write.resource!r} is not in the bound write set "
                f"{sorted(bound)!r}."
            )

    unit = provider.begin(plan)
    try:
        results = tuple(unit.apply(write) for write in pending)
        unit.commit()
        return results
    except BaseException:
        unit.rollback()
        raise
    finally:
        unit.close()
