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
| Canonical hashes detect decision-relevant mutation | RFC 8785 canonical JSON, recursively frozen values and SHA-256 binding | Conformance-edge, property, tamper and mutation tests | Internally verified | Independent cross-language reproduction/security review |
| Evidence bundles preserve source provenance | Stable locators, block/release hashes, deterministic excerpts, sealed comparison plans, typed semantic graph checks and schemas | Positive/negative schema, omission, duplication, misquotation, relationship, model-run and projection tests | Internally verified | Consumer review on retained real artifacts |
| Multilingual structural drift can be proposed | Structural extraction, concepts, heuristic alignment, and allow-listed numeric/unit parsing | Six-language authored fixture plus translated-noun and genuine-unit regression cases | Prototype | Human-labeled real-course benchmark |
| Semantic equivalence can be proposed | OpenAI-compatible evaluator with prompt/input/output provenance, configurable abstention threshold, and multi-evaluator consensus preserving every member run | Mocked, replay, abstention and disagreement tests | Integration only | Frozen-model human evaluation, repeatability and language-specific calibration |
| Curriculum contradictions and misconceptions can be proposed | Operator-supplied model and cited passages | Synthetic tests | Integration only | Subject-expert validity study |
| Tutor properties can be packaged into a safety case | Replay/live execution, citation-membership and lexical uncertainty smoke checks, retrieved context and configured gates | Synthetic suites, six-language marker cases, and integrity tests | Internally verified packaging; unvalidated suitability | Citation entailment, refusal semantics, school/age/domain review and outcome study |
| Classroom signals can be aggregated without raw conversation retention | Input rejection, cell/day pseudonyms, key epochs, retention, cohort thresholds, fixed query partition and hash-chained export ledger | Privacy-boundary and persistence tests | Prototype; not anonymous or differentially private | Deployment privacy assessment and utility pilot |
| Offline packages detect unauthorized modification | Ed25519 signatures and fail-closed activation | Real OpenSSL, corruption and rotation tests | Internally verified | Independent security assessment |
| PLCT exports can be consumed | Proposed schema, adapter and conformance command | Synthetic PLCT fixture | Prototype | Genuine Petlja export and signed attestation |
| Deterministic baseline retrieval can be measured | BM25/concept retrieval interface with recall@k and MRR | Synthetic fixtures | Prototype | Human-labeled multilingual retrieval benchmark |
| Package is portable on declared Python/OS combinations | Wheel/sdist and clean-install workflows | Local 0.1.0 Linux verification plus defined multi-OS CI workflows | Internally verified on Linux | First public CI run, native macOS/Windows crypto execution and independent clean-room reproduction |

The numeric `confidence` fields in evidence are deterministic heuristic or
evaluator decision signals. They are not calibrated probabilities. A release
may publish probabilistic interpretations only after attaching a representative,
language-specific calibration study.

The register must be updated in the same pull request as any material feature or
public claim. “Implemented” never substitutes for empirical accuracy,
independent validation, certification, or production approval.

## Known engineering debt

| Item | Current gate | Required closure evidence |
|---|---|---|
| Oversized orchestration modules | Safety verification/signing is now separately owned; strict `mypy`, Ruff and tests constrain remaining debt | Split CLI dispatch, parser construction and HTTP handler factories into smaller owned modules without compatibility regressions |
