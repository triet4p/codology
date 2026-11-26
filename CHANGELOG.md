# Changelog

## [Unreleased]

### Added

- Added the `codology` Python package scaffold with an importable static `codology.declarations` layer and a documented single `handler(self, ctx, ...)` convention.
- Added project packaging with `pyproject.toml` and `uv.lock`, plus the pytest baseline, Pyright strict configuration, and Ruff configuration.
- Added lazy forward-reference resolution for declaration annotations, resolved at link time against a composed namespace so modules can reference each other's types without runtime import cycles.
- Added `README.md` with install, test, and type-check commands, and `docs/official/design/implementation-baseline.md` recording the Python version, layout, tooling, and handler convention decisions.
- Added immutable class-based structural declarations (`Module`, `ObjectType`, `Value`, `Link`, `ObjectRef`) with explicit identity and version, typed properties, typed link specs, and frozen exports.
- Added immutable behavioral declarations (`Action`, `Function`, `Effect`) with typed params, `reads`/`writes`/`calls`, `permission`, commit requirement, and effect payload metadata, enabling tier-1, cross-module, and approval/effect declarations without executing handlers.
- Added structured approval predicates that preserve each comparison operator (including `>` versus `>=`) and reject lambdas, method calls, and other unsupported expressions with clear errors.
- Added a `load()` phase that collects declarations per owning module into an immutable model, keeps each declared identity and version, and rejects duplicate identities or unknown declaration fields with module, identity, and field context.
- Added a `link()` phase that resolves forward annotations and typed references across composed modules, rejects unresolved, wrong-kind, unexported, mismatched `ObjectRef[T]`, and mismatched handler declarations with module/identity/field context, and returns an immutable linked model without calling handlers.
- Added an immutable `snapshot()` view over the linked graph with version-explicit `(identity, version)` lookup and no implicit `latest`, exposing dependency edges and structured approval expressions that preserve comparison operators such as `>` versus `>=`. No handler digest is published.
- Added a runnable Procurement/Finance example under `examples/procurement_finance/` that composes the public Load, Link, and Snapshot API and demonstrates duplicate identity, missing export, unresolved reference, handler type/signature mismatch, and lambda approval failures without a backend.
- Added `bind_action()` deployment binding for `ATOMIC` actions: it checks provider capability, the transitive write set across `calls`, a single enlisted session, and delegation grants against the declared `calls`/`permission` contract. Missing capability, unbound child writes, split sessions, and ambient or broadened delegation mappings are rejected before any handler or business transaction runs.
- Added a file-backed SQLite transaction adapter with guarded conditional writes checked by `rowcount`, and an engine-owned `commit_guarded_writes()` boundary that rolls back before commit on any failure. Money is represented as exact integer minor units (`MinorMoney`) with one pinned currency and no FX.
