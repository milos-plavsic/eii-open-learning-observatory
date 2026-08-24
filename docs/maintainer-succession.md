# Maintainer succession and dual-control runbook

This runbook is a readiness package, not evidence that a second maintainer or
independent key custodian exists. VAL-010 closes only after the named people,
accounts, keys and rehearsal receipts below are independently verified.

## Required roles and separation

Two individually attributable people must hold separate GitHub accounts with
phishing-resistant multifactor authentication. The **promoter** reviews the exact
candidate and authorizes `production-release`; the **publisher** independently
reviews the signed promotion receipt and authorizes `production-publish`. One
person must not hold both roles for the same release, approve their own run, share
credentials, or use administrator bypass. At least one separately authorized
governance officer must be able to replace either role without possessing a live
signing key.

Record each person's legal name, organizational role, GitHub login, start date,
scope, and approving governance decision in the private institutional access
register. Publish only the non-sensitive role/login mapping. Quarterly access
review removes dormant or departed users and records the GitHub audit-log event.

## Key custody

Production signing should use an OIDC-bound KMS/HSM key whose policy admits only
the pinned promotion workflow on the protected `main` ref. If PEM custody is
temporarily unavoidable, store the encrypted private key only in the protected
GitHub environment and retain an offline encrypted recovery copy under dual
control. Never place a private key, recovery secret, or unredacted access register
in this repository.

Recovery material must require two independently held factors. Document the key
identifier, public fingerprint, creation ceremony, custodians, storage locations,
access-log location, expiry, and destruction procedure. Test recovery annually
with a disposable non-production key. A recovery test must not expose or exercise
the production private key merely to prove that recovery documentation exists.

## Appointment checklist

1. Governance names the promoter, publisher, and succession officer.
2. Administrators verify separate accounts and phishing-resistant MFA.
3. Add only the minimum repository/environment permissions needed by each role.
4. Configure both protected environments with self-review and administrator
   bypass disabled; export the settings and reviewer identities as evidence.
5. Register the independently controlled public key and verify its fingerprint
   through a second channel.
6. Run a non-public candidate through promotion and publication rehearsal using
   disposable version and key material.
7. Confirm that self-promotion, same-actor publication, altered receipts, changed
   source revision, and unauthorized keys all fail closed.
8. Archive workflow URLs, actor identities, artifact hashes, approval receipt,
   public-key fingerprint, settings export, and governance sign-off.

## Succession and emergency revocation

Departure, suspected compromise, lost MFA, unexpected key use, or governance
revocation immediately freezes release environments. Remove the account, revoke
the key/KMS grant, preserve audit logs, rotate affected credentials, and follow
`incident-response.md`. Reappointment repeats the full checklist; transferring a
departing person's credential or private key is prohibited.

VAL-010 may be closed only when the archived rehearsal demonstrates two distinct
eligible actors and an independently controlled key. Repository tests and a
deadlocked environment are useful controls but are not that evidence.
