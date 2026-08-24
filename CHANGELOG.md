# Changelog

All notable changes are recorded here. This project follows semantic versioning.

## [Unreleased]

Development toward 0.3.0. These changes are not part of the published 0.2.0
artifacts and must pass the complete candidate, two-person promotion, and
publication process before a 0.3.0 release is declared.

### Added

- Golden multilingual accuracy and false-positive corpora, property-based detector
  fuzzing, and a scheduled twenty-pass randomized flakiness workflow.
- Fixed-universe differential-privacy publication, synchronized Weather storage,
  and explicit database lineage and fork controls.
- Structured promotion receipts for candidate identity, source binding, SLSA
  provenance, and SPDX attestations, all bound into the signed release manifest.

### Changed

- Appliance routing and CLI parsing/dispatch are split into focused modules and
  protected by CI-enforced line and AST-statement budgets.
- The accuracy corpus now includes four labeled cases, including clean and positive
  six-language fixtures covering numeric, unit, order, code, link, and missing-content
  signals; corpus-shape ratchets prevent accidental loss of its validation floor.
- Runtime Ed25519 compatibility is behaviorally self-tested, and release governance
  fails closed against self-review and administrator bypass.
- The validation register maps every provisional or external claim to an owned,
  evidence-based closure commitment.

## [0.2.0] - 2026-08-24

The second public alpha strengthens decision integrity, multilingual retrieval,
privacy accounting, and crash recovery. It remains an internally verified software
release, not independent certification or evidence of educational effectiveness.

### Added

- Semantic-panel records expose configured-panel agreement, completion, winning-side
  confidence, dissent confidence, property agreement, and failed-member counts as
  separate signals. Provider failures fail closed unless policy explicitly permits
  a bounded number.
- Semantic evaluation record 2.0 and Weather Map 3.0 schemas, while preserving the
  published 1.0 and 2.0 schema identifiers for compatibility.
- Versioned alignment ranking with auditable components, hard conflicting-ID
  constraints, partial-ID handling, and consistent selection/evidence scoring.
- Phrase-aware, provenance-bearing glossary expansion for explicitly covered
  cross-language BM25 terms without claiming general semantic retrieval.
- Persistent differential-privacy budgets, memoized Laplace releases, pre-spend
  authorization, exact-byte export binding, and independently managed ledger keys.
- Authenticated, fsync-backed publication journals that deterministically recover or
  roll back every tested filesystem/database crash phase.

### Changed

- Artifact verification authenticates the complete append-only HMAC chain instead of
  trusting the mutable latest-export index.
- Weather CLI operation requires a separate durable ledger-key file and stable
  deployment database identity; privacy-key rotation rejects an implicitly shared
  ledger key.
- Consensus, alignment, glossary, privacy, recovery, schema, migration, malformed-input,
  and adversarial tests expanded the suite to 255 tests, 6,109 statements, 1,924 branches,
  and 24 critical mutation probes, all passing their configured gates.

## [0.1.0] - 2026-08-24

First release of the EII Open Learning Observatory. Version 0.1.0 establishes
software mechanisms and explicit validation boundaries; it does not claim Petlja
endorsement, independent certification, production approval, or empirical
educational effectiveness.

### Added

- A provider-independent course and evidence model with stable source locators,
  RFC 8785 canonical JSON, immutable hashes, schemas, provenance, and reviewable
  HTML/JSON reports.
- Replaceable adapters for structured repositories, a proposed PLCT export
  contract, H5P, Open edX OLX, Moodle, Kolibri, MediaWiki, and learning graphs.
- BabelBridge structural and terminology drift analysis, model-assisted semantic
  comparison, bilingual grounded tutoring, and blinded multilingual review studies.
- Relationship-aware split/merge translation analysis, low-confidence semantic
  abstention, and quorum-based distinct-configuration consensus with complete
  member-judgment and failure provenance. Organizational/model independence is
  intentionally not inferred from configuration diversity.
- Complete audit-directory integrity binds passing, drift and abstained semantic
  evaluations, alignment/status projections and the HTML report to one sealed
  evidence bundle; `eii validate` verifies either a bundle or the whole directory.
- Typed semantic-evaluation records bind canonical constituent evidence and exact
  model-run identities; validators reject misquoted excerpts, unknown or cross-
  relationship evidence, inconsistent member judgments and contradictory finding
  projections for both standalone bundles and complete directories. A sealed plan
  proves that every requested relationship/release comparison has exactly one result.
