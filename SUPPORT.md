# Support and compatibility

The project is pre-1.0. Maintainers support the latest tagged minor release and
the Python versions declared in `pyproject.toml`. Public schema versions,
command names, exit codes, PLCT adapter requirements, database schema versions,
and signed-package formats are compatibility boundaries.

Bug reports must include the EII version, platform/Python version, command,
sanitized input shape, exact error, and a minimal reproduction. Remove learner
text and credentials. Feature requests should identify the user, educational
decision, evidence needed, and privacy impact.

Deprecations are documented for at least one minor release before removal.
Security fixes may remove unsafe behavior immediately. Petlja export acceptance
is governed by the conformance report, not by undocumented adapter tolerance.
