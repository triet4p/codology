"""Manifest-pinned revision resolution over a linked declaration graph.

A pinned manifest is a durable, value-only statement of the exact declaration
revisions one execution's logic depends on: the root Action, every Action or
Function its declared ``calls`` reach, every declared Effect, and every typed
object/value dependency those declarations name. Resolution is local and
version-explicit; it never consults a default or "latest" revision, so a host
restarted with several revision sets resolves exactly the set the manifest
pins.

Each revision carries a digest of the artifact actually loaded for it. The
local artifact of a declaration is the Python source module that defines it,
and the digest is SHA-256 over that file's bytes with line endings normalized
to LF. Hashing the whole module covers the handler body and every helper beside
it, so changing logic in place changes the digest. Revisions reached through
declared ``calls``, ``effects``, or typed object/value edges are pinned
separately, so cross-module logic is covered transitively through the linked
graph. The module a host imports is the artifact this layer pins; mutating
already-imported code in place is outside the in-process trust boundary, as it
is for every other gate in this package.

Two limits are explicit instead of silent. Imports and helpers from modules
that are not themselves declared in the graph are outside the supported
pinning scope. Anonymous values have no durable revision identity; they are
covered only by the module digest of the revision that declares them. The
digest is never an intent fingerprint, an identity, or a version label, and
this module defines no build or publish pipeline.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, cast

from codology.declarations import HANDLER_NAME, Action, Declaration, Function
from codology.linking import LinkedDeclarations, LinkedDefinition
from codology.snapshot import DefinitionKey, definition_kind

MANIFEST_FORMAT: Final = "codology.manifest/1"
ARTIFACT_DIGEST_PREFIX: Final = "sha256:"

_ROOT: Final = "root"
_CHILDREN: Final = "children"
_EFFECTS: Final = "effects"
_ONTOLOGY: Final = "ontology"
_GROUPS: Final = (_CHILDREN, _EFFECTS, _ONTOLOGY)

_ALLOWED_KINDS: Final = {
    _ROOT: frozenset({"Action"}),
    _CHILDREN: frozenset({"Action", "Function"}),
    _EFFECTS: frozenset({"Effect"}),
    _ONTOLOGY: frozenset({"ObjectType", "Value"}),
}

_DIGEST_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}")
_MANIFEST_KEYS: Final = frozenset({"format", "root", "children", "effects", "ontology"})
_REVISION_KEYS: Final = frozenset({"identity", "version", "kind", "digest"})


class ManifestError(ValueError):
    """A pinned revision set cannot be identified or resolved safely."""


class InvalidManifest(ManifestError):
    """A manifest document or value is malformed and cannot be trusted."""


class UnsupportedArtifact(ManifestError):
    """A revision has no local source artifact whose bytes the manifest can pin."""


class MissingArtifact(ManifestError):
    """A pinned revision, or its readable source artifact, is absent from the host."""

    def __init__(self, message: str, *, identity: str, version: str) -> None:
        super().__init__(message)
        self.identity = identity
        self.version = version


class DigestMismatch(ManifestError):
    """The artifact loaded for a pinned revision does not hash to the pinned digest."""

    def __init__(
        self,
        message: str,
        *,
        identity: str,
        version: str,
        expected: str,
        actual: str,
    ) -> None:
        super().__init__(message)
        self.identity = identity
        self.version = version
        self.expected = expected
        self.actual = actual


class KindMismatch(ManifestError):
    """The host loaded a different declaration kind at a pinned revision."""

    def __init__(self, message: str, *, identity: str, version: str) -> None:
        super().__init__(message)
        self.identity = identity
        self.version = version


class ClosureMismatch(ManifestError):
    """The resolved dependency graph is not exactly the revisions the manifest pins."""


@dataclass(frozen=True, slots=True, order=True)
class ArtifactRevision:
    """One revision and the digest of the local artifact that defines it."""

    identity: str
    version: str
    kind: str
    digest: str

    def __post_init__(self) -> None:
        for field in ("identity", "version", "kind"):
            value: object = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise InvalidManifest(f"ArtifactRevision.{field} must be a non-empty string.")
        digest = cast(object, self.digest)
        if not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None:
            raise InvalidManifest(
                "ArtifactRevision.digest must be 'sha256:' followed by 64 lowercase hex digits."
            )

    @property
    def key(self) -> DefinitionKey:
        return DefinitionKey(self.identity, self.version)


@dataclass(frozen=True, slots=True)
class PinnedManifest:
    """The exact revisions one execution's logic depends on, grouped by role."""

    root: ArtifactRevision
    children: tuple[ArtifactRevision, ...] = ()
    effects: tuple[ArtifactRevision, ...] = ()
    ontology: tuple[ArtifactRevision, ...] = ()
    manifest_format: str = MANIFEST_FORMAT

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.root), ArtifactRevision):
            raise TypeError("PinnedManifest.root must be an ArtifactRevision.")
        if self.manifest_format != MANIFEST_FORMAT:
            raise InvalidManifest(
                f"manifest format {self.manifest_format!r} is not {MANIFEST_FORMAT!r}."
            )
        _check_kind(_ROOT, self.root)
        seen = {self.root.key}
        for group in _GROUPS:
            raw: object = getattr(self, group)
            if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
                raise TypeError(f"PinnedManifest.{group} must be a sequence of revisions.")
            entries = tuple(cast(Sequence[ArtifactRevision], raw))
            for entry in entries:
                if not isinstance(cast(object, entry), ArtifactRevision):
                    raise TypeError(
                        f"PinnedManifest.{group} may only hold ArtifactRevision values."
                    )
                _check_kind(group, entry)
                if entry.key in seen:
                    raise InvalidManifest(
                        f"revision {entry.identity!r} at version {entry.version!r} "
                        "is pinned more than once."
                    )
                seen.add(entry.key)
            object.__setattr__(self, group, tuple(sorted(entries)))

    @property
    def entries(self) -> tuple[ArtifactRevision, ...]:
        """Every pinned revision, root first."""
        return (self.root, *self.children, *self.effects, *self.ontology)

    def find(self, identity: str, version: str) -> ArtifactRevision | None:
        """Return the pinned revision for exactly ``identity`` at ``version``, if any."""
        for entry in self.entries:
            if entry.identity == identity and entry.version == version:
                return entry
        return None


