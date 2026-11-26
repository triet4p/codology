"""SQLite adapter for the resume gate: one transaction, durable decision outcome.

The wrapper keeps the existing SQLite provider unchanged. It adds a dedicated
resume unit whose transaction owns guarded writes, the guarded ledger transition
and the decision outcome row, so a commit is all-or-nothing and an interrupted
attempt leaves no half-claim that would block a later resume.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import closing

from codology.adapter import (
    _COMPARE_SQL,  # pyright: ignore[reportPrivateUsage]
    _DECISION_COLUMNS,  # pyright: ignore[reportPrivateUsage]
    _LEDGER_SELECT,  # pyright: ignore[reportPrivateUsage]
    ResourceBinding,
    SQLiteDecisionUnit,
    SQLiteProvider,
    _encode,  # pyright: ignore[reportPrivateUsage]
    _identifier,  # pyright: ignore[reportPrivateUsage]
    _record_effect,  # pyright: ignore[reportPrivateUsage]
)
from codology.binding import SessionPlan
from codology.decision import DecisionRecord, ExecutionSnapshot, stored_decision
from codology.ledger import LedgerEntry, RequestScope
from codology.outbox import EffectEnvelope
from codology.ports import (
    ApplyResult,
    CommitOutcomeUnknown,
    GuardedWrite,
    StalePlan,
    TransactionUnavailable,
    UnitOfWork,
)
from codology.query import QueryPage, QueryRequest, QueryRow, ReadGrant, VersionedRef
from codology.resume import ResumeOutcome, stored_outcome

_RESUME_COLUMNS = ("callback_key", "execution_id", "outcome", "detail", "recorded_at")


def _apply_guarded(
    connection: sqlite3.Connection,
    resources: Mapping[str, ResourceBinding],
    write: GuardedWrite,
    transaction: str,
) -> ApplyResult:
    """Apply one guarded UPDATE; a mismatched version changes no row."""
    binding = resources.get(write.resource)
    if binding is None:
        raise TransactionUnavailable(f"no adapter mapping for resource {write.resource!r}.")
    allowed = set(binding.columns)
    for column in [item.column for item in write.changes] + [
        item.column for item in write.conditions
    ]:
        if column not in allowed:
            raise TransactionUnavailable(
                f"column {column!r} is not mapped for resource {binding.identity!r}."
            )
    assignments: list[str] = []
    parameters: list[object] = []
    for change in write.changes:
        if change.op == "add":
            assignments.append(f"{change.column} = {change.column} + ?")
        else:
            assignments.append(f"{change.column} = ?")
        parameters.append(_encode(change.value, binding))
    assignments.append(f"{binding.version_column} = {binding.version_column} + 1")
    predicates = [f"{binding.key_column} = ?", f"{binding.version_column} = ?"]
    parameters.extend([write.key, write.expected_version])
    for condition in write.conditions:
        predicates.append(f"{condition.column} {_COMPARE_SQL[condition.op]} ?")
        parameters.append(_encode(condition.value, binding))
    statement = (
        f"UPDATE {binding.table} SET {', '.join(assignments)} WHERE {' AND '.join(predicates)}"
    )
    try:
        cursor = connection.execute(statement, parameters)
    except sqlite3.OperationalError as exc:
        raise TransactionUnavailable(f"guarded write failed before commit: {exc}") from exc
    if cursor.rowcount != 1:
        raise StalePlan(
            write.resource,
            write.key,
            write.expected_version,
            cursor.rowcount,
            transaction,
        )
    return ApplyResult(write.resource, write.key, cursor.rowcount, transaction)


def _execution_snapshot(
    connection: sqlite3.Connection, ledger_table: str, execution_id: str
) -> ExecutionSnapshot | None:
    statement = (
        f"SELECT tenant, principal, action, request_key, {', '.join(_LEDGER_SELECT)} "
        f"FROM {ledger_table} WHERE execution_id = ? LIMIT 2"
    )
    try:
        found = connection.execute(statement, (execution_id,)).fetchall()
    except sqlite3.OperationalError as exc:
        raise TransactionUnavailable(f"execution lookup failed: {exc}") from exc
    if len(found) != 1:
        return None
    row = found[0]
    return ExecutionSnapshot(
        RequestScope(str(row[0]), str(row[1]), str(row[2])),
        str(row[3]),
        str(row[4]),
        str(row[5]),
        str(row[6]),
        str(row[7]),
        str(row[8]),
    )


def _decision_record(
    connection: sqlite3.Connection, decision_table: str, callback_key: str
) -> DecisionRecord | None:
    statement = (
        f"SELECT {', '.join(_DECISION_COLUMNS)} FROM {decision_table} WHERE callback_key = ?"
    )
    try:
        found = connection.execute(statement, (callback_key,)).fetchone()
    except sqlite3.OperationalError as exc:
        raise TransactionUnavailable(f"decision lookup failed: {exc}") from exc
    if found is None:
        return None
    return stored_decision(dict(zip(_DECISION_COLUMNS, found, strict=True)))


class ResumeSQLiteUnit:
    """One write transaction for resume guards, ledger, decision and outbox."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        resources: Mapping[str, ResourceBinding],
        ledger_table: str,
        decision_table: str,
        resume_table: str,
        outbox_table: str = "outbox",
        effect_dedup: str | None = None,
    ) -> None:
        self._connection = connection
        self._resources = resources
        self._ledger_table = ledger_table
        self._decision_table = decision_table
        self._resume_table = resume_table
        self._outbox_table = _identifier(outbox_table, "outbox_table")
        self._effect_dedup = effect_dedup

        self._transaction = f"resume#{id(connection):x}"
        self._transaction_ended = False
        self._connection_closed = False

    def _require_open(self) -> None:
        if self._transaction_ended or self._connection_closed:
            raise RuntimeError("the resume unit is closed.")

    def find_execution(self, execution_id: str) -> ExecutionSnapshot | None:
        self._require_open()
        return _execution_snapshot(self._connection, self._ledger_table, execution_id)

    def find_decision(self, callback_key: str) -> DecisionRecord | None:
        self._require_open()
        return _decision_record(self._connection, self._decision_table, callback_key)

    def find_outcome(self, callback_key: str) -> ResumeOutcome | None:
        self._require_open()
        statement = (
            f"SELECT {', '.join(_RESUME_COLUMNS)} FROM {self._resume_table} WHERE callback_key = ?"
        )
        try:
            found = self._connection.execute(statement, (callback_key,)).fetchone()
        except sqlite3.OperationalError as exc:
            raise TransactionUnavailable(f"resume outcome lookup failed: {exc}") from exc
        if found is None:
            return None
        return stored_outcome(dict(zip(_RESUME_COLUMNS, found, strict=True)))

    def apply(self, write: GuardedWrite) -> ApplyResult:
        self._require_open()
        return _apply_guarded(self._connection, self._resources, write, self._transaction)

    def record_effect(self, envelope: EffectEnvelope) -> bool:
        self._require_open()
        return _record_effect(self._connection, self._outbox_table, self._effect_dedup, envelope)

    def transition_committed(
        self, execution_id: str, fingerprint: str, action_version: str, payload: str
    ) -> bool:
        self._require_open()
        statement = (
            f"UPDATE {self._ledger_table} SET status = 'COMMITTED', "
            "intent_fingerprint = ?, action_version = ?, payload = ? "
            "WHERE execution_id = ? AND status = 'AWAITING_APPROVAL'"
        )
        try:
            cursor = self._connection.execute(
                statement, (fingerprint, action_version, payload, execution_id)
            )
        except sqlite3.OperationalError as exc:
            raise TransactionUnavailable(f"commit transition failed: {exc}") from exc
        return cursor.rowcount == 1

    def transition_reapproval(self, execution_id: str, fingerprint: str, payload: str) -> bool:
        self._require_open()
        statement = (
            f"UPDATE {self._ledger_table} SET intent_fingerprint = ?, payload = ? "
            "WHERE execution_id = ? AND status = 'AWAITING_APPROVAL'"
        )
        try:
            cursor = self._connection.execute(statement, (fingerprint, payload, execution_id))
        except sqlite3.OperationalError as exc:
            raise TransactionUnavailable(f"reapproval transition failed: {exc}") from exc
        return cursor.rowcount == 1

    def transition_rejected(self, execution_id: str) -> bool:
        self._require_open()
        statement = (
            f"UPDATE {self._ledger_table} SET status = 'REJECTED' "
            "WHERE execution_id = ? AND status = 'AWAITING_APPROVAL'"
        )
        try:
            cursor = self._connection.execute(statement, (execution_id,))
        except sqlite3.OperationalError as exc:
            raise TransactionUnavailable(f"reject transition failed: {exc}") from exc
        return cursor.rowcount == 1

    def record_outcome(self, record: ResumeOutcome) -> bool:
        self._require_open()
        statement = (
            f"INSERT OR IGNORE INTO {self._resume_table} "
            f"({', '.join(_RESUME_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _RESUME_COLUMNS)})"
        )
        try:
            cursor = self._connection.execute(
                statement,
                (
                    record.callback_key,
                    record.execution_id,
                    record.outcome,
                    record.detail,
                    record.recorded_at,
                ),
            )
        except sqlite3.OperationalError as exc:
            raise TransactionUnavailable(f"resume outcome claim failed: {exc}") from exc
        return cursor.rowcount == 1

    def commit(self) -> None:
        self._require_open()
        try:
            self._connection.commit()
        except sqlite3.OperationalError as exc:
            raise CommitOutcomeUnknown(f"the resume commit was not confirmed: {exc}") from exc
        self._transaction_ended = True

    def rollback(self) -> None:
        if self._transaction_ended or self._connection_closed:
            return
        try:
            if self._connection.in_transaction:
                self._connection.rollback()
        finally:
            self._transaction_ended = True

    def close(self) -> None:
        if self._connection_closed:
            return
        try:
            self._connection.close()
        finally:
            self._connection_closed = True
            self._transaction_ended = True


