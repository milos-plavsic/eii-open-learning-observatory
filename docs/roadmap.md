# Capability and validation roadmap

This roadmap distinguishes software availability from empirical validity.
“Implemented” means a code path and synthetic automated test exist. It does not
mean the educational judgment is accurate, useful, independently reproduced,
or approved by a platform owner.

| Area | Software state | Analytical mechanism | Validation state |
|---|---|---|---|
| Canonical model and provenance | Implemented | Deterministic | Internally tested |
| Repository and LMS adapters | Implemented adapters | Deterministic extraction | Synthetic fixtures only except generic repository input |
| PLCT adapter | Proposed contract implemented | Deterministic extraction/conformance | No Petlja-confirmed export yet |
| BabelBridge structural drift | Implemented with scope-authoritative one-to-one/split/merge/many-to-many relationships and review-status projection | Deterministic and heuristic candidate alignment | Authored multilingual fixture only |
| BabelBridge semantic equivalence | Integration implemented with abstention and optional quorum consensus across distinct configurations | Operator-supplied model(s) | Configuration diversity does not prove evaluator independence; no human-labeled accuracy or calibration benchmark |
| Curriculum objective/evidence coverage | Implemented | Deterministic mappings | Authored fixtures only |
| Contradiction, misconception and weak-example checks | Integration implemented | Operator-supplied model | No external educational-validity study |
| Tutor replay and configured gates | Implemented | Deterministic replay plus optional live model | No classroom-suitability validation |
| Retrieval | Deterministic BM25/concept baseline and evaluation API | No embeddings bundled | No human-labeled multilingual recall/MRR benchmark |
| Classroom Weather Map | Implemented | Local deterministic aggregation | No target-school privacy/utility pilot |
| School-in-a-Box lifecycle | Prototype implemented | Local service and cryptographic packaging | No target-hardware operational pilot |

## Version 0.1.0 software scope

Version `0.1.0` establishes the following release-governance and claims controls:

1. One canonical producer version bound to package metadata, CLI output,
   evidence bundles, artifacts, release evidence, and tag.
2. A release-candidate workflow that cannot publish and produces exact artifacts
   only after the complete quality suite succeeds.
3. Explicit deterministic/model/human boundaries in public documentation.
4. A public claims-evidence register and testing policy.
5. Expanded formatting, import, modernization, bug-risk, simplification, and
   Ruff-specific lint checks.

## Post-0.1.0 validation milestones

External validation remains separate from the `0.1.0` software release:

- Obtain a genuine Petlja-owned export and signed contract attestation.
- Run a frozen, blinded multilingual reviewer study with false positives,
  abstentions, disagreement, and reviewer time reported.
- Reproduce the release from a clean independent fork.
- Complete an independent security assessment.
- Run restore, load, network-loss, disk-loss, and power-loss exercises on target
  school hardware.

No missing external result may be replaced by an EII-authored fixture or score.