- Consensus excludes member abstentions from voting and abstains when neither
  outcome reaches a strict configured majority.
- Snapshot-safe audit manifest 2.0 signatures bind signer, purpose and time;
  optional authorization policies constrain signer/key/purpose/validity tuples;
  verification is size-bounded and rejects implausibly future signing times.
- Number/unit comparison uses an explicit unit and currency vocabulary so translated
  nouns and connector words cannot be misclassified as measurement drift.
- Curriculum MRI objective/evidence/assessment mapping, accessibility and
  prerequisite checks, model-assisted editorial hypotheses, and regression fixtures.
- Tutor Safety Case schema 3.0 with replayable model requests, exact retrieved
  evidence, derived release gates, evaluator identity, signed human review, and
  strict separation of validation, authentication, and authorization.
- Deterministic missing-evidence refusal checks cover English, Serbian, Spanish,
  Portuguese, Catalan, and Croatian, including Serbian Latin and Cyrillic forms.
- Unicode-normalized whole-phrase refusal matching prevents punctuation variance
  and unrelated substring matches from changing safety results.
- Classroom Weather Map with minimized categorical inputs, local aggregation,
  retention and cohort controls, scoped pseudonyms, key rotation, coarsened
  disclosure, and an authenticated append-only export ledger.
- School-in-a-Box packaging, Ed25519 verification and trust rotation, atomic
  activation and rollback, offline safety gates, local course serving, and a
  loopback-only model interface.
- Signed external-validation records, PLCT attestations, federation envelopes,
  release evidence, SPDX 2.3 SBOM generation, and exact-artifact promotion.

### Security and quality

- HTTP model response reads share a hard wall-clock deadline with connection and
  retry work, Prometheus histograms contain only observed latency samples, and
  managed audit logs enforce one writer, no symlink target, periodic retention,
  private permissions, bounded records, and safe partial initialization.

- Ed25519-only package creation and installation; symmetric-key/HMAC packages are
  rejected and have no supported compatibility path.
- OpenSSL 3 or newer is validated at runtime, and portable CI exercises real Ed25519
  operations on Linux, macOS, and Windows.
- Defensive archive, XML, path, HTTP, model-transport, database, privacy, and
  signature validation at all untrusted boundaries.
- Strict typing, expanded Ruff linting and formatting, warning-as-error tests on
  every supported Python interpreter,
  exact statement/branch coverage, mutation/property/concurrency/recovery tests,
  browser accessibility checks, dependency auditing, and reproducible normalized
  wheel/source-distribution verification.
- Condition-backed HTTP metrics synchronization keeps concurrent load assertions
  exact without racing response delivery against handler-finalization accounting.
- Appliance services use bounded listen queues, configurable active-request and
  model-query limits, audited request-identified overload rejection, bounded TTL
  rate-limit state, per-connection deadlines, nonce-based CSP, explicitly drained
  daemon workers, readiness-aware signal handling, and finite in-flight draining.
- Semantic-provider retries share one end-to-end deadline, custom hung panels are
  capacity-bounded, configured-panel majorities fail closed, and cost/token limits
  are explicitly recorded as post-run release gates with unknown metering rejected.
- Fixed-bucket latency histograms make the documented p95 SLO computable; managed
  JSONL logs enforce private permissions, size rotation and retention cleanup,
  expose write failures without breaking completed requests, and rate-limit state
  fails closed under rotating-identity saturation.
- A three-stage candidate, protected-promotion, and publication workflow that
  binds the producer, package, evidence, artifact, revision, source digest, and tag.

### Known validation boundaries

- Semantic and pedagogical judgments require an operator-supplied model and
  qualified human review; no model, embeddings, or inference runtime is bundled.
- The PLCT contract has synthetic conformance coverage but awaits validation on a
  genuine Petlja-owned export and Petlja confirmation of identifier semantics.
- Multilingual accuracy, educational utility, penetration resistance, independent
  reproducibility, and target-school operations await external evidence.

[Unreleased]: https://github.com/milos-plavsic/eii-open-learning-observatory/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/milos-plavsic/eii-open-learning-observatory/releases/tag/v0.2.0
[0.1.0]: https://github.com/milos-plavsic/eii-open-learning-observatory/releases/tag/v0.1.0
