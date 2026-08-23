# Learning assurance federation v1

The Observatory can operate locally at a foundation or school and submit only a
signed evidence bundle to a governance system. Course source and learner prompts
do not need to leave the originating organisation.

## Trust ceremony

1. The Sentinel institution administrator registers a content provider.
2. Sentinel displays the provider bearer token exactly once and stores SHA-256 of the token.
3. The provider generates an Ed25519 key pair offline and protects the private key.
4. The administrator obtains the public key through an independently authenticated channel.
5. Both parties compare its 64-character SHA-256 fingerprint out of band.

The bearer token authenticates the connection. The signature authenticates the
evidence itself and remains independently verifiable after transport.

## Produce and submit evidence

```bash
eii federation-envelope report/evidence.json \
  --private-key-file provider-private.pem \
  --public-key-file provider-public.pem \
  --provider-id "$PROVIDER_ID" \
  --output envelope.json

eii federation-verify envelope.json --public-key-file provider-public.pem

eii federation-submit envelope.json \
  --endpoint https://sentinel.example/api/v1/learning-assurance/evidence \
  --institution-id "$INSTITUTION_ID" \
  --token-file provider-token.txt
```

The client refuses cleartext transport except loopback when explicitly enabled
for development. Redirects are refused so credentials cannot be forwarded.

## Durable worker protocol

Sentinel administrators queue audits with an immutable provider-visible source
reference and one or more profiles (`babelbridge`, `curriculum-mri`, or
`tutor-safety`). A provider polls `GET /api/v1/learning-assurance/jobs` with the
same authentication headers used for evidence submission. Claiming is atomic,
so concurrent workers cannot receive the same queued run. A failed worker posts
`{"runId":"…","status":"failed","error":"…"}` to that endpoint; a successful
worker submits an envelope tied to the run. Jobs survive process restarts.

Rotate a provider bearer token after suspected disclosure; the old value becomes
invalid immediately. Revoke a compromised Ed25519 trust key to reject new
submissions while retaining the historical fingerprint and verification record.

## Sentinel verification

- Tenant, active provider and provider bearer token.
- Provider identity in headers and envelope.
- Exact JSON shape and schema version.
- Content-block and course-release canonical hashes.
- Finding-to-block and review-to-finding references.
- Canonical evidence-bundle identifier.
- Active trusted Ed25519 key, fingerprint and signature.
- Duplicate-ID collision protection.

## Privacy and compatibility

Evidence excerpts must be minimized. Raw learner events, names, email addresses,
persistent student identities and unredacted tutor conversations are outside
the exchange contract. Unknown top-level fields are rejected in v1. A breaking
change requires a new explicit contract version.
