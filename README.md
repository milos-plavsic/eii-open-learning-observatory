# EII Open Learning Observatory

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Current version: **0.1.0**, the first public alpha of the software. The canonical
repository is [eii-open-learning-observatory](https://github.com/milos-plavsic/eii-open-learning-observatory).

An independent evidence and quality layer for open digital education. The
Observatory ingests course repositories through replaceable adapters and
produces versioned, reviewable evidence for:

- **BabelBridge** — multilingual alignment and semantic quality assurance.
- **Curriculum MRI** — curriculum coverage and course-quality auditing.
- **Tutor Safety Case** — reproducible evidence for educational assistants.
- **Classroom Weather Map** — privacy-preserving aggregate learning signals.
- **School-in-a-Box** — private, offline course and model deployment.

The project is intentionally independent of PLCT. PLCT is one adapter; the
canonical model and evidence formats remain stable if PLCT changes.

> **0.1.0 alpha and validation boundary:** The deterministic core performs extraction,
> structural comparison, provenance hashing, schema validation, packaging, and
> report generation without an ML runtime. Semantic judgments—including
> contradiction, misconception, weak-example, generated-question, difficulty,
> and pedagogical-equivalence analysis—require an operator-supplied
> OpenAI-compatible model. All findings are hypotheses for qualified human
> review. The project has not yet been independently validated on a genuine
> Petlja export or certified for production educational use.

It can run standalone or federate signed evidence into an institution-owned
governance system. See [the federation and trust workflow](docs/federation.md).
Prototype importers are available for the proposed PLCT contract, Markdown
repositories, H5P, Open edX OLX, Moodle backups, Kolibri channel snapshots,
MediaWiki revisions and learning graphs. Except for generic Markdown input,
their current conformance evidence uses repository-authored fixtures; platform
owners have not certified compatibility.

## Capability boundaries

| Capability | Deterministic core | External model | Human confirmation |
|---|---:|---:|---:|
| Content extraction, stable locators, hashes and schemas | Yes | No | Audit recommended |
| Structural/missing-unit and exact-value drift checks | Yes | No | Required before editorial action |
| Glossary and explicit terminology checks | Yes | No | Required for linguistic interpretation |
| Contradiction, misconception and weak-example analysis | Orchestration and evidence capture | Required | Required |
| Pedagogical equivalence and difficulty comparison | Orchestration and evidence capture | Usually required | Required |
| Tutor replay, citation and configured property checks | Yes | Optional for live execution | Required for release suitability |
| Safety-case and signed evidence packaging | Yes | Evaluator-dependent | Required for release decisions |
| PLCT compatibility | Proposed contract and synthetic fixture | No | Petlja validation outstanding |

See the [claims and evidence register](docs/claims-evidence-register.md) for the
evidence supporting each public claim and the external gates still outstanding.
The non-scored [requirements traceability index](docs/requirements-traceability.md)
maps implementation paths to internal tests and external closure evidence.

## Installation and development

Requires Python 3.11 or newer. Signed-evidence and appliance operations additionally
require OpenSSL 3 or newer with Ed25519 `pkeyutl` support; the runtime checks this requirement
and fails closed. The two core Python runtime dependencies are `defusedxml`
for defensive XML parsing and `rfc8785` for standards-based canonical evidence;
no embedding library, model weights, or ML runtime is bundled.

```bash
python -m pip install -e '.[test]'
python -m unittest discover -s tests
python -m eii --help
```

Model-assisted features require an OpenAI-compatible endpoint selected by the
operator. This may be a hosted service or a local server such as vLLM; the
Observatory does not bundle a model, embeddings, or an inference runtime.
Remote endpoints must use HTTPS; plain HTTP is accepted only for an explicit
loopback endpoint.

`eii audit --semantic-threshold NUMBER` records the uncalibrated decision
threshold in bundle metadata. For consensus, provide
`--semantic-evaluator-config policy.json` containing an odd panel of at least
three distinct evaluator configurations and `"schema_version": "1.0"`.
The public, secret-free configuration, its hash, quorum, deadline, every member
judgment, provider failure, abstention, passing result, model run, and aggregation
decision are retained in sealed evidence. API keys are read only from named
environment variables and are never included. Distinct configuration is not a
claim of organizational or model-family independence; operators must document
those dimensions separately. Naming `api_key_env` is a fail-closed declaration:
the audit is rejected before network access if that variable is absent or empty.
Operator and model-family values are explicitly *declared* metadata, not verified
independence claims.

```json
{
  "schema_version": "1.0",
  "quorum": 2,
  "overall_timeout_seconds": 120,
  "max_total_cost": 1.0,
  "max_total_tokens": 12000,
  "max_outstanding_panels": 1,
  "minimum_declared_operators": 2,
  "minimum_declared_model_families": 2,
  "evaluators": [
    {"base_url": "https://one.example/v1", "model": "model-a", "api_key_env": "ONE_KEY"},
    {"base_url": "https://two.example/v1", "model": "model-b", "api_key_env": "TWO_KEY"},
    {"base_url": "https://three.example/v1", "model": "model-c", "api_key_env": "THREE_KEY"}
  ]
}
```

Cost and token limits are fail-closed, post-response release gates: they prevent
an over-budget result from becoming an accepted semantic decision, but cannot
prevent a provider from incurring the cost before reporting usage. Missing usage
or cost data—including any failed or timed-out launched panel member—fails a
configured gate. The overall deadline bounds connection setup, incremental
response reads, and retries for the bundled HTTP transport; custom comparator implementations
must honor the same timeout contract. `--max-semantic-comparisons` is the
preflight control that rejects an oversized semantic audit before any model call.

`eii validate REPORT_DIRECTORY` verifies `evidence.json`, the separately useful
alignment/status JSON files, and the report's embedded data against one sealed
artifact manifest. A sealed semantic comparison plan must have exactly one result
per planned release pair. Successful semantic checks are evidence records; a report
with no semantic findings must not be interpreted as proof that no checks ran.
`eii audit-sign REPORT_DIRECTORY --signer-id ID ...` takes and validates one
immutable file snapshot, then creates an Ed25519-authenticated manifest binding
signer identity, purpose, time, bundle and every report file. `eii audit-verify`
checks integrity and authentication; adding `--authorization-policy POLICY` also
checks signer, key, purpose and validity interval against an explicit trust
policy. Verification rejects signing times more than five minutes ahead of its
verification clock and bounds individual and aggregate report input sizes. A
content hash detects mutation; only a signature associates the artifact
with a key holder, and only a policy authorizes that holder for a purpose.

The bundled retriever is a deterministic, cached BM25/concept baseline with
Unicode/CJK tokenization and recall@k, precision@k, hit-rate, mean-reciprocal-rank,
and nDCG evaluation support. It is not an embedding retriever;
deployments claiming multilingual retrieval quality must provide and publish a
human-labeled retrieval benchmark.

Core workflows:

```bash
# Cross-language evidence report
python -m eii audit ./course-en ./course-sr --output ./report

# Curriculum coverage and accessibility audit
python -m eii mri ./course --spec curriculum.json --output ./mri
# Add --model-base-url http://127.0.0.1:8000/v1 --model local-model
# for contradiction, misconception, weak-example, and generated-question checks.

# Claim-based tutor release evidence from a recorded run
python -m eii safety-case ./course --suite safety-suite.json \
  --responses replay.json --prompt-version tutor-v1 --output safety-case.json

# The outcome is configured_gates_passed or configured_gates_failed.
# Human approvals are separate signed records; operator trust is by key fingerprint.
# Derive subject_hash from the exact preliminary case, then sign the review.
python -m eii safety-review-init safety-case.json --fixture-id age-en \
  --reviewer reviewer-id --decision approve --rationale "Reviewed against rubric" \
  --output unsigned-review.json
python -m eii safety-review-sign unsigned-review.json \
  --private-key-file reviewer-private.pem --public-key-file reviewer-public.pem \
  --output signed-review.json

# Locally aggregate minimized classroom signals
python -m eii weather-key-generate --output weather.key
python -m eii weather events.json --database weather.sqlite \
  --secret-file weather.key --ledger-key-file weather-ledger.key \
  --output weather-map.json

# Offline appliance lifecycle
python -m eii appliance-check

# Frozen, randomized and blinded human-review assignments
python -m eii review-study-init report/evidence.json --database review.sqlite \
  --study-id pilot-v1 --reviewers reviewer-a,reviewer-b --seed-file review.seed
python -m eii review-study-next --database review.sqlite --study-id pilot-v1 \
  --reviewer reviewer-a --output next-assignment.json
python -m eii review-study-serve --database review.sqlite --study-id pilot-v1
```

For a safety case, “configured gates passed” means only that the declared,
reproducible checks passed. It is not a claim that a tutor is safe,
educationally effective, certified, or approved by EII, a school, or Petlja.

See [docs/architecture.md](docs/architecture.md) and
[docs/roadmap.md](docs/roadmap.md). Database migration, backup and restore
procedures are in [docs/database-operations.md](docs/database-operations.md).
Production operators should also read [docs/observability.md](docs/observability.md),
[docs/migrations-and-upgrades.md](docs/migrations-and-upgrades.md),
[docs/key-management.md](docs/key-management.md), and
[docs/incident-response.md](docs/incident-response.md). Security reports follow
[SECURITY.md](SECURITY.md); compatibility support follows [SUPPORT.md](SUPPORT.md).

Formal interchange schemas are under [`schemas/`](schemas/). Course-content
licenses must be verified separately from this software's MIT license.
Canonical `$id` artifacts are generated under [`public/schemas/`](public/schemas/);
deployment requirements are documented in
[`docs/schema-publication.md`](docs/schema-publication.md).

## Relationship to Petlja and licensing

The Observatory was developed independently by the Education Improvement
Institute. Its initial PLCT adapter and interoperability work were informed by
Petlja's open-source [PLCT Server](https://github.com/Petlja/PLCT-Server), which
is distributed under the MIT License.

Petlja has not yet reviewed, endorsed, sponsored, or certified this software or
its proposed PLCT interoperability contract. The Petlja and PLCT names identify
the intended interoperability context only.

The Observatory software is independently distributed under the
[MIT License](LICENSE). Course repositories and educational content may have
different licences and must be assessed separately before redistribution,
translation, or commercial use.

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md), report
security issues according to [SECURITY.md](SECURITY.md), and use synthetic or
properly authorized educational data in all public examples and reports.
