"""Engine-owned commit boundary for bound, guarded writes and one ledger entry."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from codology.binding import BoundAction, SessionPlan
from codology.ledger import DuplicateRequest, LedgerEntry, LedgerUnitOfWork
from codology.outbox import (
    EffectEnvelope,
    EffectNotBound,
    OutboxUnitOfWork,
    require_envelopes_bound,
)
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
    effects: Sequence[EffectEnvelope] = (),
    bound: BoundAction | None = None,
) -> tuple[ApplyResult, ...]:
    """Apply every write, ledger entry and outbox intent, then commit exactly once.

    The caller receives only results; neither commit nor rollback is exposed to
    a handler. Any failure before commit rolls the whole unit back. A caller may
    hand over an already opened unit so the ledger can be claimed before a
    handler runs. Outbox intents use that same unit, never a separate session.
    """
    intents = tuple(effects)
    if intents:
        if bound is None:
            raise EffectNotBound("outbox intents need the bound action plan.")
        require_envelopes_bound(bound, intents)

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
    if intents and not hasattr(active, "record_effect"):
        try:
            active.rollback()
        finally:
            active.close()
        raise EffectNotBound("the bound transaction cannot record outbox intents.")
    try:
        ledger = cast(LedgerUnitOfWork, active)
        if entry is not None and ledger.lookup(entry.scope, entry.request_key) is not None:
            raise DuplicateRequest(f"request key {entry.request_key!r} is already committed.")
        results = tuple(active.apply(write) for write in pending)
        if entry is not None:
            ledger.record(entry)
        for intent in intents:
            cast(OutboxUnitOfWork, active).record_effect(intent)
        active.commit()
        return results
    except BaseException as exc:
        try:
            active.rollback()
        except BaseException as rollback_error:
            exc.add_note(f"rollback after a failed unit also failed: {rollback_error!r}")
        raise
    finally:
        active.close()
