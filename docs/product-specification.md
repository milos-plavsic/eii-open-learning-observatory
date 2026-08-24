# Product specification

## Users and decisions

The first operator is a multilingual course editor or quality reviewer. Their
decision is whether a course and its assistant are ready for release. Authors
and translators resolve findings; teachers consume approved reports and
aggregate classroom signals; learners benefit from corrected material and the
grounded tutor without operating the quality system.

## Platform acceptance criteria

| Capability | Required observable result |
|---|---|
| BabelBridge | Align language units, expose a versioned non-probabilistic score/method, detect structural and literal drift, enforce terminology, accept semantic comparator judgments, retain reviewer decisions. |
| Curriculum MRI | Map objectives through concepts and prerequisites to evidence and assessments; report gaps with source evidence; emit HTML, JSON and prioritized backlog. |
| Tutor Safety Case | Replay exact questions and retrieval, evaluate explicit claims, preserve configuration and hashes, apply release gates and compare regressions. |
| Weather Map | Reject conversation/identity fields, aggregate locally, suppress small cohorts, expire events and explain every disclosed metric. |
| School-in-a-Box | Assess hardware, verify and stage signed releases, atomically activate, serve courses locally and ground a tutor through loopback-only vLLM. |

## Out-of-scope automatic actions

The Observatory never edits a source course, approves a machine finding on
behalf of an editor, assigns risk to an individual learner, or uploads classroom
data. A graphical authoring editor and model training remain deployment
extensions rather than hidden assumptions in the core. The implemented
public-key layer provides Ed25519 signing, rotation and verification primitives;
organizational identity proof, hardware custody and certificate policy remain
the deployer's responsibility.

## Course-content licensing gate

Every release has a separate `content_license` field. A missing value remains
visible in evidence and must block redistribution operationally. The MIT license
in this repository applies only to Observatory software.