@dataclass(frozen=True, slots=True)
class ResolvedManifest:
    """A verified manifest with the linked definitions it resolves to on this host."""

    manifest: PinnedManifest
    definitions: Mapping[DefinitionKey, LinkedDefinition]
    source: LinkedDeclarations

    def __post_init__(self) -> None:
        if not isinstance(cast(object, self.manifest), PinnedManifest):
            raise TypeError("ResolvedManifest.manifest must be a PinnedManifest.")
        if not isinstance(cast(object, self.source), LinkedDeclarations):
            raise TypeError("ResolvedManifest.source must be the LinkedDeclarations it came from.")
        definitions = dict(self.definitions)
        expected = {entry.key for entry in self.manifest.entries}
        if set(definitions) != expected:
            raise InvalidManifest(
                "a resolved manifest must map exactly the revisions the manifest pins."
            )
        object.__setattr__(self, "definitions", MappingProxyType(definitions))

    @property
    def root(self) -> LinkedDefinition:
        """The pinned root Action as linked on this host."""
        return self.lookup(self.manifest.root.key)

    def lookup(self, key: DefinitionKey) -> LinkedDefinition:
        """Return the linked definition resolved for exactly ``key``."""
        if not isinstance(cast(object, key), DefinitionKey):
            raise TypeError("ResolvedManifest.lookup() expects a version-explicit DefinitionKey.")
        try:
            return self.definitions[key]
        except KeyError as exc:
            raise MissingArtifact(
                f"the resolved manifest has no revision {key.identity!r} "
                f"at version {key.version!r}.",
                identity=key.identity,
                version=key.version,
            ) from exc


