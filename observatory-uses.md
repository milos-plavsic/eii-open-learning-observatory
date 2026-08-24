# How the EII Open Learning Observatory Can Be Used

The Observatory can become EII’s reusable “evidence production engine,” while Sentinel becomes the institutional governance and decision system around that evidence. That separation is strategically strong and already partly implemented.

The most important conclusion from inspecting both codebases is this:

> The Sentinel integration is substantially more than an idea, but it is not yet safe to describe as production-complete. Its architecture is right; several contract, trust, privacy, and review-lifecycle gaps must be closed before a real institutional pilot.

## 1. Use within EII Sentinel

### The correct division of responsibilities

The two products should remain separate:

| Observatory | EII Sentinel |
|---|---|
| Imports courses and learning resources | Registers institutions and providers |
| Normalizes content into canonical blocks | Owns users, roles, MFA, and tenant isolation |
| Runs BabelBridge and Curriculum MRI | Owns governance policies |
| Runs Tutor Safety Case evaluations | Owns release decisions |
| Produces findings and exact evidence | Owns human-review workflow |
| Signs evidence at its origin | Owns provider trust keys and revocation |
| Can operate locally or offline | Maintains institutional audit history |
| Avoids learner identity | Exports procurement and governance evidence |

This boundary is reflected in both `docs/federation.md` and Sentinel’s `docs/LEARNING_ASSURANCE.md`.

Sentinel should never import the Observatory’s Python internals. It should consume a public, versioned, signed interchange protocol.

### What is already implemented

Sentinel already has:

- Tenant-specific provider registration.
- One-time bearer tokens stored only as hashes.
- Ed25519 public-key registration and revocation.
- PostgreSQL-backed audit jobs.
- Signed evidence ingestion.
- Structural validation of bundles and evidence references.
- Immutable raw evidence-bundle storage.
- Projected findings for review.
- Human-review records.
- Release policies and decisions.
- Operational audit events.
- Tenant row-level security.
- An administrative Learning Assurance interface.
- Migration `0077_learning_assurance.sql`.

The Observatory already has:

- Signed federation-envelope creation and verification.
- HTTPS-only submission, except explicit loopback development.
- Redirect refusal to prevent credential forwarding.
- Provider and audit-run identifiers.
- Canonical evidence bundles.
- Precise source locators, hashes, findings, reviews, and model runs.
- Multiple source-platform adapters.
- Privacy-minimized analysis and offline operation.

Therefore, an end-to-end architectural path already exists:

```text
Institution requests audit in Sentinel
              ↓
PostgreSQL queue records immutable source reference
              ↓
Observatory worker claims the audit
              ↓
Provider adapter imports the named course release
              ↓
Requested analysis profiles execute
              ↓
Observatory seals and signs the evidence
              ↓
Sentinel authenticates provider and verifies signature
              ↓
Findings enter qualified human review
              ↓
Institution applies a versioned release policy
              ↓
Decision and rationale enter governance evidence pack
```

### Immediate Sentinel applications

#### A. Course-release gate

A school or EII administrator could require an assurance decision before making a course release available.

Example policy:

- Reject unsigned evidence.
- Reject confirmed critical findings.
- Require review of all high-severity findings.
- Require Tutor Safety Case gates to pass.
- Require all relevant language versions to be present.
- Record an explicit responsible human decision.

This can support internal release governance, but it must not be represented as certification.

#### B. Multilingual-equivalence dashboard

Sentinel can aggregate Observatory evidence by:

- Canonical course.
- Course version.
- Language.
- Finding type.
- Severity.
- Review status.
- Provider.
- Previous release.

The administrator could see:

- Which translations lag behind the canonical release.
- Which findings have been confirmed.
- Which differences are intentional localization.
- Which terminology issues recur.
- Whether the current release improved or regressed.
- Whether semantic evaluation ran, abstained, or failed.

The current page displays counts and a basic review queue. It needs deeper course/language drill-down to become truly useful.

#### C. Educational-AI governance

Tutor Safety Case evidence could feed Sentinel’s existing AI-governance and procurement capabilities.

Each assistant deployment should be represented as:

```text
Course release
+ retrieval configuration
+ model identity
+ model/provider configuration
+ system prompt version
+ safety-fixture version
+ retrieved passages
+ actual responses
+ evaluator records
+ human approvals
+ release decision
```

