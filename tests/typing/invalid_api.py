# pyright: reportUnnecessaryTypeIgnoreComment=error
"""Negative typing checks for the same surface.

Each deliberate misuse carries a rule-specific ignore. The file header turns an
*unnecessary* ignore into an error, so the fixture fails if Pyright stops
catching the mistake; ``uv run pyright`` is the verification.
"""

from typing import assert_type

from codology import DefinitionKey, SnapshotEntry, link, load, snapshot
from examples.procurement_finance.model import FINANCE_GROUP, PROCUREMENT_GROUP

loaded = load(PROCUREMENT_GROUP, FINANCE_GROUP)
linked = link(loaded)
published = snapshot(linked)

# Load output must pass through Link before it can be published.
snapshot(loaded)  # pyright: ignore[reportArgumentType]

# Lookup is version-explicit; identity alone is not a key.
published.lookup("finance.budget")  # pyright: ignore[reportCallIssue]

# Linked declarations are not the published snapshot.
linked.lookup("finance.budget", "1.0.0")  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

# A definition key needs identity and version.
DefinitionKey("finance.budget")  # pyright: ignore[reportCallIssue]

# The linked layer holds LinkedDefinition, not SnapshotEntry.
assert_type(linked.definitions["finance.budget"], SnapshotEntry)  # pyright: ignore[reportAssertTypeFailure]

# Load accepts ModuleDeclarations groups, not bare names.
load("finance")  # pyright: ignore[reportArgumentType]
