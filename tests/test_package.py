from __future__ import annotations

import sys

import codology
import codology.declarations


def test_package_imports_and_reports_a_version() -> None:
    assert codology.__version__ == "0.1.0"


def test_declarations_import_does_not_pull_runtime_layers() -> None:
    assert "codology.registry" not in sys.modules
    assert "codology.engine" not in sys.modules
    assert "codology.adapters" not in sys.modules


def test_declarations_expose_the_handler_convention_name() -> None:
    assert codology.declarations.HANDLER_NAME == "handler"
