# Observability and service objectives

Both HTTP services expose `/healthz`, `/readyz`, and `/metrics`. Liveness means
the process can respond; readiness additionally checks the active release or
review database. Reverse proxies must route traffic only when readiness passes.

Prometheus metrics use bounded route labels and expose request count, cumulative
latency, a fixed-bucket request-duration histogram, in-flight requests, capacity
rejections and audit-log failures. Alert when readiness fails for two minutes,
5xx responses exceed 1% for five minutes, or p95 latency exceeds the locally
agreed classroom limit. The initial operational objectives are 99.5% availability
during scheduled classroom hours and no loss of an acknowledged review decision.

`--audit-log` appends JSONL request metadata through a private-permission,
size-rotated stream. `--audit-log-max-bytes` bounds each active file and
`--audit-log-retention-days` removes expired rotations at open, rotation, and at
least hourly while requests continue. One process holds an exclusive writer lock;
a second process configured for the same log fails closed instead of racing a
rotation. Individual records larger than the configured file bound are rejected.
Events contain request ID, method,
bounded route, status, and duration only. They exclude query strings, learner
text, bodies, headers, tokens, reviewer identity, IP addresses, and static paths.
Filesystem deletion cannot guarantee physical erasure on journaling or flash
storage; deployments needing that property require encrypted storage and key
destruction. The provided Caddy profile deliberately has no access log because its
default fields include client network data. If a site enables proxy logging, it
must remove client addresses and authorization data or document a separate lawful,
approved data flow with its own retention policy.

For a release, exercise liveness/readiness failure, scrape metrics from loopback,
verify a request ID, force one 4xx and one 5xx, inspect the audit record, and
confirm no submitted text or credential appears. Record results in the release
evidence directory.

The bundled server limits accepted active requests to 64 daemon worker threads,
rejects excess accepted connections with a request-identified HTTP 503 and
`Retry-After`, reports and audits capacity rejections without request content,
does not invent latency samples for rejections before a request worker starts,
uses a bounded listen backlog and 30-second per-connection socket deadlines, and
marks readiness as draining on SIGTERM/SIGINT. Explicit drain bookkeeping waits
for accepted workers up to the configured grace period, then shuts down remaining
sockets so a stuck third-party handler cannot prevent process exit. It remains a single-process appliance service, not a general-purpose
internet application server. Public deployments require the documented TLS
proxy, network-level connection and request-rate controls, and a tested shutdown
drain procedure. Model saturation and multi-process coordination are outside the
0.1.0 service boundary.

Per-client rate-limit state is TTL-expired and capped at 4,096 active client
keys. New identifiers fail closed while the state is full, preventing eviction-based
bypass. The active-request bound is a process safeguard, not a substitute for proxy and
network connection limits. Abrupt process termination can still interrupt
in-flight work; durable review decisions rely on SQLite transaction completion.
