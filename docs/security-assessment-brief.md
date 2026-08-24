# Independent security assessment brief

This brief is ready for procurement; it is not evidence that an assessment has
occurred. EII must select an assessor independent of the implementation team.

## Scope

Review Ed25519 signing and trust rotation, release approval evidence, appliance
installation and rollback, HTTP authorization and resource limits, SQLite
concurrency and recovery, Classroom Weather adjacency/sensitivity and privacy
budget enforcement, database-clone handling, secrets, logs, dependency and
CI/CD controls, and the threat model's completeness.

The assessor receives source, test fixtures, workflows, architecture and threat
documentation, and a synthetic deployment. No real learner data is required.

## Required work

- Reproduce builds and security gates in an assessor-controlled environment.
- Threat-model trust boundaries and abuse cases independently.
- Review cryptographic invocation, key lifecycle, rotation and recovery.
- Attempt package substitution, rollback, path, concurrency, budget-race,
  database-clone, prompt-injection and denial-of-service attacks.
- Review the fixed-universe DP proof and distinguish implementation correctness
  from deployment-specific privacy claims.
- Report severity, exploit prerequisites, evidence, remediation and retest state.

## Deliverables and acceptance

Deliver a full confidential report, a publishable summary, machine-readable
finding list, remediation verification, assessor identity and independence
statement, dates, reviewed revision, environment and tool versions. EII closes
VAL-006 only when all critical/high findings are remediated or explicitly
accepted by an accountable person and the assessor verifies the final revision.

Security findings must use the coordinated disclosure process in `SECURITY.md`.
The assessor does not certify educational accuracy, legal compliance, or a
deployment not included in the reviewed scope.
