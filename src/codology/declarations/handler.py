"""The single handler convention for behavioral declarations.

Every behavioral declaration exposes an instance method
``def handler(self, ctx, ...)``. ``@staticmethod def handle(...)`` is not part
of the API: one convention means there is no second name and no dual surface to
keep aligned. ``self`` carries no execution state; it exists because a
declaration is a class, and the engine reuses one metadata instance.
"""

from __future__ import annotations

import inspect

HANDLER_NAME = "handler"


class HandlerConventionError(TypeError):
    """A declaration class does not follow the handler convention."""


def handler_signature(cls: type[object]) -> inspect.Signature:
    """Return the signature of ``cls.handler`` after enforcing the convention.

    The declared signature must start with ``self, ctx``. Parameter types stay
    unresolved here; Link resolves them together with the rest of the
    declaration. A declaration's own ``handler`` must be a plain instance
    method, so a static method cannot silently introduce a second convention.
    """
    own = vars(cls)
    raw = own.get(HANDLER_NAME)
    if raw is None:
        message = (
            f"{cls.__qualname__} must define an instance method '{HANDLER_NAME}(self, ctx, ...)'."
        )
        if "handle" in own:
            message += " Found 'handle'; the only supported name is 'handler'."
        raise HandlerConventionError(message)
    if not inspect.isfunction(raw):
        raise HandlerConventionError(
            f"{cls.__qualname__}.{HANDLER_NAME} must be a plain instance method, "
            "not a classmethod, staticmethod, or assigned callable."
        )
    signature = inspect.signature(raw)
    parameters = tuple(signature.parameters.values())
    if len(parameters) < 2 or parameters[0].name != "self" or parameters[1].name != "ctx":
        raise HandlerConventionError(
            f"{cls.__qualname__}.{HANDLER_NAME} must start with 'self, ctx'; "
            f"found {tuple(parameter.name for parameter in parameters)}."
        )
    return signature
