# Key-management runbook

Publisher and independent evaluator keys have different owners and must never be
shared. Generate Ed25519 keys on an administrator-controlled offline machine;
store private keys in an encrypted hardware-backed store where available. Copy
only public keys to appliances. Record owner, purpose, fingerprint, creation,
expiry/review date, and revocation status in the deployment inventory.

Sign release packages with the publisher key and configured-gates-passed safety cases with the
evaluator key. Verify fingerprints over an independent channel before initial
trust. Rotate with `appliance-trust-rotation-create` and
`appliance-trust-rotation-apply`, retaining the signed authorization and
`trust/history.jsonl`. Test the new key before revoking the old one.

Human safety reviewers use distinct Ed25519 keys. Sign review records with
`safety-review-sign`; release operators must independently verify reviewer
fingerprints and pass the approved fingerprints to safety verification,
packaging and appliance installation. A signature proves key control, not a
person's employment, qualifications or delegated authority. Each review's
`subject_hash` binds it to the exact serialized case result, so approval cannot
be replayed after the fixture, answer, retrieval or automatic evaluation changes.

Generate Classroom Weather secrets with `weather-key-generate`. Keep the
rotating contribution-linkage key separate from the stable export-ledger key;
both are mandatory files for CLI operation. The database binds the ledger-key
fingerprint on first open and rejects substitution. Back up the ledger key in the
institutional secret store: losing it makes prior export history unverifiable, while
reusing the linkage key as the ledger key makes safe unlinkability rotation impossible. Rotation is
an explicit `weather-key-rotate` operation and always creates a verified backup
before purging records linked under the prior epoch.

On suspected private-key compromise: stop publishing, preserve logs, revoke the
fingerprint at every appliance, generate a new key, issue a separately verified
rotation/recovery statement, rebuild affected artifacts, and notify operators.
Do not delete the audit trail. Do not provision HMAC package keys. Symmetric-key
packages have no supported creation, installation, authentication, or migration
path in version 0.1.0.
