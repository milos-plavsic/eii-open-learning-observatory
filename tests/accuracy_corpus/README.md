# Golden multilingual accuracy corpus

This corpus is a correctness gate, not a determinism fixture. Each case declares
findings that must be present and findings that must remain absent. Clean cases
also set a severity threshold above which no finding is permitted. Labels are
human-authored and must be changed only with an explained review in the same pull
request. Synthetic cases are clearly marked; real-course cases require recorded
licence and reviewer provenance.

Cases marked with `maximum_finding_severity: none` are known-clean translations
and fail on any emitted finding. The corpus contains both focused regressions and
six-language, multi-signal fixtures. Add every confirmed false positive here
before fixing it. Corpus-shape tests enforce unique identifiers, declared
provenance, all six supported languages, positive labels, and multiple clean
negative cases so the gate cannot be weakened accidentally.
