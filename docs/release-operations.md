# Release and supply-chain operations

No release tag may be created merely to discover whether CI passes. Tags and
published assets are the output of verification, never its input.

## Required sequence

1. Create a release branch and set the producer version once in
   `src/eii/_version.py`.
2. Open a pull request. Require the complete CI workflow and review before merge.
3. Merge to protected `main` and require the complete `main` CI run to pass.
4. Manually run **Release candidate** on `main` with the exact version.
5. Download the unpublished candidate artifact and independently verify its
   wheel, sdist, checksums, SBOM, revision, and version binding.
6. Run **Promote exact release candidate** through the protected
   `production-release` environment. It re-verifies provenance and source digest,
   emits `APPROVAL.json` containing the candidate run, actor, protected
   environment, approval run, checked artifact hashes and revision, binds that
   record into the signed manifest, and stores approved bytes without a tag.
7. Run **Publish approved release** through the separately protected
   `production-publish` environment. Only then create the release tag
   `v<producer-version>`. The tag is a locator;
   the signed release manifest and GitHub attestation are the trust evidence.
8. Publish exactly the candidate bytes; do not rebuild after approval.
9. Install the downloaded public assets in a clean environment and verify CLI
   version, evidence producer version, checksums, signatures, and rollback.

The candidate and promotion workflows do not create tags or releases. Only the
final publication workflow has that boundary, after a second environment approval.

## Release gates

A candidate is blocked unless all of the following pass:

- Expanded Ruff lint and formatting.
- Mypy static analysis.
- Warning-as-error tests and 100% tracked statement/branch coverage.
- Schema, property, malformed-input, concurrency, recovery and mutation tests.
- Deterministic six-language fixture output.
- Reproducible wheel and normalized sdist comparison.
- Clean sdist-to-wheel and wheel installation.
- Linux container, Windows and macOS portability smoke tests.
- Browser/accessibility smoke tests.
- Static security and dependency audits.
- Producer/package/CLI/evidence/artifact/release-evidence/tag version binding.
- A clean Git worktree plus SHA-256 digest of the exact `git archive` source tree.

Coverage is governed by `docs/testing-policy.md`; it is not a substitute for
meaningful assertions or external validation.

## Version binding

The producer version comes only from `eii._version`. Setuptools reads that value
for package metadata. `EvidenceBundle.create` reads the same value. The release
preflight rejects a mismatched requested version, tag, wheel, sdist, or producer.
Schema, database, adapter and course versions are independent compatibility
identities described in `docs/architecture.md`.

## Evidence and signing

Build with a fixed `SOURCE_DATE_EPOCH`. Generate SPDX evidence, checksums, and
provenance binding revision, source-archive digest, workflow, runner, tool versions,
and artifacts.
Sign the canonical release manifest—which binds checksums, release evidence,
SBOM, machine-generated promotion approval, project, version and revision—with
the release publisher key and verify it
before publication:

```bash
eii release-sign ./release-evidence --private-key-file publisher-private.pem \
  --public-key-file publisher-public.pem
eii release-verify ./release-evidence --artifacts ./dist \
  --public-key-file publisher-public.pem
```

The candidate build job emits SLSA build provenance and an SPDX SBOM attestation
at the point where the artifacts are constructed. The `Promote exact release
candidate` workflow accepts only a successful `Release candidate` run from
`main`, downloads its exact retained artifact, verifies both SLSA and SPDX
attestations against the exact workflow identity, source digest and `main` ref,
checks its embedded revision, version and independently recomputed Git-archive
digest, writes machine-verifiable approval evidence containing hashes of the
actual candidate-resolution, source-binding, provenance, SBOM, and release-verification
receipts, copies those receipts into the approved artifact, validates their structured
content and exact hashes, and signs the complete manifest including every receipt and
that evidence inside the protected `production-release` environment. The provenance
and SBOM receipts are the JSON verification results emitted by
`gh attestation verify --format=json`; validation requires the expected predicate,
verified certificate/timestamp material, and coverage of every release artifact digest.
The workflow then verifies the result and uploads immutable approved bytes. Configure required reviewers plus
`EII_RELEASE_PRIVATE_KEY_PEM` and `EII_RELEASE_PUBLIC_KEY_PEM` in that environment.
The separate `Publish approved release` workflow requires its actor to differ
from the recorded promotion actor, re-verifies the signed bytes,
requires `main` still to equal the approved revision, then atomically creates the
tag and public release inside `production-publish`.

The publication workflow rejects the promotion actor as publisher, providing a
machine-enforced two-person release boundary. Until VAL-010 closes, maintainer
succession, independent control of two accounts, and signing-key succession remain
explicit governance gaps. Appoint and rehearse those roles using
[`maintainer-succession.md`](maintainer-succession.md); the runbook is preparation,
not substitute evidence.
The record conforms to the immutable
[`release-approval-1.0`](https://eii.edu.eu/schemas/release-approval-1.0.json)
schema and is verified against `release-evidence.json` before signing and again
before publication.

PEM secrets are the portable baseline. Mature deployments should replace them with
OIDC-authorized KMS/HSM signing or an equivalently audited keyless workflow; a private
release key must never be available to untrusted pull-request execution.

The two-build comparison establishes repeatability on one pinned runner image. It is
not independent reproducibility; that status requires a separately administered
rebuild which compares the same source digest and published artifact bytes.

CI provenance does not replace publisher approval, educational validation, or
an independent security review. Release notes identify schema/database changes,
deprecations, security fixes, known limitations, supported platforms, external
validation status, and rollback constraints.

Review `THIRD_PARTY_LICENSES.md` for every release. A release is blocked when a
redistributed component has an unknown licence or lacks required notices.
