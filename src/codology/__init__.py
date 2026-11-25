"""Codology's import root.

The package currently ships only the static declaration layer. Registry,
binding, engine, and adapter modules do not exist yet; importing ``codology``
must never require a database, credentials, or a backend SDK.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
