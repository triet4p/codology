"""Immutable behavioral and governance declarations.

An action or function is still pure metadata: its identity, typed parameters,
access scope, and optional governance rules are captured as frozen class
attributes. Nothing here calls a handler, evaluates a predicate against data,
or delivers an effect; load, link, and execution belong to later layers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, NoReturn, cast

from codology.declarations.primitives import Declaration, DeclarationError, ObjectType, Value

_COMPARISON_OPERATORS: Final = frozenset({">", ">=", "<", "<=", "==", "!="})


class UnsupportedApprovalExpression(DeclarationError):
    """An approval condition used an expression the static layer cannot represent."""


def _reject_expression(kind: str, detail: str) -> NoReturn:
    raise UnsupportedApprovalExpression(
        f"{kind} is not supported in approval predicates: {detail}. "
        "Use structured comparisons (> >= < <= == !=) and and_/or_/not_."
    )


def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UnsupportedApprovalExpression(f"{label} must be a non-empty name.")
    return value


def _require_path(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise UnsupportedApprovalExpression(
            "A predicate field path must be a tuple of non-empty field names."
        )
    parts = cast(tuple[object, ...], value)
    if any(not isinstance(part, str) or not part for part in parts):
        raise UnsupportedApprovalExpression(
            "A predicate field path must be a tuple of non-empty field names."
        )
    return cast(tuple[str, ...], parts)


def _require_operator(value: object) -> str:
    if value not in _COMPARISON_OPERATORS:
        raise UnsupportedApprovalExpression(
            f"Unsupported approval comparison operator {value!r}; expected one of > >= < <= == !=."
        )
    return cast(str, value)


def _require_operand(value: object) -> FieldRef | Literal:
    if not isinstance(value, FieldRef | Literal):
        _reject_expression(
            "An unstructured comparison operand", "use a literal or a typed field path"
        )
    return value


def _require_predicate_parts(value: object, label: str) -> tuple[Predicate, ...]:
    if not isinstance(value, tuple):
        raise UnsupportedApprovalExpression(f"{label} requires at least two predicates.")
    parts = cast(tuple[object, ...], value)
    if len(parts) < 2:
        raise UnsupportedApprovalExpression(f"{label} requires at least two predicates.")
    return tuple(_as_predicate(part) for part in parts)


def _require_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise DeclarationError(f"{label} must be an explicit bool; there is no implicit default.")
    return value


def _require_result(value: object, label: str) -> type | str:
    if isinstance(value, str):
        if not value.strip():
            raise DeclarationError(f"{label} cannot be a blank name.")
        return value
    if not isinstance(value, type):
        raise DeclarationError(f"{label} must be a type or a forward-reference string.")
    return value


def _require_payload(value: object, label: str) -> type[Value] | str:
    if isinstance(value, str):
        if not value.strip():
            raise DeclarationError(f"{label} cannot be a blank name.")
        return value
    if not isinstance(value, type) or not issubclass(value, Value):
        raise DeclarationError(f"{label} must be a Value class or a forward-reference string.")
    return value


def _require_commit(value: object, label: str) -> CommitRequirement | None:
    if value is not None and not isinstance(value, CommitRequirement):
        raise DeclarationError(f"{label} must be a CommitRequirement member.")
    return value


def _require_approval(value: object, label: str) -> Approval | None:
    if value is not None and not isinstance(value, Approval):
        raise DeclarationError(f"{label} must be an Approval.")
    return value


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(dict(cast(Mapping[object, object], value)))
    if isinstance(value, str | bytes):
        return value
    if isinstance(value, Sequence):
        return tuple(cast(Sequence[object], value))
    if isinstance(value, set | frozenset):
        return frozenset(cast(set[object] | frozenset[object], value))
    return value


@dataclass(frozen=True, slots=True, eq=False)
class FieldRef:
    """A typed path from an action parameter into a structured predicate."""

    parameter: str
    path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "parameter", _require_identifier(self.parameter, "A predicate parameter")
        )
        object.__setattr__(self, "path", _require_path(self.path))

    def __getattr__(self, name: str) -> FieldRef:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        if not name.isidentifier():
            _reject_expression(f"Field name {name!r}", "field paths must be identifiers")
        return FieldRef(self.parameter, (*self.path, name))

    def __call__(self, *args: object, **kwargs: object) -> NoReturn:
        _reject_expression("Method calls", "use a typed field path, not a method call")

    def __getitem__(self, key: object) -> NoReturn:
        _reject_expression("Subscripting", "use attribute paths to reach a typed field")

    def __contains__(self, item: object) -> NoReturn:
        _reject_expression("Membership tests", "use a structured comparison")

    def __neg__(self) -> NoReturn:
        _reject_expression("Unary '-'", "compare a field path with a literal")

    def __pos__(self) -> NoReturn:
        _reject_expression("Unary '+'", "compare a field path with a literal")

    def __add__(self, other: object) -> NoReturn:
        _reject_expression("Arithmetic '+'", "compare a field path with a literal")

    def __radd__(self, other: object) -> NoReturn:
        _reject_expression("Arithmetic '+'", "compare a field path with a literal")

    def __sub__(self, other: object) -> NoReturn:
        _reject_expression("Arithmetic '-'", "compare a field path with a literal")

    def __rsub__(self, other: object) -> NoReturn:
        _reject_expression("Arithmetic '-'", "compare a field path with a literal")

    def __mul__(self, other: object) -> NoReturn:
        _reject_expression("Arithmetic '*'", "compare a field path with a literal")

    def __rmul__(self, other: object) -> NoReturn:
        _reject_expression("Arithmetic '*'", "compare a field path with a literal")

    def __truediv__(self, other: object) -> NoReturn:
        _reject_expression("Arithmetic '/'", "compare a field path with a literal")

    def __rtruediv__(self, other: object) -> NoReturn:
        _reject_expression("Arithmetic '/'", "compare a field path with a literal")

    def _compare(self, operator: str, other: object) -> Comparison:
        return Comparison(operator, self, _operand(other))

    def __gt__(self, other: object) -> Comparison:
        return self._compare(">", other)

    def __ge__(self, other: object) -> Comparison:
        return self._compare(">=", other)

    def __lt__(self, other: object) -> Comparison:
        return self._compare("<", other)

    def __le__(self, other: object) -> Comparison:
        return self._compare("<=", other)

    def __eq__(self, other: object) -> Comparison:  # pyright: ignore[reportIncompatibleMethodOverride]
        return self._compare("==", other)

    def __ne__(self, other: object) -> Comparison:  # pyright: ignore[reportIncompatibleMethodOverride]
        return self._compare("!=", other)

    def __bool__(self) -> NoReturn:
        _reject_expression("Truthiness of a field path", "build a comparison first")


class Param(FieldRef):
    """Root of an approval field path, e.g. ``Param("order").amount``."""

    __slots__ = ()

    def __init__(self, name: str) -> None:
        super().__init__(name, ())


@dataclass(frozen=True, slots=True)
class Literal:
    """A comparison operand captured by value, never as a live callable."""

    value: object

    def __post_init__(self) -> None:
        if callable(self.value):
            _reject_expression(
                "A callable literal", "lambdas and functions cannot be stored in a manifest"
            )
        object.__setattr__(self, "value", _freeze_value(self.value))


class _PredicateBase:
    __slots__ = ()

    def and_(self, other: object) -> AllOf:
        return AllOf((_as_predicate(self), _as_predicate(other)))

    def or_(self, other: object) -> AnyOf:
        return AnyOf((_as_predicate(self), _as_predicate(other)))

    def not_(self) -> Negate:
        return Negate(_as_predicate(self))

    def __and__(self, other: object) -> AllOf:
        return self.and_(other)

    def __or__(self, other: object) -> AnyOf:
        return self.or_(other)

    def __invert__(self) -> Negate:
        return self.not_()

    def __eq__(self, other: object) -> bool:
        return _shape(self) == _shape(other)


@dataclass(frozen=True, slots=True, eq=False)
class Comparison(_PredicateBase):
    """A typed field path compared with a literal or another field path."""

    operator: str
    left: FieldRef
    right: FieldRef | Literal

    def __post_init__(self) -> None:
        object.__setattr__(self, "operator", _require_operator(self.operator))
        object.__setattr__(self, "left", _require_operand(self.left))
        object.__setattr__(self, "right", _require_operand(self.right))


@dataclass(frozen=True, slots=True, eq=False)
class AllOf(_PredicateBase):
    parts: tuple[Predicate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parts", _require_predicate_parts(self.parts, "all_of"))


@dataclass(frozen=True, slots=True, eq=False)
class AnyOf(_PredicateBase):
    parts: tuple[Predicate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parts", _require_predicate_parts(self.parts, "any_of"))


@dataclass(frozen=True, slots=True, eq=False)
class Negate(_PredicateBase):
    operand: Predicate

    def __post_init__(self) -> None:
        _as_predicate(self.operand)


type Predicate = Comparison | AllOf | AnyOf | Negate


def _shape(node: object) -> object:
    """Structural view used for equality without invoking overloaded operators."""
    if isinstance(node, FieldRef):
        return ("field", node.parameter, node.path)
    if isinstance(node, Literal):
        return ("literal", node.value)
    if isinstance(node, Comparison):
        return ("comparison", node.operator, _shape(node.left), _shape(node.right))
    if isinstance(node, AllOf):
        return ("all", tuple(_shape(part) for part in node.parts))
    if isinstance(node, AnyOf):
        return ("any", tuple(_shape(part) for part in node.parts))
    if isinstance(node, Negate):
        return ("not", _shape(node.operand))
    return ("unsupported", type(node).__name__)


def _as_predicate(value: object) -> Predicate:
    if isinstance(value, (Comparison, AllOf, AnyOf, Negate)):
        return value
    if callable(value):
        name: object = getattr(value, "__name__", type(value).__name__)
        _reject_expression(
            f"A callable ({name})", "lambdas and functions cannot be represented in a manifest"
        )
    _reject_expression(
        f"An expression of type {type(value).__name__}",
        "only structured comparisons and boolean combinators are allowed",
    )


def _operand(value: object) -> FieldRef | Literal:
    if isinstance(value, FieldRef):
        return value
    if isinstance(value, _PredicateBase):
        _reject_expression("A predicate operand", "compose predicates with and_/or_/not_")
    return Literal(value)


def validate_predicate(value: object) -> Predicate:
    """Validate a predicate at the declaration boundary; load/link may reuse it."""
    return _as_predicate(value)


def all_of(*parts: object) -> AllOf:
    return AllOf(tuple(_as_predicate(part) for part in parts))


def any_of(*parts: object) -> AnyOf:
    return AnyOf(tuple(_as_predicate(part) for part in parts))


def not_(operand: object) -> Negate:
    return Negate(_as_predicate(operand))


@dataclass(frozen=True, slots=True)
class Approval:
    """Structured wait-for-approval rule; evaluated only by a future engine."""

    when: Predicate
    role: str
    self_approval: bool

    @classmethod
    def conditional(cls, *, when: object, role: str, self_approval: bool) -> Approval:
        predicate = validate_predicate(when)
        checked_role = _require_identifier(role, "Approval.role")
        checked_self_approval = _require_bool(self_approval, "Approval.self_approval")
        return cls(predicate, checked_role, checked_self_approval)


class CommitRequirement(StrEnum):
    """Commit guarantee declared by an action; no backend claim is made here."""

    ATOMIC = "ATOMIC"


def _required_text(cls: type[Declaration], field: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeclarationError(f"{cls.__qualname__}.{field} must be a non-empty string.")
    return value


def _object_types(cls: type[Declaration], field: str) -> tuple[type[ObjectType] | str, ...]:
    raw: object = getattr(cls, field, ())
    if isinstance(raw, str | bytes) or not isinstance(raw, Sequence):
        raise DeclarationError(
            f"{cls.__qualname__}.{field} must be a sequence of ObjectType classes "
            "or forward-reference strings."
        )
    entries = tuple(cast(Sequence[object], raw))
    for entry in entries:
        if isinstance(entry, str):
            if not entry.strip():
                raise DeclarationError(
                    f"{cls.__qualname__}.{field} cannot contain a blank forward reference."
                )
        elif not isinstance(entry, type) or not issubclass(entry, ObjectType):
            raise DeclarationError(
                f"{cls.__qualname__}.{field} may only contain ObjectType classes or "
                f"forward-reference strings; found {entry!r}."
            )
    return cast(tuple[type[ObjectType] | str, ...], entries)


def _identities(cls: type[Declaration], field: str) -> tuple[str, ...]:
    raw: object = getattr(cls, field, ())
    if isinstance(raw, str | bytes) or not isinstance(raw, Sequence):
        raise DeclarationError(
            f"{cls.__qualname__}.{field} must be a sequence of identity strings."
        )
    entries = tuple(cast(Sequence[object], raw))
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            raise DeclarationError(
                f"{cls.__qualname__}.{field} must contain non-empty identity strings; "
                f"found {entry!r}."
            )
    return cast(tuple[str, ...], entries)


def _predicate_parameters(predicate: Predicate) -> frozenset[str]:
    if isinstance(predicate, Comparison):
        names = {predicate.left.parameter}
        if isinstance(predicate.right, FieldRef):
            names.add(predicate.right.parameter)
        return frozenset(names)
    if isinstance(predicate, AllOf | AnyOf):
        names: set[str] = set()
        for part in predicate.parts:
            names.update(_predicate_parameters(part))
        return frozenset(names)
    return _predicate_parameters(predicate.operand)


class Effect(Declaration):
    """Outbox intent shape: identity, version, typed payload, optional dedup key."""

    payload: type[Value] | str | None = None
    dedupKey: tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        payload: object = getattr(cls, "payload", None)
        checked_payload: object = _require_payload(payload, f"{cls.__qualname__}.payload")
        dedup_key = _identities(cls, "dedupKey")
        type.__setattr__(cls, "payload", checked_payload)
        type.__setattr__(cls, "dedupKey", dedup_key)
        cls._freeze(require_identity=True)


class Function(Declaration):
    """Read-only derived view: typed params, result, reads and calls only."""

    params: Mapping[str, object] = MappingProxyType({})
    result: type | str | None = None
    reads: tuple[type[ObjectType] | str, ...] = ()
    calls: tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        for forbidden in ("writes", "approval", "effects"):
            if forbidden in cls.__dict__:
                raise DeclarationError(
                    f"{cls.__qualname__} is read-only and cannot declare {forbidden}."
                )
        cls._freeze(require_identity=True)
        result: object = getattr(cls, "result", None)
        checked_result: object = _require_result(result, f"{cls.__qualname__}.result")
        reads = _object_types(cls, "reads")
        calls = _identities(cls, "calls")
        type.__setattr__(cls, "result", checked_result)
        type.__setattr__(cls, "reads", reads)
        type.__setattr__(cls, "calls", calls)
        type.__setattr__(cls, "params", cls.properties)


class Action(Declaration):
    """Behavioral declaration with additive governance metadata.

    Tier 1 needs only identity, version, typed params, reads, writes,
    permission, and ``handler(self, ctx, ...)``. ``calls`` and
    ``commitRequirement`` are tier-2 additions; ``approval`` and ``effects``
    are tier-3 additions. No field is read by executing a handler here.
    """

    params: Mapping[str, object] = MappingProxyType({})
    reads: tuple[type[ObjectType] | str, ...] = ()
    writes: tuple[type[ObjectType] | str, ...] = ()
    calls: tuple[str, ...] = ()
    permission: str = ""
    commitRequirement: CommitRequirement | None = None
    approval: Approval | None = None
    effects: tuple[type[Effect], ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._freeze(require_identity=True)
        params = cls.properties
        permission = _required_text(cls, "permission", getattr(cls, "permission", None))
        reads = _object_types(cls, "reads")
        writes = _object_types(cls, "writes")
        calls = _identities(cls, "calls")

        commit_requirement = _require_commit(
            getattr(cls, "commitRequirement", None), f"{cls.__qualname__}.commitRequirement"
        )

        approval = _require_approval(getattr(cls, "approval", None), f"{cls.__qualname__}.approval")
        if approval is not None:
            undeclared = sorted(
                name for name in _predicate_parameters(approval.when) if name not in params
            )
            if undeclared:
                raise DeclarationError(
                    f"{cls.__qualname__}.approval references undeclared parameter(s): "
                    f"{', '.join(undeclared)}."
                )

        raw_effects: object = getattr(cls, "effects", ())
        if isinstance(raw_effects, str | bytes) or not isinstance(raw_effects, Sequence):
            raise DeclarationError(
                f"{cls.__qualname__}.effects must be a sequence of Effect classes."
            )
        effects = tuple(cast(Sequence[object], raw_effects))
        for effect in effects:
            if not isinstance(effect, type) or not issubclass(effect, Effect):
                raise DeclarationError(
                    f"{cls.__qualname__}.effects may only contain Effect classes; found {effect!r}."
                )

        type.__setattr__(cls, "params", params)
        type.__setattr__(cls, "permission", permission)
        type.__setattr__(cls, "reads", reads)
        type.__setattr__(cls, "writes", writes)
        type.__setattr__(cls, "calls", calls)
        type.__setattr__(cls, "commitRequirement", commit_requirement)
        type.__setattr__(cls, "approval", approval)
        type.__setattr__(cls, "effects", effects)