class ResumeSQLiteProvider:
    """Expose resume lookups and one write unit beside an existing SQLite provider."""

    def __init__(
        self, provider: SQLiteProvider, *, resume_table: str = "approval_resume_outcomes"
    ) -> None:
        self._provider = provider
        self.resume_table = _identifier(resume_table, "resume_table")
        self.database = provider.database
        self.timeout = provider.timeout
        self.resources: Mapping[str, ResourceBinding] = provider.resources

    def decision_unit(self) -> SQLiteDecisionUnit:
        return self._provider.decision_unit()

    def fetch(self, request: QueryRequest) -> QueryPage[object]:
        return self._provider.fetch(request)

    def resolve(self, ref: VersionedRef[object], grant: ReadGrant) -> QueryRow[object] | None:
        return self._provider.resolve(ref, grant)

    def begin(self, plan: SessionPlan) -> UnitOfWork:
        return self._provider.begin(plan)

    def lookup(self, scope: RequestScope, request_key: str) -> LedgerEntry | None:
        return self._provider.lookup(scope, request_key)

    def find_execution(self, execution_id: str) -> ExecutionSnapshot | None:
        with closing(
            sqlite3.connect(self.database, timeout=self.timeout, isolation_level=None)
        ) as connection:
            connection.execute("PRAGMA query_only = ON")
            return _execution_snapshot(connection, self._provider.ledger_table, execution_id)

    def read_decision(self, callback_key: str) -> DecisionRecord | None:
        with closing(
            sqlite3.connect(self.database, timeout=self.timeout, isolation_level=None)
        ) as connection:
            connection.execute("PRAGMA query_only = ON")
            return _decision_record(connection, self._provider.decision_table, callback_key)

    def resume_unit(self) -> ResumeSQLiteUnit:
        try:
            connection = sqlite3.connect(self.database, timeout=self.timeout, isolation_level=None)
        except sqlite3.OperationalError as exc:
            raise TransactionUnavailable(f"could not open the resume session: {exc}") from exc
        try:
            connection.execute(f"PRAGMA busy_timeout = {round(self.timeout * 1000)}")
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            connection.close()
            raise TransactionUnavailable(f"could not start the resume unit: {exc}") from exc
        except BaseException:
            connection.close()
            raise
        return self._new_unit(connection)

    def _new_unit(self, connection: sqlite3.Connection) -> ResumeSQLiteUnit:
        """Factory seam for deterministic fault injection around commit."""
        return ResumeSQLiteUnit(
            connection,
            self.resources,
            self._provider.ledger_table,
            self._provider.decision_table,
            self.resume_table,
            self._provider.outbox_table,
            self._provider.effect_dedup,
        )


__all__ = ["ResumeSQLiteProvider", "ResumeSQLiteUnit"]
