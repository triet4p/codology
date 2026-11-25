"""Lazy annotation capture and link-time resolution.

A declaration class is created while a single Python module is being imported.
Its annotations may name declarations owned by another module, so evaluating
them at class-creation time would force an import that can form a cycle. The
class body is therefore captured as written and resolved later against a
namespace composed from every module taking part in the link.
"""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable, Mapping
from typing import Any, get_type_hints


def raw_annotations(target: type[object] | Callable[..., Any]) -> dict[str, Any]:
    """Return annotations exactly as written, leaving strings unevaluated."""
    return dict(inspect.get_annotations(target, eval_str=False))


def resolve_annotations(
    target: type[object] | Callable[..., Any],
    namespace: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve annotations of ``target`` against a composed link namespace.

    ``namespace`` maps declaration names from every module in the link to their
    classes, so a forward reference can resolve to a class that the defining
    module never imported. Names from the target's own module remain available
    as a fallback; ``namespace`` wins on collisions.
    """
    merged = {**_module_namespace(target), **namespace}
    return get_type_hints(target, globalns=merged, localns=merged, include_extras=True)


def _module_namespace(target: type[object] | Callable[..., Any]) -> dict[str, Any]:
    module_name: object = getattr(target, "__module__", None)
    if not isinstance(module_name, str):
        return {}
    module = sys.modules.get(module_name)
    if module is None:
        return {}
    return dict(vars(module))
