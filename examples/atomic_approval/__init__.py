"""Executable Procurement/Finance example over the real SQLite adapter.

The tier-2 declarations live in ``examples.procurement_finance.runtime``; the
static tier-3 example is never executed. ``wiring`` composes graph, deployment
and principals, ``consumer`` holds the query -> ref -> invoke path, and
``database`` creates the file-backed fixture.
"""