Sentinel could then answer:

- Which tutor configuration is approved for which course?
- Which languages were evaluated?
- What changed since the previous approval?
- Which limitations were accepted?
- When must the decision be reviewed?
- Has a signing key, model, course, or prompt changed since approval?

#### D. Institution-controlled external providers

Sentinel can register:

- EII-hosted Observatory workers.
- Foundation-hosted workers.
- Publisher-operated workers.
- School-local workers.
- Offline School-in-a-Box installations.

Each provider can have an independently managed trust key and authentication credential. This supports federation without making EII the custodian of every course repository.

#### E. Procurement evidence packs

Sentinel already generates governance and procurement evidence. Observatory records could form an educational-assurance annex containing:

- Course identity and version.
- Content licence status.
- Supported languages.
- Analysis profiles executed.
- Findings and dispositions.
- Tutor evaluation results.
- Human reviewers and rationales.
- Known limitations.
- Artifact hashes and signatures.
- Release decision and applicable policy.
- Regression comparison.

This is more defensible than a generic “AI safety score.”

#### F. Continuous monitoring

A scheduled Sentinel audit could run when:

- A course tag changes.
- A translation changes.
- A prompt changes.
- A model changes.
- A retrieval configuration changes.
- An evaluation suite changes.
- A provider key rotates.
- A previously resolved finding reappears.

Sentinel should compare releases rather than merely list bundles.

### Critical integration problems to solve

These are not theoretical refinements; several are material correctness issues.

#### 1. Human review currently does not reliably affect the policy decision

Sentinel stores the original signed bundle and also projects findings into database rows. A reviewer changes the database finding’s status, but `decideRelease()` evaluates the original immutable bundle payload.

That means a finding changed from `proposed` to `confirmed` in Sentinel may remain `proposed` inside the object evaluated by policy. A confirmed critical finding could consequently fail to trigger the intended rejection.

The proper model is:

```text
Immutable provider assertion
        +
Immutable institutional review records
        +
Versioned policy snapshot
        =
Institutional release decision
```

Sentinel must evaluate its current review ledger, not mutate or blindly reuse the provider assertion.

#### 2. Trust keys are not sufficiently scoped to providers during ingestion

The trusted-key lookup uses institution and fingerprint, but does not also require that the key belongs to the authenticated provider.

Within one institution, a key registered for Provider A could potentially authenticate a submission made using Provider B’s bearer credentials if the attacker controls both elements.

Verification must bind:

- Institution.
- Provider.
- Key.
- Envelope.
- Audit run.
- Expected source.
- Requested profiles.

#### 3. Canonical JSON is duplicated and not demonstrably equivalent

The Observatory uses RFC 8785 canonicalization. Sentinel has an independently written TypeScript canonicalizer using `localeCompare()` and `JSON.stringify()`.

This is dangerous around:

- Unicode key ordering.
- Numeric serialization.
- Negative zero.
- Exponent notation.
- Unpaired Unicode surrogates.
- Unsupported JavaScript values.
- Cross-runtime differences.

Sentinel should use a tested RFC 8785 implementation or consume published canonical test vectors from the Observatory. The same fixture corpus must run in Python and TypeScript CI.

#### 4. The envelope lacks an explicit serialized protocol version

The Observatory defines `FEDERATION_VERSION`, but it is not included in the emitted envelope. Sentinel only sees the bundle’s schema version.

These are distinct concepts:

- Envelope protocol version.
- Evidence schema version.
- Producer version.
- Analysis-profile version.
- Policy version.

The envelope needs an explicit field such as:

```json
{
  "protocol": "eii-learning-assurance-envelope-v1",
  "bundle": {},
  "signature": "...",
  "signing_key_fingerprint": "..."
}
```

#### 5. The privacy narrative is currently too broad

The documentation says course source does not need to leave the originating organization. However, the evidence bundle includes full course releases and block text.

Consequently, submitting the current envelope can transfer substantial course content into Sentinel.

Three federation profiles are needed:

- `full`: complete canonical content and findings.
- `evidence-minimized`: cited excerpts and hashes only.
- `reference-only`: hashes and resolvable locators, with authorized retrieval on demand.

A deployment should choose the profile according to licence, confidentiality, and institutional policy.

#### 6. Job protocol documentation and implementation disagree

The documentation says workers claim jobs with `GET` and submit a failure using fields resembling `status` and `error`. The implemented route claims using `POST` and expects:

