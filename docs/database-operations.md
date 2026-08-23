# Database operations

Weather Map and blinded-review databases are SQLite files managed by a shared,
versioned lifecycle. Opening a store enables foreign keys, WAL mode and a
five-second busy timeout, runs an integrity check, applies ordered migrations,
and rejects databases created by a newer unsupported release or another EII
subsystem.

## Inspect

```bash
eii database-status /srv/eii/weather.sqlite --kind weather
eii database-status /srv/eii/reviews.sqlite --kind review-study
```

The command exits non-zero for corruption, an unsupported future schema or a
database-kind mismatch. A successful result includes the database kind, schema
version and `ok` integrity result.

## Online backup

The application may remain open while SQLite's backup API takes a consistent
snapshot:

```bash
eii database-backup /srv/eii/weather.sqlite --kind weather \
  --output /srv/eii/backups/weather-$(date +%F).sqlite
```

The destination is integrity-checked before success is reported. Protect
backups using the same filesystem permissions and retention policy as the live
database. A backup may contain pseudonymous contribution hashes or confidential
review decisions even though it contains no raw learner conversations.

## Restore drill

1. Stop writers to the affected database.
2. Preserve the damaged file, its `-wal` and `-shm` companions for investigation.
3. Copy the selected verified backup to a new path; do not overwrite the only copy.
4. Run `database-status` against the new path with the correct kind.
5. Start the service against the restored path and execute a read-only export.
6. Record the backup identifier, integrity result, operator and recovery time.

## Migration policy

- Schema versions are monotonic SQLite `user_version` integers.
- Every release must migrate from every still-supported prior version.
- Migrations run under an immediate transaction before normal access.
- Downgrades are not performed in place; restore a backup made by the older release.
- A newer database is rejected rather than guessed at or silently modified.
