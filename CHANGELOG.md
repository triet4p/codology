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