def encode_manifest(manifest: PinnedManifest) -> str:
    """Encode a manifest as canonical JSON so it can be stored and compared."""
    if not isinstance(cast(object, manifest), PinnedManifest):
        raise TypeError("encode_manifest() expects a PinnedManifest.")
    document = {
        "format": manifest.manifest_format,
        "root": _revision_document(manifest.root),
        "children": [_revision_document(entry) for entry in manifest.children],
        "effects": [_revision_document(entry) for entry in manifest.effects],
        "ontology": [_revision_document(entry) for entry in manifest.ontology],
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def decode_manifest(payload: str) -> PinnedManifest:
    """Decode canonical manifest JSON, rejecting any malformed or unknown field."""
    if not isinstance(cast(object, payload), str):
        raise TypeError("decode_manifest() expects the JSON text produced by encode_manifest().")
    try:
        decoded: object = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise InvalidManifest("the manifest is not valid JSON.") from exc
    if not isinstance(decoded, dict):
        raise InvalidManifest("the manifest must be a JSON object.")
    document = cast(Mapping[object, object], decoded)
    if cast(frozenset[str], frozenset(document)) != _MANIFEST_KEYS:
        raise InvalidManifest(
            f"the manifest must have exactly the fields {sorted(_MANIFEST_KEYS)}."
        )
    encoded_format = document["format"]
    if not isinstance(encoded_format, str):
        raise InvalidManifest("the manifest format must be a string.")

    root = _decode_revision(document["root"])
    groups: dict[str, tuple[ArtifactRevision, ...]] = {}
    for group in _GROUPS:
        raw = document[group]
        if not isinstance(raw, list):
            raise InvalidManifest(f"manifest field {group!r} must be a list.")
        groups[group] = tuple(_decode_revision(item) for item in cast(list[object], raw))
    return PinnedManifest(
        root=root,
        children=groups[_CHILDREN],
        effects=groups[_EFFECTS],
        ontology=groups[_ONTOLOGY],
        manifest_format=encoded_format,
    )


def manifest_digest(manifest: PinnedManifest) -> str:
    """Identify a manifest by its canonical bytes, not by a name or version."""
    encoded = encode_manifest(manifest)
    return ARTIFACT_DIGEST_PREFIX + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def pin_manifest(linked: LinkedDeclarations, action: DefinitionKey) -> PinnedManifest:
    """Pin the exact logic closure reachable from one linked Action revision."""
    if not isinstance(cast(object, linked), LinkedDeclarations):
        raise TypeError("pin_manifest() expects the LinkedDeclarations produced by link().")
    if not isinstance(cast(object, action), DefinitionKey):
        raise TypeError("pin_manifest() expects a version-explicit DefinitionKey.")

    roles = _closure_roles(linked, action)
    grouped: dict[str, list[ArtifactRevision]] = {group: [] for group in _GROUPS}
    root: ArtifactRevision | None = None
    for key, role in roles.items():
        revision = _revision(_loaded(linked, key))
        if role == _ROOT:
            root = revision
            continue
        grouped[role].append(revision)
    if root is None:
        raise InvalidManifest("the pinned root revision is missing from its own closure.")
    return PinnedManifest(
        root=root,
        children=tuple(grouped[_CHILDREN]),
        effects=tuple(grouped[_EFFECTS]),
        ontology=tuple(grouped[_ONTOLOGY]),
    )


def resolve_manifest(
    manifest: PinnedManifest,
    revisions: LinkedDeclarations | Sequence[LinkedDeclarations],
) -> ResolvedManifest:
    """Resolve ``manifest`` against the host's loaded revision sets, or fail closed.

    ``revisions`` is one linked graph or several revision sets a host holds at
    once. A set qualifies only when every pinned revision is loaded there at
    its exact version, the linked dependency closure from the pinned root is
    exactly the pinned graph, and every artifact's digest and kind match. No
    default version is consulted; the first qualifying set wins when several
    sets agree on the pinned bytes.
    """
    if not isinstance(cast(object, manifest), PinnedManifest):
        raise TypeError("resolve_manifest() expects a PinnedManifest.")
    sets = _revision_sets(revisions)
    candidates = _root_candidates(sets, manifest.root)
    if not candidates:
        raise MissingArtifact(
            f"no revision set loaded {manifest.root.identity!r} at version "
            f"{manifest.root.version!r}; the pinned root artifact is missing.",
            identity=manifest.root.identity,
            version=manifest.root.version,
        )

    failures: list[ManifestError] = []
    for linked in candidates:
        try:
            definitions = _verify_set(linked, manifest)
        except ManifestError as exc:
            failures.append(exc)
            continue
        return ResolvedManifest(manifest, definitions, linked)
    raise failures[0]


def _verify_set(
    linked: LinkedDeclarations,
    manifest: PinnedManifest,
) -> Mapping[DefinitionKey, LinkedDefinition]:
    definitions: dict[DefinitionKey, LinkedDefinition] = {}
    for entry in manifest.entries:
        item = linked.definitions.get(entry.identity)
        if item is None or item.definition.version != entry.version:
            raise MissingArtifact(
                f"the pinned revision {entry.identity!r} at version {entry.version!r} "
                "is not loaded in this revision set.",
                identity=entry.identity,
                version=entry.version,
            )
        definitions[entry.key] = item

    for entry in manifest.entries:
        declaration = definitions[entry.key].definition.declaration
        kind = definition_kind(declaration)
        if kind != entry.kind:
            raise KindMismatch(
                f"the revision {entry.identity!r} at version {entry.version!r} is a "
                f"{kind}, but the manifest pins a {entry.kind}.",
                identity=entry.identity,
                version=entry.version,
            )

    expected = {manifest.root.key: _ROOT}
    for group in _GROUPS:
        for entry in cast(Sequence[ArtifactRevision], getattr(manifest, group)):
            expected[entry.key] = group
    actual = _closure_roles(linked, manifest.root.key)
    if actual != expected:
        raise ClosureMismatch(_closure_detail(expected, actual))

    for entry in manifest.entries:
        declaration = definitions[entry.key].definition.declaration
        actual_digest = _artifact_digest(declaration)
        if actual_digest != entry.digest:
            raise DigestMismatch(
                f"the artifact loaded for {entry.identity!r} at version "
                f"{entry.version!r} hashes to {actual_digest}, but the manifest pins "
                f"{entry.digest}.",
                identity=entry.identity,
                version=entry.version,
                expected=entry.digest,
                actual=actual_digest,
            )
    return definitions


def _closure_roles(
    linked: LinkedDeclarations,
    root: DefinitionKey,
) -> dict[DefinitionKey, str]:
    item = _loaded(linked, root)
    if definition_kind(item.definition.declaration) != "Action":
        raise InvalidManifest(
            f"the pinned root {root.identity!r} at version {root.version!r} is not an Action."
        )
    roles: dict[DefinitionKey, str] = {root: _ROOT}
    queue: deque[LinkedDefinition] = deque([item])
    while queue:
        current = queue.popleft()
        for reference in current.references:
            target = reference.target
            identity = target.identity
            version = target.version
            if identity is None or version is None:
                continue
            key = DefinitionKey(identity, version)
            if key in roles:
                continue
            roles[key] = _role_of(definition_kind(target.declaration))
            queue.append(_loaded(linked, key))
    return roles


def _loaded(linked: LinkedDeclarations, key: DefinitionKey) -> LinkedDefinition:
    item = linked.definitions.get(key.identity)
    if item is None or item.definition.version != key.version:
        raise MissingArtifact(
            f"no loaded definition for {key.identity!r} at version {key.version!r}.",
            identity=key.identity,
            version=key.version,
        )
    return item


def _role_of(kind: str) -> str:
    if kind == "Effect":
        return _EFFECTS
    if kind in {"Action", "Function"}:
        return _CHILDREN
    if kind in {"ObjectType", "Value"}:
        return _ONTOLOGY
    raise UnsupportedArtifact(
        f"a {kind} revision has no pinnable role; pin Action, Function, Effect, "
        "ObjectType, and Value revisions only."
    )


def _revision(item: LinkedDefinition) -> ArtifactRevision:
    definition = item.definition
    identity = definition.identity
    version = definition.version
    if identity is None or version is None:
        raise UnsupportedArtifact(
            f"the anonymous {definition.declaration.__qualname__} has no durable revision identity."
        )
    return ArtifactRevision(
        identity=identity,
        version=version,
        kind=definition_kind(definition.declaration),
        digest=_artifact_digest(definition.declaration),
    )


def _artifact_digest(declaration: type[Declaration]) -> str:
    source = _artifact_source(declaration)
    try:
        raw = Path(source).read_bytes()
    except OSError as exc:
        identity = cast(object, getattr(declaration, "identity", None))
        version = cast(object, getattr(declaration, "version", None))
        raise MissingArtifact(
            f"the source artifact {source!r} for {declaration.__qualname__} cannot be read.",
            identity=identity if isinstance(identity, str) else "<anonymous>",
            version=version if isinstance(version, str) else "<anonymous>",
        ) from exc
    normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return ARTIFACT_DIGEST_PREFIX + hashlib.sha256(normalized).hexdigest()


def _artifact_source(declaration: type[Declaration]) -> str:
    try:
        source = inspect.getsourcefile(declaration)
    except (TypeError, OSError) as exc:
        raise UnsupportedArtifact(
            f"the declaration {declaration.__qualname__} has no readable source artifact."
        ) from exc
    if source is None:
        raise UnsupportedArtifact(
            f"the declaration {declaration.__qualname__} has no source file to pin."
        )
    if issubclass(declaration, Action | Function):
        handler = vars(declaration).get(HANDLER_NAME)
        try:
            handler_source = inspect.getsourcefile(handler) if handler is not None else None
        except (TypeError, OSError) as exc:
            raise UnsupportedArtifact(
                f"the handler of {declaration.__qualname__} has no readable source artifact."
            ) from exc
        if handler_source is None or Path(handler_source).resolve() != Path(source).resolve():
            raise UnsupportedArtifact(
                f"the handler of {declaration.__qualname__} must be defined in the "
                "declaration's own source module so the pinned digest covers it."
            )
    return source


def _root_candidates(
    sets: tuple[LinkedDeclarations, ...],
    root: ArtifactRevision,
) -> tuple[LinkedDeclarations, ...]:
    candidates: list[LinkedDeclarations] = []
    for linked in sets:
        item = linked.definitions.get(root.identity)
        if item is not None and item.definition.version == root.version:
            candidates.append(linked)
    return tuple(candidates)


def _revision_sets(
    revisions: LinkedDeclarations | Sequence[LinkedDeclarations],
) -> tuple[LinkedDeclarations, ...]:
    value = cast(object, revisions)
    if isinstance(value, LinkedDeclarations):
        return (value,)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(
            "resolve_manifest() expects one LinkedDeclarations or a sequence of revision sets."
        )
    sets = tuple(cast(Sequence[object], value))
    if not sets:
        raise InvalidManifest("resolve_manifest() needs at least one revision set.")
    for item in sets:
        if not isinstance(item, LinkedDeclarations):
            raise TypeError("every revision set must be LinkedDeclarations from link().")
    return cast(tuple[LinkedDeclarations, ...], sets)


def _check_kind(group: str, entry: ArtifactRevision) -> None:
    allowed = _ALLOWED_KINDS[group]
    if entry.kind not in allowed:
        raise InvalidManifest(
            f"revision {entry.identity!r} at version {entry.version!r} is a "
            f"{entry.kind}, which cannot be pinned as {group!r}; expected {sorted(allowed)}."
        )


def _revision_document(entry: ArtifactRevision) -> dict[str, str]:
    return {
        "identity": entry.identity,
        "version": entry.version,
        "kind": entry.kind,
        "digest": entry.digest,
    }


def _decode_revision(value: object) -> ArtifactRevision:
    if not isinstance(value, dict):
        raise InvalidManifest("every manifest revision must be a JSON object.")
    document = cast(Mapping[object, object], value)
    if cast(frozenset[str], frozenset(document)) != _REVISION_KEYS:
        raise InvalidManifest(
            f"a manifest revision must have exactly the fields {sorted(_REVISION_KEYS)}."
        )
    fields: dict[str, str] = {}
    for name in _REVISION_KEYS:
        field = document[name]
        if not isinstance(field, str):
            raise InvalidManifest(f"a manifest revision field {name!r} must be a string.")
        fields[name] = field
    return ArtifactRevision(
        identity=fields["identity"],
        version=fields["version"],
        kind=fields["kind"],
        digest=fields["digest"],
    )


def _closure_detail(
    expected: Mapping[DefinitionKey, str],
    actual: Mapping[DefinitionKey, str],
) -> str:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    moved = sorted(key for key in set(expected) & set(actual) if expected[key] != actual[key])

    def label(keys: Sequence[DefinitionKey]) -> str:
        return ", ".join(f"{key.identity}@{key.version}" for key in keys) or "none"

    return (
        "the linked dependency closure does not match the pinned manifest: "
        f"pinned but unreachable [{label(missing)}]; reachable but unpinned "
        f"[{label(extra)}]; pinned under another role [{label(moved)}]."
    )


__all__ = [
    "ArtifactRevision",
    "ClosureMismatch",
    "ARTIFACT_DIGEST_PREFIX",
    "DigestMismatch",
    "InvalidManifest",
    "KindMismatch",
    "MANIFEST_FORMAT",
    "ManifestError",
    "MissingArtifact",
    "PinnedManifest",
    "ResolvedManifest",
    "UnsupportedArtifact",
    "decode_manifest",
    "encode_manifest",
    "manifest_digest",
    "pin_manifest",
    "resolve_manifest",
]
