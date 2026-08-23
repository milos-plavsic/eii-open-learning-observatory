# Architecture decisions and ownership

## ADR-001: canonical model, replaceable adapters

Status: accepted. Source platforms are untrusted import boundaries. Analyses
consume `CourseRelease`, never PLCT runtime objects. Adapter owners maintain
versioned fixtures and conformance; changes to stable IDs or hashes require a
schema/version decision and compatibility report.

## ADR-002: evidence over scores

Status: accepted. Findings cite immutable block hashes and source locators.
Canonical evidence IDs bind releases, findings, reviews, model runs and metadata.
Human decisions remain distinct. Analysis owners may add findings but cannot
silently change source content or turn confidence into approval.

## ADR-003: dependency-minimal runtime

Status: accepted. Core operation has two pinned third-party Python runtime
dependencies: `defusedxml` for defensive XML parsing and `rfc8785` for canonical
JSON. No model, embedding stack, web framework, database driver, or cryptographic
Python package is bundled. Ed25519 operations require and validate an OpenSSL 3-or-newer
system executable. Schema, browser, mutation, lint/type/security and build
tools are optional, pinned development dependencies. Any new runtime dependency
requires a threat, licence, offline-size, maintenance and fallback decision.

## ADR-004: separate trust roots

Status: accepted. Publisher, safety evaluator and Petlja organizational
attestation keys represent different claims. `crypto.py` owns Ed25519 execution;
callers own claim-specific canonical payloads and key policy. Package creation and
installation are Ed25519-only; symmetric-key/HMAC appliance packages are rejected.

## ADR-005: privacy-minimized services

Status: accepted. HTTP observability records bounded operational metadata, not
request bodies or identities. Weather analytics refuses text/direct identifiers
and applies retention/contributor thresholds before export. Any new telemetry
field requires a privacy review and schema update.

## Module ownership

- `domain.py`, `evidence.py`, `schemas/`: evidence-contract maintainer.
- `adapters/`, `plct_conformance.py`: integration maintainer plus upstream reviewer.
- `alignment.py`, `babelbridge.py`, `babel_semantic.py`, `semantic_policy.py`,
  `semantics.py`, `curriculum.py`, `safety.py`: educational-evaluation maintainer.
- `persistence.py`, `weather.py`, `study.py`: data/privacy maintainer.
- `appliance*.py`, `service.py`, `crypto.py`, `secureio.py`: operations/security maintainer.
- `supply_chain.py`, CI and release runbooks: release maintainer.
- `cli_parser.py`, `cli.py`: interface maintainer.

Public schemas, CLI command/option names and exit meanings, database versions,
package manifests, canonical hashes and adapter formats are compatibility
surfaces. Deprecate for one minor release where safe; never reinterpret signed
bytes. Security corrections may fail closed immediately and must be called out
in release notes.
