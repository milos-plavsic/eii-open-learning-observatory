# Golden multilingual accuracy corpus

This corpus is a correctness gate, not a determinism fixture. Each case declares
findings that must be present and findings that must remain absent. Clean cases
also set a severity threshold above which no finding is permitted. Labels are
human-authored and must be changed only with an explained review in the same pull
request. Synthetic cases are clearly marked; real-course cases require recorded
licence and reviewer provenance.
This corpus is an output-accuracy gate, not a determinism fixture. Each case
labels findings that must occur and findings that must not occur. Cases marked
with `maximum_finding_severity: none` are known-clean translations and fail on
any emitted finding. Add every confirmed false positive here before fixing it.
