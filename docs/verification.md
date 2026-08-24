# Release-candidate verification — 2026-08-24

This is a local verification record for the `0.2.0` source version. It is
not a GitHub CI result, independent reproduction, certification, Petlja
endorsement, or production approval. Published artifacts must carry their own
immutable checksums and signed release evidence.

## Current local evidence

| Gate | Observed result |
|---|---|
| Warning-as-error unit/integration suite | 255 tests passed |
| Coverage | 6,109 tracked statements and 1,924 branches at 100%, with 33 declared non-executable protocol and opposite-platform lock lines excluded |
| Lint and formatting | Expanded Ruff rules and formatter passed for `src`, `tests`, and `tools` |
| Static typing | Repository-wide strict `mypy` passed for 74 source files without module exemptions or ignored missing imports |
| Critical mutation probes | Twenty-four mutations spanning cryptography, persistence, PLCT conformance, release/SBOM evidence, scoped safety decisions, replay text integrity, privacy bounds/differencing, model transport, retrieval, split/merge and scoped alignment, semantic abstention, status projection, canonical quotation, snapshot signing, incomplete metering, configured-panel denominators, consensus consistency, ledger-key binding and uncertainty matching were killed |
| Browser/accessibility | Real Chromium smoke and Axe scan completed with zero detected violations |
| Security/dependencies | Bandit medium/high gate passed, `pip-audit` reported no known vulnerabilities, and `spdx-tools` independently validated the SPDX 2.3 document |
| Artifact reproducibility | Two fixed-epoch wheels and normalized source distributions compared byte-for-byte equal |
| Clean source binding | Automated tests prove dirty-tree rejection and commit/archive binding; candidate generation requires a clean committed tree |
| Version binding | Runtime, evidence producer, wheel metadata, source-distribution metadata, and requested candidate version all reported `0.2.0` |
| Supported interpreters | Python 3.14 passed locally; CI repeats the warning-as-error suite on 3.11, 3.12, 3.13, and 3.14 and exercises real Ed25519 operations on Linux, macOS, and Windows |
| Clean installation | The built wheel, `defusedxml`, and `rfc8785` installed into a new `uv` virtual environment; `eii --version` and `eii --help` succeeded |

## Commands

```bash
uv sync --extra dev
uv run ruff check src tests tools
uv run ruff format --check src tests tools
uv run mypy
uv run coverage erase
PYTHONWARNINGS=error uv run coverage run -m unittest discover -s tests -p 'test_*.py'
uv run coverage report
uv run python tests/mutation_probe.py
SOURCE_DATE_EPOCH=1700000000 uv run python -m build --sdist --wheel --outdir DIST
PYTHONPATH=src uv run python tools/release_preflight.py --version 0.2.0 DIST/*.whl DIST/*.tar.gz
```

The release-candidate workflow repeats the full CI suite before producing
downloadable, unpublished artifacts. A release may be tagged only after that
workflow succeeds and the exact candidate bytes are reviewed.

## Evidence still required outside this repository

- A successful GitHub run URL for the candidate commit.
- Independent clean-room reproduction and security assessment.
- A Petlja-confirmed export and signed conformance attestation.
- Human-labeled multilingual and educational-validity benchmarks.
- Target-hardware load, restore, disk-full, and power-loss exercises.
- Pilot SLO, privacy assessment, and procurement/certification decisions.

The claims/evidence register is authoritative for the boundary between
internally verified mechanisms and externally validated outcomes.
