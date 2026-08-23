# Testing and quality policy

The repository currently requires 100% tracked statement and branch coverage
for executable code. The fixed exclusion count consists solely of non-executable
`Protocol` declaration ellipses and is independently asserted in CI.
This is an execution-coverage constraint, not evidence of correctness,
educational validity, security, or production suitability.

Coverage is paired with:

- Warning-as-error execution on every supported Python interpreter.
- Assertions on observable behavior and failure modes.
- Property and malformed-input tests for canonicalization and trust boundaries.
- Twenty-two mutation probes for cryptography, persistence, PLCT conformance,
  release/SBOM evidence, safety integrity/decisions, privacy, model transport,
  retrieval, multilingual split/merge alignment, semantic abstention,
  consensus consistency, multilingual uncertainty matching, scoped alignment,
  status projection, canonical quotation, snapshot signing and incomplete metering.
- Clean wheel/sdist installation and multi-platform smoke tests.
- Reproducible-build comparison and artifact verification.
- Static security and dependency auditing.
- Real-browser accessibility smoke tests.

Tests written only to execute a line without asserting a meaningful outcome are
not acceptable. New defects require a regression test. Unreachable defensive
code must be redesigned. New source exclusions require a documented review and
an explicit update to the fixed exclusion-count gate; the coverage threshold
may not be silently lowered to meet a deadline.

The project may revise the numerical threshold only through a public decision
record explaining the risk, excluded behavior, compensating tests, and approval.

Concurrent artifact builds must use separate exported source trees or worktrees.
Setuptools maintains source-discovery metadata in the checkout, so multiple build
backends must not mutate one shared source directory concurrently. GitHub matrix
jobs use isolated checkouts.
