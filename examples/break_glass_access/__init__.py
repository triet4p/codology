"""Simulated infrastructure-access domain, static composition and SQLite host.

The domain is deliberately different from order approval: the compared quantity
is a duration in integer minutes, the authority is a security officer, and the
effect only shapes a local notification. ``model`` composes the declarations;
``database`` and ``wiring`` own the SQLite fixture and deployment plan, and
``consumer`` drives the public engine ports.
"""

from examples.break_glass_access.model import (
    ACCESS_GROUP,
    AUDIT_GROUP,
    GRANT_ACCESS_KEY,
    RECORD_SESSION_KEY,
    build_snapshot,
    link_model,
    load_model,
)

__all__ = [
    "ACCESS_GROUP",
    "AUDIT_GROUP",
    "GRANT_ACCESS_KEY",
    "RECORD_SESSION_KEY",
    "build_snapshot",
    "link_model",
    "load_model",
]
