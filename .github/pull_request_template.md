## Purpose

Describe the user-visible or engineering outcome.

## Evidence

- [ ] Tests cover positive, negative, and relevant boundary behavior.
- [ ] `ruff check src tests tools` passes.
- [ ] `ruff format --check src tests tools` passes.
- [ ] `mypy` passes.
- [ ] Warning-as-error branch coverage remains exactly 100%.
- [ ] Documentation and the claims/evidence register match shipped behavior.
- [ ] No release tag or public artifact was created before this pull request's full CI passed.

## Compatibility and risk

Describe schema, adapter, security, privacy, migration, and rollback effects, or
state why each is not applicable.
