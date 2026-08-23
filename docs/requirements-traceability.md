# Requirements and evidence traceability

This is a non-scored engineering index. `Implemented` means a software path
exists; `internally verified` means repository tests exercise it; neither term
means externally validated, certified, or production-approved. The public
claims register remains authoritative for outcome claims.

| Requirement | Implementation | Internal verification | External closure | State |
|---|---|---|---|---|
| Canonical, tamper-evident evidence | `domain.py`, `evidence.py`, JSON schemas | Canonicalization, mutation, schema and tamper tests | Independent consumer reproduction | Internally verified mechanism |
| Multilingual structural alignment | `babelbridge.py`, cardinality-bearing `Alignment` | Split, merge, insertion, literal and six-language tests | Human-labelled multilingual corpus | Prototype |
| Semantic comparison policy | `semantic_policy.py`, `semantics.py`, `babel_semantic.py` | Configuration, identity, abstention, consensus and mutation tests | Frozen evaluator benchmark and calibration | Integration only |
| Tutor evaluation packaging | `safety*.py`, safety-case schema | Replay, integrity, signature and multilingual smoke tests | Entailment, refusal and classroom suitability review | Internally verified packaging |
| Privacy-minimized classroom aggregation | `weather*.py`, SQLite migrations | Threshold, differencing, retention, recovery and concurrency tests | Deployment privacy/utility assessment | Prototype |
| Offline signed appliance | `appliance*.py`, `crypto.py`, `service.py` | Package, trust rotation, bounded HTTP, rollback and crypto tests | Target-hardware failure and capacity exercises | Prototype |
| Replaceable PLCT boundary | `adapters/plct.py`, conformance schemas and commands | Synthetic positive/negative fixtures | Petlja exporter, real QueryContext and attestation | Proposed contract |
| Reproducible release | supply-chain modules and GitHub workflows | Local multi-Python, clean-container, byte reproducibility and signature gates | Public CI and independent clean-room build | Internally verified on Linux |

Every material feature change must update this table, the claims register, its
tests, and any affected interchange schema in the same change. External closure
must cite a dated, independently controlled artifact; repository-authored
fixtures cannot satisfy it.