```json
{
  "action": "fail",
  "runId": "...",
  "errorCode": "...",
  "errorDetail": "..."
}
```

The Observatory also lacks a complete long-running worker that polls, claims, executes all requested profiles, renews a lease, and submits the result.

The protocol needs:

- An OpenAPI contract.
- Contract-generated or shared fixtures.
- Lease/heartbeat support.
- Retry rules.
- Stale-job recovery.
- Cancellation.
- Idempotency keys.
- Maximum attempts.
- Dead-letter handling.
- Provider capability negotiation.

#### 7. Audit request and returned evidence are insufficiently bound

Sentinel requests a `sourceRef` and profiles, but ingestion does not fully prove that returned evidence corresponds to:

- That exact source reference.
- The requested adapter.
- The requested profiles.
- The expected course or languages.
- The queued policy context.

A signed execution claim should bind all of those fields.

#### 8. Policies and decisions need stronger immutability

A release decision should contain a snapshot or hash of:

- Exact policy rules.
- Relevant review records.
- Provider assertion.
- Key status at verification time.
- Evaluation timestamp.
- Actor and role.
- Decision algorithm version.

A foreign-key reference to a policy row is insufficient if that policy can later change.

#### 9. No complete end-to-end database proof exists yet

The migration exists, but the complete exchange has not been demonstrated against a target PostgreSQL deployment with:

- RLS enabled.
- Two tenants.
- Two providers.
- Concurrent workers.
- Key rotation.
- Failure and retry.
- Human review.
- Release decision.
- Backup and restore.
- Evidence export.
- Cross-tenant attack tests.

That should be the immediate integration milestone.

### Best Sentinel implementation sequence

1. Publish the federation protocol and shared test vectors.
2. Fix provider/key binding and canonicalization.
3. Redesign decisions as provider assertion + institutional review ledger.
4. Introduce minimized envelope profiles.
5. Implement a real Observatory worker.
6. Add job leases, retry, cancellation, and recovery.
7. Bind returned evidence to the requested source and profiles.
8. Add release comparison and course/language drill-down.
9. Integrate decisions into Sentinel’s procurement evidence pack.
10. Conduct a two-tenant PostgreSQL end-to-end pilot.
11. Add real content only after licence and retention decisions.
12. Seek independent educational and security review.

## 2. Other EII uses

### A. Independent assurance laboratory

EII can offer a service that evaluates courses without hosting the learning platform.

Deliverables could include:

- Signed audit evidence.
- Human-reviewed editorial backlog.
- Translation-equivalence report.
- Tutor safety case.
- Regression suite.
- Before/after comparison.

This is the clearest near-term EII service because it uses the present package without requiring Sentinel adoption.

### B. Open educational resource quality programme

EII could maintain publicly reproducible quality baselines for selected open courses:

- Accessibility findings.
- Prerequisite continuity.
- Assessment coverage.
- Multilingual equivalence.
- Retrieval benchmarks.
- Tutor safety fixtures.

The results should be framed as evidence and unresolved findings—not ratings of institutions.

### C. European multilingual education observatory

BabelBridge can support:

- Erasmus+ consortia.
- Minority-language programmes.
- Migrant education.
- Cross-border vocational training.
- Public-sector translation assurance.
- Shared terminology projects.

EII could maintain language-independent concept identities and domain glossaries as public infrastructure.

### D. Course and AI procurement assessment

EII could help schools compare products based on reproducible evidence:

- Does the tutor cite course material correctly?
- Does it refuse when material is absent?
- Are translated versions educationally equivalent?
- Does changing the model alter safety results?
- Can the provider reproduce the evaluation?
- Can the school run it locally?
- Is the content licence clear?

This should remain advisory unless EII later establishes a formally governed assessment scheme.

### E. Grant monitoring and programme evaluation

Funders could require participating projects to submit versioned evidence on:

- What content was delivered.
- Which learning objectives were supported.
- Which translations were complete.
- Which defects were identified and corrected.
- Whether educational-AI components passed declared gates.

The Observatory provides technical evidence; qualitative and outcome evaluation must remain separate.

### F. Editorial QA service

Publishers and nonprofits could use Curriculum MRI as a structured pre-publication workflow:

```text
Import → deterministic checks → semantic proposals → expert review
→ editorial backlog → source correction → re-audit → regression closure
```

