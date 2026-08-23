# Architecture and invariants

Decision rationale, module ownership and compatibility policy are recorded in
`docs/architecture-decisions.md`.

## Boundary

Source systems are untrusted inputs behind adapters. They emit the canonical
`CourseRelease` model; analysis engines consume only that model. Reports refer
to immutable content hashes and stable source locators, never database row IDs.

```text
repositories / PLCT / other LMS
              | adapters
              v
       canonical CourseRelease
              |
     +--------+----------+-------------+
     |                   |             |
BabelBridge       Curriculum MRI   Tutor Safety Case
     +--------+----------+-------------+
              v
       EvidenceBundle JSON
              |
       HTML / CI / offline appliance
```

Classroom Weather Map receives minimized events, not learner conversations.
School-in-a-Box packages the same canonical releases and evidence bundles.

## Non-negotiable invariants

1. Every finding points to precise source evidence or explicitly records that
   evidence is absent.
2. Model-produced judgments record provider, model, parameters, prompt version,
   inputs and output hashes.
3. Findings are proposals. No source course is modified automatically.
4. Human decisions are append-only and distinct from machine judgments.
5. Raw learner conversations and direct identifiers are rejected by analytics.
6. Aggregates below a configurable cohort threshold are never disclosed.
7. Equivalent runs over identical inputs are addressable by the same hashes.
8. Course-content licensing is recorded per release; software licensing does
   not imply permission to redistribute content.
9. Canonical hashes bind identifiers, hierarchy, order, provenance, semantics,
   release identity, version, language, licence, and metadata.
10. Safety release decisions are derived and independently recomputed; serialized
    pass/fail flags are never trusted as authority.
11. The producer version has one source of truth and must match package metadata,
    CLI output, evidence bundles, wheel/sdist metadata, release evidence, and the
    signed release tag. Schema versions remain independent compatibility fields.
12. Every requested semantic evaluation is declared in a sealed comparison plan
    and has exactly one explicit equivalent, drift, or abstained record;
    successful evaluations are never represented merely by the absence of a
    finding.
13. Alignment and translation-status exports are projections of records embedded
    in the sealed evidence bundle. Complete audit-directory validation rejects a
    substituted projection or a report embedding a different bundle.
14. Semantic-evaluation records are typed and versioned, reference only canonical
    constituent course blocks, and bind the exact recorded model run by content ID;
    synthetic split/merge comparison text can never masquerade as source evidence.
15. Evidence excerpts are deterministic projections of referenced block text.
    Bundle validation rejects misquotation, unknown relationships, evidence outside
    a relationship, member judgments inconsistent with their model run, and
    semantic outcomes inconsistent with finding projections.
16. Declared translation identity is authoritative across one-to-one, split,
    merge and many-to-many relationships. Differently scoped identities cannot be
    rejoined by heuristic title or order matching.
17. Semantic records reference a deterministic alignment-relationship hash, not
    a reusable concept label. Multiple lessons may teach the same concept without
    collapsing their evidence or evaluator decisions into one relationship.

Semantic panels use conservative dual agreement: a strict majority must approve
or reject the whole judgment and every required property must independently
receive a strict-majority result. A tied/incomplete vote, a member abstention, or
a conflict between whole and property votes makes the panel abstain. Provider
failure is recorded; a strict configured quorum is required. “Distinct configuration”
does not establish model, provider, training-data, or organizational independence.
Configured cost/token limits are post-run acceptance gates, not provider spending
limits. Missing metering or a failed launched member fails closed. A configured-panel majority remains the
decision denominator when members fail, so quorum cannot turn a minority of the
declared panel into a positive decision.

## Version identities

- **Producer version:** the Observatory software version in `eii._version`.
- **Evidence schema version:** the compatibility version of serialized evidence.
- **Database schema version:** the migration level for a local persistent store.
- **Adapter contract version:** the external interchange contract, such as PLCT v1.
- **Course version:** the source platform's course/repository release identity.

These identities must not be substituted for one another. Producer-version
changes alter provenance; schema versions change only when their respective
compatibility contract changes.

Evidence schema 2.0 uses RFC 8785 JSON Canonicalization Scheme for every
content hash and signature payload. Hashed metadata is recursively copied and
frozen at construction. The loader accepts schema 1.0 only when its stored
hashes also verify under RFC 8785; incompatible legacy evidence must remain with
its original verifier rather than being silently re-signed.

Tutor Safety Case schema 3.0 replaces ambiguous `approved`/`rejected` outcomes
with `configured_gates_passed`/`configured_gates_failed` and binds exact
retrieved text, IDs, hashes, replayable model requests, derived gates and outcome,
evaluator version and evaluator-ruleset hash. Human reviews are individually
Ed25519-signed and authorized against an operator-supplied reviewer-key policy.
Validation, signer authentication and release authorization are independent;
failed cases remain valid signable evidence. Weather Map export schema 2 and
database schema 5 add count coarsening, cell/day scoped pseudonyms, explicit
key-epoch rotation, an immutable export-partition strategy and a keyed,
append-only export ledger, plus course-partitioned export-interval disclosure
control. These are deliberate breaking changes;
older artifacts must remain paired with their original verifier.

## Stable identifiers

Identifiers are namespaced strings such as `plct:course-key` and
`repo:relative/path#anchor`. Language-independent concepts use reverse-DNS-like
keys such as `programming.loop.for.range`. IDs supplied by a source are retained;
derived IDs are deterministic hashes of normalized source location and content.
