# Verification record — 2026-08-24

This is an append-only evidence ledger for the unreleased `0.3.0.dev0` development
line, not a claim that the last row verifies every future edit. The latest recorded
merged revision is
[`4d157cf`](https://github.com/milos-plavsic/eii-open-learning-observatory/commit/4d157cf6a49c6e00ed97fad2b76506fb3ab565da),
verified by [merged-main CI run 32748245307](https://github.com/milos-plavsic/eii-open-learning-observatory/actions/runs/32748245307)
and [nightly assurance run 32748264181](https://github.com/milos-plavsic/eii-open-learning-observatory/actions/runs/32748264181).
For a newer commit, its required GitHub commit checks are authoritative until a
later immutable run is added to this ledger; an older run is never evidence for a
newer revision. These are EII-controlled results, not independent reproduction,
certification, Petlja endorsement, or production approval. Published artifacts
must carry immutable checksums and signed release evidence.

## Current evidence

| Gate | Observed result |
|---|---|
| Warning-as-error unit/integration suite | Recorded revision: 272 tests passed on Python 3.11, 3.12, 3.13 and 3.14 |
| Coverage | Recorded revision: 6,670 statements and 2,062 branches at 100%, with 39 declared non-executable protocol and opposite-platform lock lines excluded |
| Lint and formatting | Expanded Ruff rules and formatter passed for `src`, `tests`, and `tools` |
| Static typing | Repository-wide strict `mypy` passed for 97 source files without module exemptions or ignored missing imports |
| Critical mutation probes | Twenty-four mutations spanning cryptography, persistence, PLCT conformance, release/SBOM evidence, scoped safety decisions, replay text integrity, privacy bounds/differencing, model transport, retrieval, split/merge and scoped alignment, semantic abstention, status projection, canonical quotation, snapshot signing, incomplete metering, configured-panel denominators, consensus consistency, ledger-key binding and uncertainty matching were killed |
| Flakiness hunter | Nightly run 32748264181 completed twenty shuffled 272-test full-suite passes against `4d157cf` |
| Browser/accessibility | Real Chromium smoke and Axe scan completed with zero detected violations |
| Security/dependencies | Bandit medium/high and five EII-specific Semgrep rules passed with zero blocking findings; `pip-audit` reported no known vulnerabilities, `spdx-tools` validates the SPDX 2.3 document in CI, and scheduled generic plus domain-specific rescans are configured |
| Artifact reproducibility | Two fixed-epoch wheels and normalized source distributions compared byte-for-byte equal |
| Clean source binding | Automated tests prove dirty-tree rejection and commit/archive binding; candidate generation requires a clean committed tree |
| Version binding | The published 0.2.0 artifacts remain bound to `v0.2.0`; current unreleased runtime, evidence producer and package metadata report `0.3.0.dev0` from one source of truth |
| Supported interpreters | Merged-main CI passed Python 3.11, 3.12, 3.13 and 3.14 and exercised real Ed25519 operations on Linux, macOS and Windows |
| Clean installation | The built wheel, `defusedxml`, and `rfc8785` installed into a new `uv` virtual environment; the wheel rebuilt from the sdist, and `eii --version` and `eii --help` succeeded |

## Commands

```bash
uv sync --extra dev
uv run ruff check src tests tools
uv run ruff format --check src tests tools
uv run mypy
uv run python tools/maintainability_gate.py
uv run coverage erase
PYTHONWARNINGS=error uv run coverage run -m unittest discover -s tests -p 'test_*.py'
uv run coverage report
uv run python tests/mutation_probe.py
SOURCE_DATE_EPOCH=1700000000 uv run python -m build --sdist --wheel --outdir DIST
PYTHONPATH=src uv run python tools/release_preflight.py --version 0.3.0.dev0 DIST/*.whl DIST/*.tar.gz
```

The release-candidate workflow repeats the full CI suite before producing
downloadable, unpublished artifacts. A release may be tagged only after that
workflow succeeds and the exact candidate bytes are reviewed.

## Evidence still required outside this repository

- A successful release-candidate, two-person promotion and publication run for the
  eventual 0.3.0 release commit.
- Independent clean-room reproduction and security assessment.
- A Petlja-confirmed export and signed conformance attestation.
- Human-labeled multilingual and educational-validity benchmarks.
- Target-hardware load, restore, disk-full, and power-loss exercises.
- Pilot SLO, privacy assessment, and procurement/certification decisions.

The claims/evidence register is authoritative for the boundary between
internally verified mechanisms and externally validated outcomes.
