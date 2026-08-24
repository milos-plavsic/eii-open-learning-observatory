# External validation commitments

These commitments prevent provisional labels from becoming permanent caveats.
“Owner” identifies responsibility for arranging evidence, not permission to
self-certify the result. Target dates are planning targets and do not change a
claim’s status.

| ID | Claim boundary | Accountable owner | Plan and closure artifact | Target |
|---|---|---|---|---|
| [VAL-001](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/6) | Multilingual structural drift | Dr Miloš Plavšić / EII; independent language leads required | Freeze a licensed real-course corpus, double-label positive and negative cases, publish adjudication and precision/recall by language | 2026 Q4 |
| [VAL-002](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/5) | Semantic equivalence | EII research lead; external bilingual reviewers required | Frozen model/configuration study with repeat runs, human labels, disagreement analysis and language-specific calibration report | 2027 Q1 |
| [VAL-003](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/11) | Curriculum contradictions and misconceptions | EII research lead; subject experts required | Subject-specific validity study reporting false positives, false negatives, abstentions and reviewer agreement | 2027 Q1 |
| [VAL-004](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/4) | Tutor suitability | EII safety lead; school/age/domain reviewers required | Citation-entailment, refusal-semantics and pedagogical review plus bounded outcome pilot; no certification claim | 2027 Q2 |
| [VAL-005](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/8) | Classroom Weather privacy and utility | EII privacy owner; independent DP reviewer required | Review fixed-universe adjacency/sensitivity proof, deployment DPIA, clone procedure and teacher-facing utility pilot | Before learner-data pilot |
| [VAL-006](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/9) | Offline package security | EII security owner; independent assessor required | Third-party cryptographic, key-management and appliance threat review with public or redacted findings linked from `SECURITY.md` | Before production pilot |
| [VAL-007](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/12) | PLCT interoperability | EII integration owner; Petlja maintainer required | Genuine licensed export, conformance report and Petlja-controlled signed attestation | Before Petlja compatibility claim |
| [VAL-008](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/7) | Retrieval quality | EII evaluation owner; independent relevance labelers required | Frozen multilingual query corpus with recall@k, MRR, nDCG, glossary ablation and confidence intervals | 2027 Q1 |
| [VAL-009](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/10) | Documentation comprehension | EII documentation owner; outside platform reader required | Cold-read protocol, issue log, revisions and reviewer disposition report | 2026 Q4 |
| [VAL-010](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/13) | Release bus factor | EII governance body | Name a second maintainer, register an independent key, document succession/escrow and require two distinct approvals | Before v1.0 |
| [VAL-011](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/14) | Canonical-hash interoperability | EII security/evidence owner; independent implementer required | Reproduce canonicalization and representative hashes in a separately administered implementation across at least two language/runtime stacks; publish signed mutation and discrepancy results tied to the reviewed revision | Before production or certification claims |
| [VAL-012](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/15) | Retained provenance usability | EII evidence owner; independent archive, publisher or platform consumer required | Reconstruct sampled claims, passages, versions, relationships, model runs and decisions from retained real-course artifacts; publish protocol, issue disposition and attributable review record | Before production-grade provenance interoperability claims |
| [VAL-013](https://github.com/milos-plavsic/eii-open-learning-observatory/issues/16) | Portability and independent reproducibility | EII release owner; separately administered clean-room rebuilder required | Exercise supported Linux/macOS/Windows installation and real Ed25519 operations, independently rebuild from the published source digest, compare artifacts and publish signed receipts plus toolchain details | Before v1.0 or production portability claims |

Progress must be recorded as evidence links. A target date, internal test, issue
closure, or owner assertion alone cannot change a claim to externally validated.
