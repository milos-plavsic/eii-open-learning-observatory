# Classroom Weather Map privacy contract

Weather Map records categorical pedagogical events, not conversations. Its
event schema permits only timestamp, course/activity keys, language, concept,
signal and a short-lived pseudonymous contribution token. Imports containing any
additional field are rejected, including seemingly convenient raw questions.

Before persistence, contribution tokens are keyed-hashed with a local secret and
explicit key epoch. Compatibility mode binds the hash to UTC day and cell, so it
cannot link across days or cells. Fixed-universe mode binds it to course and UTC
day so the system can enforce a maximum number of contributed cells; this allows
within-course/day linkage but not cross-day linkage. Tokens must be rotated
by the collecting classroom service. This is pseudonymization, not anonymity.
Timestamps are reduced to their UTC calendar day before persistence. One
contributor can add at most three events per day to the same
course/activity/language/concept/signal cell by default, limiting one device's
ability to dominate a displayed count. Deployments may lower this bound.

Aggregates are visible only when the distinct-contributor count reaches the
configured threshold (default 5). Events expire after the configured retention
period (default 30 days), and expiry runs before each CLI import. Export files
contain the applicable threshold and retention policy and never contain hashes,
tokens, direct identifiers, or conversation text.

After exact small-cell suppression, exported event and contributor counts receive
independent Laplace noise under a persistent, memoized epsilon budget and are then
rounded to a configured granularity. The formal protected unit for those released
count vectors is one bounded contributor/cell/UTC-day. Empty exports consume no
budget, and an export rejected by interval or partition policy is rejected before
noise generation. A database commits to
either global or course-partitioned exports; mixing both query families is rejected to
avoid overlapping-query subtraction. The database records every export in a
keyed, hash-chained append-only ledger binding the exact JSON or HTML bytes and refuses a changed export inside the minimum
interval (24 hours by default), including across JSON and HTML views. Each key epoch is
bound to one secret, a secret cannot be relabeled as another epoch, and activating a
new epoch purges old linkage rows.
The independently managed ledger key is bound to the database and must remain stable
across linkage-key rotation. Artifact replacement uses an authenticated, fsync-backed
recovery journal: startup either completes an installed artifact's ledger record or
restores the prior bytes. Verification authenticates the complete append-only chain,
not the mutable latest-export index. A failed artifact publication conservatively
retains any privacy budget already spent; retrying the same memoized snapshot reuses
the same noisy release and spends no additional epsilon.
In compatibility mode this supplies differential privacy for each released fixed count vector, under the
stated protected unit and sequential-composition budget. It does not make the full
sparse report end-to-end differentially private: cell selection still depends on an
exact threshold over a data-dependent set of cells. A fixed public cell universe or
reviewed private-histogram mechanism is required before making that stronger claim.
Fixed-universe mode instead publishes a curriculum-declared, data-independent cell
set including zero cells and bounds contributor sensitivity across those cells;
it therefore implements an internally verified end-to-end central-DP mechanism
for that declared adjacency. Independent privacy review remains required.
Deployment privacy review remains required.

The ledger detects local history alteration. Database-instance lineage rejects a
clone opened under a different configured identity and records explicit forks,
but cannot detect two copies both continuing under the original identity or a
whole-store rollback. High-assurance deployments need protected backups,
monotonic external audit anchoring, and a deployment privacy assessment. Deployments
should keep both the SQLite database and secret on the school
server. Moving the secret off-device or correlating rotating tokens with school
accounts violates this privacy contract.
