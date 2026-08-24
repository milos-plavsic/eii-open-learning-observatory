# Threat model and recovery

## Assets and trust boundaries

Protected assets are course integrity, release decisions, classroom prompts,
pseudonymous aggregate data, publisher trust keys, and service availability. Source
repositories, imported PLCT exports, model responses, package archives, browsers,
and classroom event files cross explicit validation boundaries. Course content
is also untrusted prompt input.

## Threats, controls, and residual risk

| Threat | Implemented control | Residual risk / operation |
|---|---|---|
| Course or model package tampering | Ed25519 manifest signature plus per-file SHA-256 before extraction in supported CLI workflows. | Publisher endpoint compromise remains possible; rotate/revoke its key and rollback. |
| Audit-report substitution or ambiguous provenance | Typed semantic records verify a sealed evaluation plan, canonical excerpts, alignment membership, model-run linkage and exact finding projections; size-bounded, snapshot-safe Ed25519 manifests bind signer, purpose, time and all files. Optional policies authorize signer/key/purpose/validity tuples and reject implausibly future signing times. | Policy issuance, revocation distribution, trusted time and key custody remain deployment responsibilities. The two output metadata files fail closed if a crash interrupts replacement, but publication should still stage and rename the complete report directory atomically. |
| Archive path traversal | Absolute and parent paths are rejected; only manifest-enumerated files are staged. | Administrators must protect the appliance filesystem itself. |
| Unsafe update regression | Existing appliances independently verify the evaluator signature, canonical case digest, passing gates, answer hashes, and exact staged course/model/prompt binding before activation. | Test-suite omissions remain visible as known limitations. |
| Malicious key replacement | New public key must be fingerprinted and signed by a currently trusted key; rotations are logged. | Offline compromise of the current private key requires out-of-band school re-provisioning. |
| Missing or incompatible system cryptography | Signing and verification reject absent, LibreSSL, and OpenSSL runtimes older than version 3; Linux, macOS, and Windows CI execute real Ed25519 generation, signing, verification, fingerprinting, and tamper rejection. | Operators must retain a supported patched OpenSSL 3-or-newer build on `PATH`; platform packaging does not bundle it. |
| Private signing-key exposure through local file permissions | Secret-file reads enforce owner-only permission bits on POSIX systems. Windows does not expose its DACL through Python's POSIX-compatible `st_mode`, so the implementation does not misinterpret that synthetic mask; operators must restrict the key with Windows DACLs or use protected CI environment secrets. | Windows DACL policy is deployment-owned and is not independently audited by this dependency-light package. Production publisher keys should be held in KMS/HSM infrastructure where available. |
| Prompt exfiltration | Appliance model endpoints must resolve to an explicit loopback hostname; no cloud keys or accounts are required. | A separately compromised local model server can still log prompts. |
| Prompt injection in course content | Tutor system prompt treats passages as evidence; canary safety fixtures and release gates test resistance. | Model behavior is probabilistic and must be regression-tested after changes. |
| Learner surveillance | Raw fields are rejected; day/cell-scoped pseudonyms prevent cross-cell linkage; retention purges events; k-thresholds suppress small cells. Released count values receive cryptographically sampled Laplace noise under a persistent basic-composition epsilon budget; blocked and empty releases spend no budget; identical scope/snapshot/policy releases reuse noise; exact JSON/HTML bytes are hash-ledgered. | The protected unit is one bounded contributor/cell/UTC-day, not a person across cells. Because the set of published cells is selected by an exact threshold, the complete sparse release is not claimed to satisfy end-to-end differential privacy. A fixed public cell universe or reviewed private-histogram mechanism is required before making that stronger claim. Database clones require institution-level budget coordination. |
| Weather ledger substitution or export crash | A distinct durable ledger key is fingerprint-bound to the database; startup authenticates the full HMAC chain. An authenticated journal binds destination, old/new hashes, strategy, scope and release metadata; staged writes, replacements and directory entries are fsynced and recovered deterministically. | Key loss makes old history unverifiable. Whole-database rollback and loss of both database and artifact still require protected backups and external monotonic anchoring. Filesystem or SQLite implementations that violate documented durability semantics remain platform risks. |
| Cross-site/script injection in reports | Course/finding content is HTML-escaped, embedded JSON escapes closing script sequences, inline handlers are absent, and served HTML receives per-response CSP nonces. | Third-party course scripts remain untrusted and should be reviewed before packaging; browser/platform vulnerabilities remain external. |
| Denial of service | Query size, worker count, model concurrency, client rate-state memory, and static paths are bounded; full rate state rejects new identities rather than evicting counters; overload receives an audited 503. | The limiter is process-local rather than distributed; LAN firewalling and proxy limits remain required. |
| Hung semantic providers | HTTP connection and bounded incremental response reads share one wall-clock deadline across retries; unresolved custom-comparator panels retain a bounded capacity lease until their workers finish. | Python cannot forcibly terminate arbitrary third-party threads; custom comparators must implement the timeout contract or run behind a killable process boundary. |
| Active-pointer corruption | Releases remain immutable; append-only activation history supports `appliance-recover`. | Loss of all release directories requires reinstalling a verified package. |

## Recovery drill

1. Stop the classroom server.
2. Preserve the appliance directory for investigation.
3. Run `eii appliance-recover --root /srv/eii`; this chooses the newest release
   in activation history whose manifest remains present and atomically rebuilds
   `active.json`.
4. If the release itself is suspect, run `eii appliance-rollback` or reinstall a
   package with the trust store.
5. Start the service, check `/healthz`, rerun the offline safety case, and record
   the incident and any publisher-key rotation.

Automated tests cover wrong signatures, key rotation, unsafe update rejection,
rollback, pointer recovery, path constraints, small-group suppression, and
retention deletion.
