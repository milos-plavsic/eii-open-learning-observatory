# School-in-a-Box operations

School-in-a-Box runs without cloud credentials or learner accounts. A release
is a `.eii` ZIP containing course UI/content, optional local model assets,
evaluation evidence, a canonical manifest and an integrity signature.

```bash
eii appliance-check
eii appliance-package ./offline-site ./models/model.gguf ./evidence \
  --version 2026.08 --private-key-file ./publisher-private.pem --output school.eii \
  --model-base-url http://127.0.0.1:8000/v1 --model local-model \
  --course-path content/course-export.json
eii appliance-install school.eii --root /srv/eii \
  --public-key-file /etc/eii/publisher-public.pem
eii appliance-serve --root /srv/eii --port 8080 --audit-log /var/log/eii/audit.jsonl
```

Installation verifies the manifest signature and every file hash before writing
the release. It extracts only enumerated, traversal-safe paths into staging and
atomically changes `active.json` after verification succeeds. The previous
release remains available for manual rollback. `/healthz` reports whether the
active release is readable. All other paths serve files only from its `content`
directory.

After the first install, every update must embed a Tutor Safety Case whose
release decision is `configured_gates_passed`; otherwise activation stops before extraction.
The case must have a valid canonical digest and independent evaluator Ed25519
signature, all cases and gates must pass, and its course hash, model, and prompt
must match the staged release exactly. Use `eii safety-sign` and
`--safety-case gates-passed-case.json`; installation requires the evaluator's
`--safety-public-key-file`. Teachers configure the
enabled course/language set and behavior with `eii appliance-configure`, and
`eii appliance-rollback` atomically restores the preceding verified release.

When model metadata is present, `POST /api/query` performs local lexical
retrieval and calls the configured OpenAI-compatible model. Model endpoints are
accepted only on loopback (`localhost`, `127.0.0.1`, or `::1`), which supports
vLLM without allowing classroom prompts to leave the machine. Requests contain
no account field and are not retained by the appliance service.

Supported CLI provisioning uses Ed25519 via a validated OpenSSL 3-or-newer runtime: package with
`--private-key-file` and install with the corresponding `--public-key-file`.
Private publisher keys never enter a school. Symmetric-key/HMAC packages are
rejected, cannot be created or installed, and have no compatibility path.

For managed updates, initialize the appliance trust store with
`eii appliance-trust-init`. A publisher authorizes a replacement key with
`eii appliance-trust-rotation-create`; the school applies that signed statement
with `eii appliance-trust-rotation-apply`. The statement embeds and fingerprints
the new public key, is signed by the currently trusted private key, and can
either overlap both keys or revoke the old key. Every change is appended to
`trust/history.jsonl`. Subsequent installs use `appliance-install
--use-trust-store`, which accepts only a currently trusted publisher.

Course content and model licenses must be recorded in package metadata and
reviewed independently. Package verification proves integrity, not permission
to redistribute its contents.

For managed deployments, bind EII to loopback and place it behind an HTTPS
reverse proxy. `deploy/Caddyfile.example` provides a private-PKI TLS profile and
`deploy/eii-appliance.service` provides a restricted systemd unit. Create a
random classroom bearer token outside the appliance content directory with
mode `0600`, and pass it through `--query-token-file`. Rotate it between cohorts
or immediately after suspected disclosure. The token is an access boundary,
not a learner identity, and must never be logged or embedded in evidence.

Administrative package installation, trust rotation, configuration, rollback,
and recovery remain local filesystem operations requiring operating-system
administrator access; they are deliberately not exposed as HTTP endpoints.

The service exposes `/healthz` for process liveness, `/readyz` for active-release
readiness, and dependency-free Prometheus metrics at `/metrics`. The example
proxy deliberately blocks classroom access to metrics; collect them directly
over loopback. Audit JSONL contains only request ID, bounded route name, method,
status and duration—never learner text, authorization headers, bodies, query
strings or static paths. Restrict the log to administrators, rotate it by size,
and delete it according to the documented local retention policy.

The systemd example loads the classroom token through systemd credentials,
creates private state and log directories, caps memory/tasks/file descriptors,
and applies kernel, process, namespace, capability, syscall and filesystem
restrictions. Sites must tune `MemoryMax` to the selected local model and verify
the unit with `systemd-analyze security eii-appliance.service` after every OS
upgrade.
