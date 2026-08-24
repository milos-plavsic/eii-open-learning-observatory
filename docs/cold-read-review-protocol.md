# Independent cold-read documentation protocol

This protocol prepares VAL-009. It does not constitute an outside review.

Select at least one reviewer who did not author the software or its documentation
and who represents a target platform, school IT, course-authoring, security, or
procurement audience. Give the reviewer only the public repository URL and a
realistic task; do not coach them through the expected path.

Record the exact revision, reviewer role and independence statement, start/end
times, task, documents opened, commands attempted, questions asked, incorrect
inferences, blockers, and severity. Do not collect learner data or unnecessary
personal information. Ask the reviewer to distinguish unclear wording from a
missing mechanism and to identify every place where cautious qualification was
mistaken for either a guarantee or an unexplained disclaimer.

Minimum tasks are:

1. Explain what works without an external model and what requires one.
2. Run the six-language deterministic demonstration and interpret one finding.
3. Explain the boundary between internal verification and external validation.
4. Identify what evidence would be required before a learner-data pilot.
5. Locate installation, rollback, security-reporting, privacy, and release-key
   procedures without assistance.

For every observation, record disposition (`accepted`, `partially accepted`, or
`rejected`), rationale, owner, target revision, resulting change, and retest. A
different outside reader should retest high-severity comprehension failures.
Publish a privacy-reviewed report or redacted summary and sign it using the
external-validation process. Internal review, issue closure, or an unsigned email
does not close VAL-009.
