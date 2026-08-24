# Public claims and evidence register

Status terms:

- **Internally verified:** exercised by repository-controlled automated tests.
- **Prototype:** code exists but operational or educational utility is unproven.
- **Integration only:** the Observatory records and evaluates another system's
  output; it does not supply the external model or judgment.
- **Externally validated:** supported by an identified independent record. No
  claim currently has this status unless a linked record says otherwise.

| Public claim | Mechanism | Current evidence | Status | Missing external evidence |
|---|---|---|---|---|
| Canonical hashes detect decision-relevant mutation | RFC 8785 canonical JSON, recursively frozen values and SHA-256 binding | Conformance-edge, property, tamper and mutation tests | Internally verified | Independent cross-language reproduction/security review; VAL-011 |
| Evidence bundles preserve source provenance | Stable locators, block/release hashes, deterministic excerpts, sealed comparison plans, typed semantic graph checks and schemas | Positive/negative schema, omission, duplication, misquotation, relationship, model-run and projection tests | Internally verified | Consumer review on retained real artifacts; VAL-012 |
| Multilingual structural drift can be proposed | Structural extraction, concepts, one versioned selection/evidence scoring algorithm with hard translation-ID constraints, and allow-listed numeric/unit parsing | Labeled golden corpus, explicit false-positive labels, six-language authored fixture, and property-based number-plus-translated-word fuzzing | Prototype | Human-labeled real-course benchmark; commitment VAL-001 |
| Semantic equivalence can be proposed | OpenAI-compatible evaluator with prompt/input/output provenance, configurable confidence/agreement/dissent/unanimity gates, and multi-evaluator consensus preserving every member run plus whole-decision and property-level signals | Mocked, replay, policy-gate, abstention, dissent-monotonicity and disagreement tests | Integration only | Frozen-model human evaluation, repeatability and language-specific calibration; VAL-002 |
| Curriculum contradictions and misconceptions can be proposed | Operator-supplied model and cited passages | Synthetic tests | Integration only | Subject-expert validity study; VAL-003 |
| Tutor properties can be packaged into a safety case | Replay/live execution, citation-membership and lexical uncertainty smoke checks, retrieved context and configured gates | Synthetic suites, six-language marker cases, and integrity tests | Internally verified packaging; unvalidated suitability | Citation entailment, refusal semantics, school/age/domain review and outcome study; VAL-004 |
| Classroom signals can be aggregated without raw conversation retention | Input rejection, key epochs, retention, bounded contributions, optional fixed public cell universe, pre-spend release authorization, secure Laplace count noise, persistent basic-composition budget, clone lineage binding, snapshot-bound noise memoization and exact-artifact hash-chained ledger | Privacy-boundary, fixed-universe selection, independent-connection budget race, shared-store concurrency, clone-detection, memoization, artifact-tamper and persistence tests | Prototype; fixed-universe mode provides an internally verified end-to-end central-DP mechanism, while compatibility threshold mode remains explicitly partial | Independent privacy review, deployment assessment and utility pilot; commitment VAL-005 |
| Offline packages detect unauthorized modification | Ed25519 signatures, startup known-vector self-test and fail-closed activation | Real OpenSSL, behavioral self-test, corruption and end-to-end rotation tests | Internally verified | Independent security assessment; VAL-006 |
| PLCT exports can be consumed | Proposed schema, adapter and conformance command | Synthetic PLCT fixture | Prototype | Genuine Petlja export and signed attestation; VAL-007 |
| Deterministic baseline retrieval can be measured | BM25/concept retrieval interface with recall@k and MRR plus down-weighted, phrase-aware glossary expansion | Synthetic monolingual and glossary-covered cross-language fixtures | Prototype | Human-labeled multilingual retrieval benchmark; VAL-008 |
| Package is portable on declared Python/OS combinations | Wheel/sdist and clean-install workflows | Merged-main CI on Linux, macOS and Windows, including native cryptographic operations; exact run recorded in `verification.md` | Internally verified on declared CI platforms | Independent clean-room reproduction; VAL-013 |

The numeric `confidence` fields in evidence are deterministic heuristic or
evaluator self-report signals. Consensus records separately preserve structural
agreement, winning-side mean confidence, and dissenting-side mean confidence;
they are never multiplied into a manufactured aggregate. They are not calibrated probabilities. A release
may publish probabilistic interpretations only after attaching a representative,
language-specific calibration study.

The register must be updated in the same pull request as any material feature or
public claim. “Implemented” never substitutes for empirical accuracy,
independent validation, certification, or production approval.

## Known engineering debt

| Item | Current gate | Required closure evidence |
|---|---|---|
| Oversized appliance and CLI orchestration | **Closed internally:** appliance routing/handler groups, trust operations, Weather/appliance/learning/review/trust/operations CLI command and parser groups have separate modules | CI fails on both line and AST-statement limits; full compatibility and coverage suites are required |

All Prototype, Integration-only, and external-evidence gaps are mapped to named,
owned closure commitments in [`validation-commitments.md`](validation-commitments.md).
