# Security policy

## Supported versions

Until a stable release, only the newest `0.x` minor line receives security fixes.

| Version | Status |
|---|---|
| 0.2.x | Supported |
| 0.1.x | Unsupported |
| Unreleased `main` | Development only |

## Reporting

Do not open a public issue for a suspected vulnerability. Send an initial report
to `support@eii.edu.eu` with `SECURITY` in the subject, including affected version,
reproduction, impact, and whether learner or reviewer data may be involved. The
project will acknowledge within two working days, provide an initial severity
assessment within five, and coordinate disclosure after a fix is available.

Do not include live credentials, personal data, private course material, or an
unredacted exploit in the initial message. Request an encrypted channel in that
message; EII will provide a case-specific public key and fingerprint through a
separate channel before sensitive material is transferred. The repository does
not currently publish a long-lived vulnerability-reporting key and therefore
does not claim that ordinary email to this address is end-to-end encrypted.

Never include real learner conversations, bearer tokens, private keys, or
unredacted databases. Test with synthetic data. If a live credential may have
escaped, revoke or rotate it immediately before waiting for a response.

## Scope and guarantees

In scope are package verification and activation, Ed25519 trust rotation,
safety-case integrity, HTTP authentication/authorization, path handling,
database privacy boundaries, and generated evidence. Hashes prove integrity,
not truth, educational quality, licensing, or independent approval. Provisioning,
installation, and distribution require Ed25519. Symmetric-key/HMAC appliance
packages are rejected and have no supported migration or installation path.

See `docs/threat-model.md`, `docs/key-management.md`, and
`docs/incident-response.md` for controls and response procedures.

## Independent assessment status

No independent security assessment has yet been completed. The procurement-ready
scope and acceptance criteria are in `docs/security-assessment-brief.md`; status
is tracked as VAL-006 in `docs/validation-commitments.md`. No production or
learner-data claim may treat internal tests as a substitute for that review.
