from __future__ import annotations

import pytest

from codology.declarations import HandlerConventionError, handler_signature


class _ValidAction:
    def handler(self, ctx: object, order: str) -> None:
        pass


class _MissingHandler:
    pass


class _LegacyHandleName:
    def handle(self, ctx: object) -> None:
        pass


class _StaticHandler:
    @staticmethod
    def handler(ctx: object) -> None:
        pass


class _MissingContext:
    def handler(self, order: str) -> None:
        pass


def test_instance_handler_with_self_and_ctx_is_accepted() -> None:
    signature = handler_signature(_ValidAction)

    assert list(signature.parameters) == ["self", "ctx", "order"]


def test_missing_handler_is_rejected() -> None:
    with pytest.raises(HandlerConventionError, match="must define an instance method"):
        handler_signature(_MissingHandler)


def test_legacy_handle_name_is_rejected_and_named() -> None:
    with pytest.raises(HandlerConventionError, match="Found 'handle'"):
        handler_signature(_LegacyHandleName)


def test_static_handler_is_rejected() -> None:
    with pytest.raises(HandlerConventionError, match="plain instance method"):
        handler_signature(_StaticHandler)


def test_handler_without_ctx_parameter_is_rejected() -> None:
    with pytest.raises(HandlerConventionError, match="self, ctx"):
        handler_signature(_MissingContext)
