"""SQLite adapter for the local relay and its durable receiver inbox.

The relay store reads only rows visible from an independent connection whose
execution is committed in the ledger. Effect state advances in its own SQLite
transaction; the business transaction is never reopened. The receiver writes a
notification and its dedup receipt in one transaction, so a lost acknowledgement
can only cause a replayed receipt.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from typing import cast

from codology.ledger import deserialize, serialize
from codology.relay import (
    DeliveryStatus,
    EffectState,
    EffectStatus,
    InvalidOutboxMessage,
    OutboxMessage,
    PermanentDelivery,
    Receipt,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DELIVERABLE = ("PENDING", "PENDING_RETRY")

RELAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS effect_delivery (
    dedup_id TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS notification_inbox (
    dedup_id TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_notifications (
    id TEXT PRIMARY KEY,
    dedup_id TEXT NOT NULL,
    document TEXT NOT NULL
);
"""


class RelayStoreUnavailable(Exception):
    """The relay could not read or advance durable effect state."""


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a plain SQL identifier; got {value!r}.")
    return value


def _connect(path: Path, timeout: float) -> sqlite3.Connection:
    try:
        return sqlite3.connect(path, timeout=timeout, isolation_level=None)
    except sqlite3.OperationalError as exc:
        raise RelayStoreUnavailable(f"could not open the relay session: {exc}") from exc


def _timeout(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{label} must be a number of seconds.")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be positive and finite.")
    return number


def _begin(connection: sqlite3.Connection, timeout: float) -> None:
    try:
        connection.execute(f"PRAGMA busy_timeout = {round(timeout * 1000)}")
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        connection.close()
        raise RelayStoreUnavailable(f"could not start the relay transaction: {exc}") from exc
    except BaseException:
        connection.close()
        raise


def create_relay_schema(database: str | Path, *, timeout: float = 10.0) -> None:
    """Install the host-owned relay and receiver tables in an existing SQLite file."""
    timeout = _timeout(timeout, "timeout")
    connection = _connect(Path(database), timeout)
    try:
        connection.executescript(RELAY_SCHEMA)
    except sqlite3.OperationalError as exc:
        raise RelayStoreUnavailable(f"could not install the relay schema: {exc}") from exc
    finally:
        connection.close()


def _document(row: object, label: str) -> Mapping[str, object]:
    if not isinstance(row, str):
        raise InvalidOutboxMessage(f"{label} is not a stored document.")
    document = deserialize(row)
    if document is None:
        raise InvalidOutboxMessage(f"{label} could not be decoded.")
    return document


