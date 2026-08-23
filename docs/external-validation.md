# External validation evidence

EII cannot review itself into independence. Petlja integration approval,
multilingual human accuracy, penetration testing, independent reproduction and
target-school pilots therefore end in a separately signed record owned by the
reviewing organization.

Start from `examples/external-validation-statement.json`. Replace every
placeholder, identify the exact procedure/version and subject artifact hashes,
record all findings and limitations, and select `passed`, `failed`, or
`conditional`. A conditional outcome does not satisfy a 10/10 gate unless the
release authority explicitly accepts and documents every condition.

The reviewer generates and controls an Ed25519 key, then runs:

```bash
eii external-record-sign statement.json --private-key-file reviewer-private.pem \
  --public-key-file reviewer-public.pem --output external-record.json
eii external-record-verify external-record.json --public-key-file reviewer-public.pem
```

The recipient independently establishes that the fingerprint belongs to the
named organization. The signature proves integrity and key control, not the
reviewer's competence, authority, or truthfulness.

Minimum attachments by gate:

- Petlja integration: genuine export hash, repository revision, QueryContext
  capture, course/version/languages and Petlja-specific attestation.
- Human accuracy: frozen study ID/dataset, sampling plan, reviewer criteria,
  blinded decisions, agreement/calibration statistics and exclusions.
- Penetration test: exact release/deployment scope, methodology, dates,
  severity definitions, full finding disposition and retest evidence.
- Independent reproduction: clean environment identity, commands, raw gate
  output, artifact digests and deviations.
- Target-school pilot: hardware/software inventory, cohort/privacy approval,
  capacity/load results, restore and power/disk failure drills, observed SLO,
  incidents and operator acceptance.

Archive the signed record, reviewer public key, fingerprint-verification note,
attachments and exact release artifacts together. Never place learner personal
data, private keys or live credentials in this package.
