# Public schema publication

The files under `schemas/` are authoritative source documents. Their immutable
`$id` URLs map by basename to generated files under `public/schemas/`. Run
`python tools/build_schema_site.py` after any schema addition and run it with
`--check` in CI. The web deployment for `eii.edu.eu` must publish `public/` with
`Content-Type: application/schema+json`, must not redirect schema paths to an
HTML application shell, and must use long-lived immutable caching for versioned
filenames.

Published schema versions are never edited or deleted. A breaking change gets a
new `$id`; the unversioned repository filename may point at the newest schema,
while old public artifacts remain present.
