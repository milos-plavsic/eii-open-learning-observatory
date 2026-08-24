# Release signing keys

Commits and release tags are signed with the following dedicated SSH signing
key:

```text
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEdhAxp8K9c/qitt5zIbhO07X9wrrexGyilsn7phNEgI eii-open-learning-observatory release signing
```

Fingerprint:

```text
SHA256:Bfbi1YApplkWdXemU3C8c09TLsUeyIxnPHBvEjh5IJo
```

To verify locally, place the public-key line in an allowed-signers file prefixed
with the commit identity, then configure `gpg.ssh.allowedSignersFile` and run
`git verify-commit <commit>` or `git verify-tag <tag>`.

This key signs repository history only. Signed evidence bundles and offline
appliance releases use the separate trust procedures documented in
`docs/key-management.md`, `docs/release-operations.md`, and the fail-closed
appointment and recovery procedure in `docs/maintainer-succession.md`.