def _field(document: Mapping[str, object], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidOutboxMessage(f"the outbox document has no usable {name}.")
    return value


def _attempt_counts(
    database: Path, table: str, timeout: float
) -> dict[str, tuple[int, str | None]]:
    found: dict[str, tuple[int, str | None]] = {}
    with closing(_connect(database, timeout)) as connection:
        connection.execute("PRAGMA query_only = ON")
        try:
            rows = connection.execute(f"SELECT dedup_id, attempts, detail FROM {table}").fetchall()
        except sqlite3.OperationalError as exc:
            raise RelayStoreUnavailable(f"effect state lookup failed: {exc}") from exc
    for row in rows:
        found[str(row[0])] = (int(row[1]), None if row[2] is None else str(row[2]))
    return found


class SQLiteRelayStore:
    """Read committed outbox rows and advance their effect state in SQLite."""

    def __init__(
        self,
        database: str | Path,
        *,
        outbox_table: str = "outbox",
        ledger_table: str = "request_ledger",
        delivery_table: str = "effect_delivery",
        timeout: float = 10.0,
    ) -> None:
        self.timeout = _timeout(timeout, "timeout")
        self.database = Path(database)
        self.outbox_table = _identifier(outbox_table, "outbox_table")
        self.ledger_table = _identifier(ledger_table, "ledger_table")
        self.delivery_table = _identifier(delivery_table, "delivery_table")

    def committed_messages(self, limit: int = 20) -> tuple[OutboxMessage, ...]:
        """Return deliverable rows only when their execution is committed."""
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer.")
        statement = (
            f"SELECT id, dedup_id, payload, status FROM {self.outbox_table} "
            "WHERE status IN (?, ?) ORDER BY id LIMIT ?"
        )
        attempts = _attempt_counts(self.database, self.delivery_table, self.timeout)
        committed = (
            f"SELECT 1 FROM {self.ledger_table} "
            "WHERE execution_id = ? AND status = 'COMMITTED' LIMIT 1"
        )
        messages: list[OutboxMessage] = []
        with closing(_connect(self.database, self.timeout)) as connection:
            connection.execute("PRAGMA query_only = ON")
            try:
                rows = connection.execute(statement, (*_DELIVERABLE, limit)).fetchall()
                for row in rows:
                    document = _document(row[2], "outbox payload")
                    execution_id = _field(document, "execution_id")
                    if connection.execute(committed, (execution_id,)).fetchone() is None:
                        continue
                    messages.append(
                        OutboxMessage(
                            str(row[0]),
                            str(row[1]),
                            document,
                            cast(EffectStatus, str(row[3])),
                            attempts.get(str(row[1]), (0, None))[0],
                        )
                    )
            except sqlite3.OperationalError as exc:
                raise RelayStoreUnavailable(f"outbox relay read failed: {exc}") from exc
        return tuple(messages)

    def record_attempt(
        self, message: OutboxMessage, status: DeliveryStatus, detail: str | None
    ) -> bool:
        """Advance one pending effect; a terminal or stale row refuses the write."""
        connection = _connect(self.database, self.timeout)
        try:
            _begin(connection, self.timeout)
            update = (
                f"UPDATE {self.outbox_table} SET status = ? "
                "WHERE id = ? AND dedup_id = ? AND status IN (?, ?)"
            )
            cursor = connection.execute(
                update, (status, message.id, message.dedup_id, *_DELIVERABLE)
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            advance = (
                f"INSERT INTO {self.delivery_table} (id, dedup_id, status, attempts, detail) "
                "VALUES (?, ?, ?, 1, ?) "
                "ON CONFLICT(dedup_id) DO UPDATE SET "
                "status = excluded.status, "
                "attempts = effect_delivery.attempts + 1, "
                "detail = excluded.detail "
                "WHERE effect_delivery.status IN (?, ?) "
                "AND effect_delivery.attempts = ?"
            )
            cursor = connection.execute(
                advance,
                (message.id, message.dedup_id, status, detail, *_DELIVERABLE, message.attempts),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            connection.commit()
            return True
        except sqlite3.OperationalError as exc:
            connection.rollback()
            raise RelayStoreUnavailable(f"effect state write failed: {exc}") from exc
        finally:
            connection.close()

    def effect_states(self, execution_id: str, tenant: str) -> tuple[EffectState, ...]:
        """Read scoped effect state; no execution status is read or changed here."""
        attempt_rows = _attempt_counts(self.database, self.delivery_table, self.timeout)
        statement = f"SELECT id, dedup_id, payload, status FROM {self.outbox_table} ORDER BY id"
        scope = (
            f"SELECT 1 FROM {self.ledger_table} "
            "WHERE execution_id = ? AND tenant = ? AND status = 'COMMITTED' LIMIT 1"
        )
        states: list[EffectState] = []
        with closing(_connect(self.database, self.timeout)) as connection:
            connection.execute("PRAGMA query_only = ON")
            try:
                if connection.execute(scope, (execution_id, tenant)).fetchone() is None:
                    return ()
                for row in connection.execute(statement).fetchall():
                    document = _document(row[2], "outbox payload")
                    if document.get("execution_id") != execution_id:
                        continue
                    dedup_id = _field(document, "dedup_id")
                    row_id = _field(document, "id")
                    attempts, detail = attempt_rows.get(dedup_id, (0, None))
                    states.append(
                        EffectState(
                            row_id,
                            dedup_id,
                            cast(EffectStatus, str(row[3])),
                            attempts,
                            detail,
                        )
                    )
            except sqlite3.OperationalError as exc:
                raise RelayStoreUnavailable(f"effect state read failed: {exc}") from exc
        return tuple(states)


class SQLiteLocalReceiver:
    """A local sink that writes one notification per dedup ID and keeps a receipt."""

    def __init__(
        self,
        database: str | Path,
        *,
        notifications_table: str = "local_notifications",
        inbox_table: str = "notification_inbox",
        before_write: Callable[[OutboxMessage], Exception | None] | None = None,
        after_write: Callable[[OutboxMessage], Exception | None] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.timeout = _timeout(timeout, "timeout")
        self.database = Path(database)
        self.notifications_table = _identifier(notifications_table, "notifications_table")
        self.inbox_table = _identifier(inbox_table, "inbox_table")
        self.before_write = before_write
        self.after_write = after_write

    def receive(self, message: OutboxMessage) -> Receipt:
        """Write once under the dedup ID; a retry returns the durable receipt."""
        connection = _connect(self.database, self.timeout)
        try:
            _begin(connection, self.timeout)
            found = connection.execute(
                f"SELECT document FROM {self.inbox_table} WHERE dedup_id = ?",
                (message.dedup_id,),
            ).fetchone()
            if found is not None:
                stored = _document(found[0], "inbox document")
                connection.rollback()
                if serialize(stored) != serialize(message.document):
                    raise PermanentDelivery("the dedup ID already carries another notification.")
                return Receipt(message.dedup_id, f"notice:{message.dedup_id}", True)
            if self.before_write is not None:
                failure = self.before_write(message)
                if failure is not None:
                    connection.rollback()
                    raise failure
            document = serialize(message.document)
            notification = f"notice:{message.dedup_id}"
            connection.execute(
                f"INSERT INTO {self.notifications_table} (id, dedup_id, document) VALUES (?, ?, ?)",
                (notification, message.dedup_id, document),
            )
            connection.execute(
                f"INSERT INTO {self.inbox_table} (dedup_id, id, document) VALUES (?, ?, ?)",
                (message.dedup_id, notification, document),
            )
            connection.commit()
            if self.after_write is not None:
                failure = self.after_write(message)
                if failure is not None:
                    raise failure
            return Receipt(message.dedup_id, notification, False)
        except sqlite3.OperationalError as exc:
            connection.rollback()
            raise RelayStoreUnavailable(f"local receiver failed: {exc}") from exc
        finally:
            connection.close()


__all__ = [
    "RELAY_SCHEMA",
    "RelayStoreUnavailable",
    "SQLiteLocalReceiver",
    "SQLiteRelayStore",
    "create_relay_schema",
]
