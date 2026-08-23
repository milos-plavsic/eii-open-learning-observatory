# PLCT integration and conformance

EII does not import PLCT runtime classes. A Petlja-controlled exporter emits
`plct-course-export-v1`, and EII converts that document into its canonical
course model. This makes the boundary replaceable and gives both projects a
small contract to version and test.

## Required identities

- `course_key` is the stable PLCT course identity.
- `activity_key` is stable across content-only releases and is unique per course.
- `chunk_key` is stable within an activity and is unique within that activity.
- `canonical_course_id` joins language versions of the same educational course.
- `translation_id` explicitly aligns educational units when structure differs.
  It is relationship identity, not merely a local label, and therefore must be
  unique for one relationship within a language release. If a source system
  reuses a local ID under different parents, it must also emit
  `metadata.translation_scope`; the canonical identity is
  `translation_scope::translation_id`. Differently scoped identities are never
  heuristically paired. Repeated identity declares one relationship and supports
  one-to-many, many-to-one and many-to-many source structures.
- `repository` must be stable; it must not be a temporary export filename.

Changing text, order, hierarchy, concepts, objectives or provenance changes the
canonical hash. Renaming an export file does not when `repository` is supplied.

## Captured QueryContext fixtures

Integration conformance requires at least one `query_context_cases` item. Each
case contains the learner question, activity context and the ordered blocks
actually returned by PLCT. Every returned block ID and hash must bind to a block
in the same export, and every score must be finite and between zero and one.

These cases are regression evidence, not a claim that PLCT must retain one
retrieval implementation. A deliberate retrieval change updates the fixtures
and is reviewed like another interface change.

## Run conformance

```bash
eii plct-conformance plct-export.json \
  --previous previous-plct-export.json \
  --output evidence/plct-conformance.json
```

The command emits the conformance report plus an identifier compatibility
comparison. It exits `2` when the software contract fails. A missing Petlja
attestation is reported separately and does not pretend to be a software error.

## Maintainer attestation

Only a Petlja maintainer may supply this optional export field:

```json
{
  "petlja_attestation": {
    "maintainer": "reviewer pseudonym or organizational identity",
    "reviewed_at": "2026-08-21T12:00:00+02:00",
    "repository_revision": "full commit hash",
    "notes": "Confirmed identifiers and QueryContext capture semantics"
  }
}
```

EII checks that an attestation is structurally present but does not claim to
authenticate the person's authority. A signed organizational review artifact
should accompany production acceptance.

Petlja can create that separately owned artifact after reviewing the generated
report. The signature binds the report hash, raw export hash, canonical release
hash and repository revision to the maintainer identity and Petlja-controlled
Ed25519 key:

```bash
eii plct-attest evidence/plct-conformance.json \
  --maintainer "Petlja maintainer" --repository-revision FULL_COMMIT \
  --private-key-file petlja-private.pem --public-key-file petlja-public.pem \
  --output evidence/petlja-attestation.json
eii plct-attestation-verify evidence/petlja-attestation.json \
  --report evidence/plct-conformance.json --public-key-file petlja-public.pem
```

EII validates the cryptography and binding, but the recipient must independently
establish that the public-key fingerprint belongs to Petlja. EII never generates
or controls Petlja's signing key and therefore cannot self-attest this gate.
