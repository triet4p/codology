# Changelog

## [Unreleased]

### Added

- Added the `codology` Python package scaffold with an importable static `codology.declarations` layer and a documented single `handler(self, ctx, ...)` convention.
- Added project packaging with `pyproject.toml` and `uv.lock`, plus the pytest baseline, Pyright strict configuration, and Ruff configuration.
- Added lazy forward-reference resolution for declaration annotations, resolved at link time against a composed namespace so modules can reference each other's types without runtime import cycles.
- Added `README.md` with install, test, and type-check commands, and `docs/official/design/implementation-baseline.md` recording the Python version, layout, tooling, and handler convention decisions.
