# Six-language CoCreate-style demonstration

This deliberately small, openly licensed fixture proves the six-language
pipeline without claiming to redistribute an upstream Petlja course. Croatian
intentionally omits the range section so the report has a known finding.

```bash
python -m eii audit en sr es pt ca hr --glossary glossary.json --output report
```

Expected: six language releases, two aligned concept groups, a missing Croatian translation,
a terminology status map, and five reusable cross-language assistant fixtures.