The Observatory should not become the authoring environment. It should export issues to GitHub, GitLab, Jira, or an authoring tool.

### G. Translation-review studies

The built-in randomized and blinded study workflow could support research on:

- False-positive rates.
- Inter-reviewer agreement.
- Language-specific evaluator performance.
- Human review time.
- Finding usefulness and actionability.
- Differences between deterministic and model-assisted checks.

This is the most important path from “internally tested software” to empirically validated educational infrastructure.

### H. Privacy-preserving curriculum feedback

The Weather Map can help EII identify curriculum problems without constructing learner profiles.

Appropriate use:

- Aggregate misconceptions.
- Retrieval failures.
- Language-specific difficulties.
- Repeated unsupported questions.
- Course gaps.

Inappropriate use:

- Student risk scoring.
- Teacher performance ranking.
- Individual intervention automation.
- Behavioural prediction.
- Publishing small-cohort data.

Its present central-DP count mechanism is useful but not yet a complete end-to-end differential-privacy system because cell discovery still relies partly on threshold protection.

### I. Offline education deployments

School-in-a-Box could support:

- Connectivity-constrained schools.
- Child-data-sensitive environments.
- Refugee or temporary education centres.
- Local-language learning centres.
- Public institutions unable to use hosted models.

The Observatory would verify the package and assistant before activation; Sentinel could later synchronize only signed aggregate governance evidence.

### J. EII’s own internal release governance

EII can dogfood the package for:

- Training materials.
- Website educational resources.
- AI policy courses.
- Staff-development modules.
- Grant-funded curricula.
- Sentinel onboarding content.
- Public explainers translated into several languages.

This creates authentic evidence and exposes usability problems before external pilots.

## 3. Use in other future projects

The most reusable asset is not the course analyzer itself. It is the pattern:

> Canonical source objects → reproducible analysis → exact evidence references → signed provider assertion → separate human judgment → explicit policy decision.

That pattern can support many future products.

### A. Evidence Contract SDK

Extract the canonicalization, provenance, signing, review, and policy interfaces into language-neutral specifications plus SDKs.

Potential consumers:

- Python services.
- TypeScript institutional systems.
- Java learning platforms.
- Offline appliances.
- Publisher CI pipelines.

This should become a protocol project only after the current Python/TypeScript duplication is resolved.

### B. Learning-content CI

A GitHub or GitLab application could audit every course pull request:

- Structural drift.
- Missing translations.
- Broken identifiers.
- Changed assessments.
- Accessibility regressions.
- Terminology violations.
- Safety-fixture regressions.

It should post evidence-linked checks and never edit course content automatically.

### C. Authoring-tool integrations

For systems such as eXeLearning, Moodle, Open edX, H5P, Kolibri, and MediaWiki, the Observatory could appear as:

- “Audit this release.”
- “Show unresolved findings.”
- “Compare translations.”
- “Generate regression fixture.”
- “Export signed assurance package.”

The core remains independent; each integration is an adapter plus UI connector.

### D. Public course-evidence registry

A registry could hold metadata and signed evidence—not necessarily course content—for openly licensed resources.

Search could include:

- Language availability.
- Accessibility review.
- Last audited release.
- Known limitations.
- Tutor compatibility.
- Translation status.
- Human-review status.

This must avoid turning provisional findings into reputational scores.

### E. Model-independent tutor benchmark service

The safety-case system could compare:

- Local versus hosted models.
- Prompt versions.
- Retrieval strategies.
- Course versions.
- Languages.
- Hardware, latency, and cost.

The result should be a multidimensional evidence record, not a leaderboard scalar.

### F. Educational AI release registry

A future Sentinel module could register every approved educational-AI configuration and answer:

- Who approved it?
- For which learners and content?
- Under which policy?
- Based on what evidence?
- When does approval expire?
- What changed after approval?
- Which incidents or regressions affect it?

### G. Curriculum knowledge graph

Canonical course blocks, concepts, objectives, prerequisites, assessments, and translations could form an educational knowledge graph.

Potential applications:

- Curriculum comparison.
- Standards mapping.
- Reuse and attribution.
- Translation planning.
- Gap analysis.
- Tutor routing.
- Course discovery.
- Prerequisite-aware recommendations.

This must remain concept- and content-centered, not learner-profile-centered.

### H. Standards and regulatory mapping

