# Dependency and licence inventory

The `eii-observatory` source is MIT licensed; see `LICENSE`. Its pinned runtime
dependencies are:

| Component | Version | Declared licence | Purpose |
|---|---:|---|---|
| `defusedxml` | 0.7.1 | PSF-2.0 | Defensive parsing of untrusted XML formats |
| `rfc8785` | 0.1.4 | Apache-2.0 | RFC 8785 JSON canonicalization for hashes and signatures |

Python itself, OpenSSL, SQLite,
the operating system, reverse proxy, local model runtime, model weights, course
content, fonts and browser are deployment components and are not relicensed or
redistributed by this repository unless a release inventory explicitly lists
them.

Development and CI tools are pinned in workflow steps and are not runtime
dependencies. Their own licences and vulnerability state must be captured by
the CI environment for each release. The generated SPDX document describes the
Python distribution, its direct runtime dependencies, and their relationships;
a School-in-a-Box publisher must extend it with every
bundled course, model and binary and record source, version, licence, checksum
and redistribution permission.

Integrity verification does not grant copyright or database rights. Every
Petlja course repository requires an independent content-licence decision before
translation, redistribution, commercial use, or inclusion in an appliance.
