# Classroom Weather Map privacy contract

Weather Map records categorical pedagogical events, not conversations. Its
event schema permits only timestamp, course/activity keys, language, concept,
signal and a short-lived pseudonymous contribution token. Imports containing any
additional field are rejected, including seemingly convenient raw questions.

Before persistence, contribution tokens are keyed-hashed with a local secret,
explicit key epoch, UTC day and complete aggregate-cell identity. A stored value
therefore cannot link a contributor across days or cells. Tokens must be rotated
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

Exported counts are rounded down to a configured granularity. A database commits to
either global or course-partitioned exports; mixing both query families is rejected to
avoid overlapping-query subtraction. The database records every export in a
hash-chained append-only ledger and refuses a changed export inside the minimum
interval (24 hours by default), including across JSON and HTML views. Each key epoch is
bound to one secret, a secret cannot be relabeled as another epoch, and activating a
new epoch purges old linkage rows.
This reduces short-window differencing risk. It is disclosure control, not a
claim of formal differential privacy; deployment privacy review remains required.

The ledger detects local history alteration but cannot prevent an operator from cloning
or rolling back an entire database. High-assurance deployments need protected backups,
monotonic external audit anchoring, and a deployment privacy assessment. Deployments
should keep both the SQLite database and secret on the school
server. Moving the secret off-device or correlating rotating tokens with school
accounts violates this privacy contract.