A future mapping layer could connect evidence to:

- WCAG criteria.
- Curriculum standards.
- Organizational AI controls.
- Procurement requirements.
- Internal approval obligations.

The Observatory should supply facts; Sentinel or another governance system should interpret regulatory obligations.

### I. Research data infrastructure

With licensed content and ethical governance, anonymized audit records could support research into:

- Translation drift.
- Curriculum structure.
- Retrieval performance.
- Model grounding.
- Human–AI review agreement.
- Accessibility patterns.

Datasets must separate public source content, restricted content, and review records with personal information.

### J. Cross-domain evidence infrastructure

The architectural pattern can extend beyond education. EII’s neighboring projects already use related ideas:

- Sentinel: institutional governance.
- Continuum: continuity and incident evidence.
- LineageGuard: data-lineage and recovery evidence.
- RecallOps: evidence-conditioned operational memory.
- NOMOS: financial and compliance records.

A shared EII evidence foundation could eventually provide:

- Canonical JSON.
- Stable identifiers.
- Signed assertions.
- Trust registries.
- Key rotation.
- Evidence manifests.
- Human attestations.
- Policy snapshots.
- Provenance verification.
- Cross-product evidence export.

However, creating a shared framework now would be premature. First prove two real integrations—Observatory ↔ Sentinel and one external learning platform—then extract only the demonstrably common elements.

## Recommended product structure

EII should treat this as three layers:

```text
Layer 1: Observatory
Content adapters, analysis, retrieval, evaluation and evidence production

Layer 2: Learning Assurance Protocol
Schemas, signatures, canonicalization, transport and compatibility tests

Layer 3: Sentinel
Institutional trust, review, policy, decision, retention and procurement
```

Optional products then sit around those layers:

```text
Course CI       Editorial QA       Offline appliance
     \              |                /
          Open Learning Observatory
                     |
          Learning Assurance Protocol
                     |
        Sentinel / institutional systems
```

## Commercial and public-interest models

The software can remain MIT-licensed while EII offers:

- Paid audits.
- Adapter development.
- Private deployment.
- Human-review coordination.
- Multilingual terminology work.
- Benchmark design.
- Institutional integration.
- Training and support.
- Offline appliance setup.
- Continuous regression monitoring.

Open public goods could include:

- Schemas.
- Reference implementation.
- Synthetic fixtures.
- Public evaluation methodology.
- Terminology glossaries.
- Selected open-course benchmarks.
- Verification tools.

EII should not initially sell “certification.” It can sell or provide “independent evidence-backed assessment” while developing the governance, competence, impartiality, and external oversight needed for stronger claims.

## Priority assessment

| Opportunity | Value | Current readiness | Recommended timing |
|---|---:|---:|---|
| Internal EII course audits | High | High | Now |
| Human-reviewed open-course pilot | Very high | Medium-high | Now |
| Sentinel federation demonstration | Very high | Medium | After contract fixes |
| Publisher editorial QA | High | Medium | First pilot |
| Multilingual Erasmus+ work | Very high | Medium | Near term |
| Procurement evidence annex | High | Medium | After Sentinel lifecycle fix |
| Tutor regression monitoring | Very high | Medium | Near term |
| School-in-a-Box deployment | High | Low-medium | Later pilot |
| Public evidence registry | High | Low | After external validation |
| Formal certification | Very high | Very low | Long term |
| Shared cross-EII evidence SDK | High | Low-medium | After two proven integrations |

## Objective recommendation

The next major milestone should be:

> A genuine end-to-end Observatory–Sentinel learning-assurance pilot using one legally usable multilingual course, two independent reviewers, a real PostgreSQL deployment, and one model-assisted tutor evaluation.

Before that pilot, fix the trust-key scoping, review-to-decision disconnect, canonicalization duplication, envelope versioning, privacy profiles, and job-protocol mismatch.

That single pilot would produce the evidence EII currently lacks:

- Real adapter evidence.
- Real multilingual findings.
- False-positive and false-negative estimates.
- Human-review usability data.
- Cross-runtime signature compatibility.
- Sentinel operational evidence.
- A defensible case study.
- A reusable external integration blueprint.

The software’s best future is not as another tutor. It is as an independent evidence-producing subsystem that lets institutions govern courses, translations, and educational AI without surrendering their judgment—or their data—to the platform being evaluated.
