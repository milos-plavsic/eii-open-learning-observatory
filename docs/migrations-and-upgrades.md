# Upgrade, migration, backup, and rollback

Before upgrading, read release notes, stop writers, run `database-status`, create
an online `database-backup`, copy the active package/trust state, and verify free
disk capacity. Test the new version against a restored copy first.

Database opening applies ordered migrations in one transaction and rejects a
database from another subsystem or a newer schema. After upgrading, run status,
application smoke tests, schema validation, PLCT conformance, and readiness.
Retain the prior executable and backup until the local observation period ends.

Weather database schema 2 adds the singleton `privacy_exports` record used to
enforce the cross-format minimum export interval. The migration does not alter
or expose existing minimized events. Downgrading to a binary that supports only
schema 1 requires restoring the pre-upgrade backup; it must not bypass the
future-schema rejection.

Weather schema 3 adds `privacy_exports_v2`. Schema 4 binds secrets to key epochs,
prevents mixed global/course query partitions, and adds an export ledger. Schema
5 conservatively purges events and old unauthenticated export records during
migration, makes rotation an explicit backup-first operation, authenticates the
ledger with a separate key, and enforces append-only audit rows with database
triggers. The export table maintains
budgets per course scope. New contributions use key-epoch, day and cell-scoped
pseudonyms. Restore a pre-schema-5 backup with the old executable if historical
minimized rows must be retained; they are intentionally not carried forward.

Schema 6 adds persistent differential-privacy budgets and memoized releases plus
the exact-artifact v2 export ledger. Schema 7 binds the independent ledger key and
adds an authenticated publication journal. Schema 8 records the partition strategy
and prior artifact hash in that journal, allowing deterministic recovery at every
filesystem/database crash boundary. Opening the database authenticates the complete
ledger and finishes or rolls back journaled publications before accepting work.

Generate the linkage and ledger secrets separately with `weather-key-generate`.
Treat the ledger key as durable recovery material. Rotate the linkage key only with
`weather-key-rotate`, which requires the current and new secrets, a distinct
stable ledger key, explicit old/new epoch names, and a backup destination.

Application rollback never means database downgrade. If the older executable
cannot read the migrated schema, restore the pre-upgrade backup while all writers
are stopped. Verify integrity before service start. Appliance content rollback is
atomic through `appliance-rollback`; damaged activation pointers can be rebuilt
from intact history with `appliance-recover`.

Practice restore quarterly and record timestamp, operator, source hash, target,
integrity result, row-count checks, elapsed time, and recovery-point loss.
