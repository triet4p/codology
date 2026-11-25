"""Immutable class-based structural declarations.

A declaration is pure metadata: it is created from a class body, carries an
explicit identity and version, and is frozen before the author can mutate it.
Nothing here imports a registry, engine, binding, or adapter, and creating a
declaration needs no provider, database, or credential.

Annotations are captured as written (see ``annotations.raw_annotations``), so a
property may name a declaration from a module that has not been imported yet.
Resolving those names is a link-time concern, not a declaration-time one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final, Literal, cast

from codology.declarations.annotations import raw_annotations

Cardinality = Literal["one", "many"]
Traversal = Literal["navigable", "internal"]
_CARDINALITIES: Final = frozenset({"one", "many"})
_TRAVERSALS: Final = frozenset({"navigable", "internal"})

DECLARATION_FIELDS: Final = frozenset(
    {
        "identity",
        "version",
        "properties",
        "exports",
        "keyType",
        "links",
        "params",
        "reads",
        "writes",
        "calls",
        "permission",
        "commitRequirement",
        "approval",
        "effects",
        "result",
        "payload",
        "dedupKey",
    }
)


class DeclarationError(ValueError):
    """A declaration was built with missing or invalid metadata."""


class DeclarationMeta(type):
    """Freeze a declaration class once its class body has been processed."""

    def __new__(
        mcls,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, object],
        **kwargs: object,
    ) -> DeclarationMeta:
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        type.__setattr__(cls, "_frozen", True)
        return cls

    def __setattr__(cls, name: str, value: object) -> None:
        if cls.__dict__.get("_frozen", False):
            raise AttributeError(
                f"{cls.__qualname__} is an immutable declaration; cannot set {name!r}."
            )
        super().__setattr__(name, value)

    def __delattr__(cls, name: str) -> None:
        if cls.__dict__.get("_frozen", False):
            raise AttributeError(
                f"{cls.__qualname__} is an immutable declaration; cannot delete {name!r}."
            )
        super().__delattr__(name)


class Declaration(metaclass=DeclarationMeta):
    """Common metadata for every class-based declaration."""

    identity: str | None = None
    version: str | None = None
    properties: Mapping[str, object] = MappingProxyType({})

    @classmethod
    def _freeze(cls, *, require_identity: bool) -> None:
        own = cls.__dict__
        identity = own.get("identity")
        version = own.get("version")
        if require_identity or identity is not None or version is not None:
            _require_text(cls, "identity", identity)
            _require_text(cls, "version", version)

        properties = {
            name: annotation
            for name, annotation in raw_annotations(cls).items()
            if name not in DECLARATION_FIELDS
        }
        for name, value in own.items():
            if isinstance(value, type) and issubclass(value, Link):
                properties.pop(name, None)

        type.__setattr__(cls, "properties", MappingProxyType(properties))
        type.__setattr__(cls, "_frozen", True)


def _require_text(cls: type[Declaration], field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeclarationError(
            f"{cls.__qualname__}.{field} must be a non-empty string declared explicitly; "
            "it is never derived from the host class name."
        )
    return value


class Module(Declaration):
    """Ownership boundary; only identities in ``exports`` are visible outside."""

    exports: tuple[type[Declaration], ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        raw_exports: object = getattr(cls, "exports", ())
        if isinstance(raw_exports, (str, bytes)) or not isinstance(raw_exports, Sequence):
            raise DeclarationError(
                f"{cls.__qualname__}.exports must be a sequence of declarations."
            )
        exports = tuple(cast(Sequence[object], raw_exports))
        for entry in exports:
            if not isinstance(entry, type) or not issubclass(entry, Declaration):
                raise DeclarationError(
                    f"{cls.__qualname__}.exports may only contain declaration classes; "
                    f"found {entry!r}."
                )
            if not isinstance(getattr(entry, "identity", None), str):
                raise DeclarationError(
                    f"{cls.__qualname__}.exports cannot contain {entry.__qualname__}: "
                    "an exported declaration needs an explicit identity."
                )
        type.__setattr__(cls, "exports", exports)
        cls._freeze(require_identity=True)

    @classmethod
    def is_exported(cls, declaration: type[Declaration]) -> bool:
        """Report whether ``declaration``'s identity is in this module's exports."""
        identity = getattr(declaration, "identity", None)
        if not isinstance(identity, str):
            return False
        return any(
            isinstance(entry.identity, str) and entry.identity == identity for entry in cls.exports
        )


class ObjectType(Declaration):
    """An entity with a stable definition identity and canonical key type."""

    links: Mapping[str, type[Link]] = MappingProxyType({})

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        key_type = getattr(cls, "keyType", None)
        if key_type is not None and (not isinstance(key_type, str) or not key_type.strip()):
            raise DeclarationError(
                f"{cls.__qualname__}.keyType must be a non-empty string or None."
            )

        raw_links: object = getattr(cls, "links", {})
        if not isinstance(raw_links, Mapping):
            raise DeclarationError(f"{cls.__qualname__}.links must be a mapping of link specs.")
        links: dict[str, type[Link]] = {}
        for name, value in cast(Mapping[object, object], raw_links).items():
            if not isinstance(name, str) or not _is_link_spec(value):
                raise DeclarationError(
                    f"{cls.__qualname__}.links may only contain named link specs."
                )
            links[name] = cast(type[Link], value)
        for name, value in cls.__dict__.items():
            if _is_link_spec(value):
                links[name] = cast(type[Link], value)

        type.__setattr__(cls, "keyType", key_type)
        type.__setattr__(cls, "links", MappingProxyType(links))
        cls._freeze(require_identity=True)


class Value(Declaration):
    """A structural concept with no lifecycle of its own.

    Identity and version are optional here: a value is used through its typed
    properties. When present, they are still explicit and never inferred from
    the host class name.
    """

    identity: str | None = None
    version: str | None = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._freeze(require_identity=False)


def _validate_target(target: object) -> None:
    if isinstance(target, str):
        if not target.strip():
            raise DeclarationError("A link or object reference target cannot be blank.")
        return
    if isinstance(target, type) and issubclass(target, ObjectType):
        return
    raise DeclarationError(
        "A link or object reference target must be an ObjectType class "
        "or a forward-reference string."
    )


class Link(metaclass=DeclarationMeta):
    """Immutable relationship spec: target, cardinality, and traversal."""

    target: object
    cardinality: str
    traversal: str

    def __new__(cls, *args: object, **kwargs: object) -> Link:
        raise DeclarationError("Declare a link with Link[target, cardinality, traversal].")

    def __class_getitem__(cls, item: object) -> type[Link]:
        if not isinstance(item, tuple):
            raise DeclarationError("Link[...] expects exactly (target, cardinality, traversal).")
        params = cast(tuple[object, object, object], item)
        if len(params) != 3:
            raise DeclarationError("Link[...] expects exactly (target, cardinality, traversal).")
        target, cardinality, traversal = params
        _validate_target(target)
        if cardinality not in _CARDINALITIES:
            raise DeclarationError(
                f"Link cardinality must be 'one' or 'many'; found {cardinality!r}."
            )
        if traversal not in _TRAVERSALS:
            raise DeclarationError(
                f"Link traversal must be 'navigable' or 'internal'; found {traversal!r}."
            )
        return cast(
            type[Link],
            DeclarationMeta(
                cls.__name__,
                (cls,),
                {"target": target, "cardinality": cardinality, "traversal": traversal},
            ),
        )


class ObjectRef(metaclass=DeclarationMeta):
    """Immutable typed reference to an object definition or a forward name."""

    target: object

    def __new__(cls, *args: object, **kwargs: object) -> ObjectRef:
        raise DeclarationError("Declare an object reference with ObjectRef[Target].")

    def __class_getitem__(cls, item: object) -> type[ObjectRef]:
        _validate_target(item)
        return cast(
            type[ObjectRef],
            DeclarationMeta(cls.__name__, (cls,), {"target": item}),
        )


def _is_link_spec(value: object) -> bool:
    return isinstance(value, type) and issubclass(value, Link)
