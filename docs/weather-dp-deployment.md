# Classroom Weather differential-privacy deployment

## Two publication modes

The default compatibility mode applies Laplace noise to counts after an exact
minimum-contributor threshold. It protects released count values but the set of
cells that appears is data-dependent, so it is **not** an end-to-end differential
privacy claim.

For end-to-end central DP over cell selection and counts, operators must supply a
fixed, public cell-universe file with `--public-cell-universe`. Every declared
cell is released, including cells whose internal count is zero. Events outside
the declaration fail closed. The store additionally bounds the number of cells
to which one contributor can contribute per course and UTC day. This increases
internal linkage from cell/day to course/day; the keyed pseudonym remains local,
short-lived, and absent from exports.

The universe must be designed from the curriculum before inspecting classroom
events. Deriving it from observed events would reintroduce the selection leak.

## What epsilon means here

`dp_epsilon` is the privacy cost of one non-memoized publication. Smaller values
provide a stronger indistinguishability bound and more noise. Under pure
epsilon-DP, the likelihood ratio for neighboring datasets is bounded by
`exp(epsilon)`: approximately 2.72 at epsilon 1.0 and 1.65 at epsilon 0.5. This is
not a direct “probability of re-identification,” and no honest conversion exists
without an explicit attacker model and prior knowledge.

`dp_total_epsilon` is a basic sequential-composition ceiling for one database
lineage. The defaults are engineering starting points, not universally safe
values. A deployment must choose them through a documented privacy and utility
assessment considering cohort size, release frequency, contribution bounds,
universe size, auxiliary knowledge, recipients, and acceptable uncertainty.

For the fixed-universe mechanism, one event can affect at most three released
cells by default. The event-count sensitivity is therefore 9 (three cells times
three bounded events), while contributor-count sensitivity is 3. With Laplace
noise, expected absolute error is `sensitivity / epsilon`, and 95% of absolute
errors are below approximately `3 × sensitivity / epsilon`. At epsilon 1.0 this
means expected/95%-bound errors of 9/27 events and 3/9 contributors; at epsilon
0.5 they are 18/54 and 6/18. For a 15-, 30-, or 60-person class, the epsilon-1
95% contributor-count error of 9 is respectively 60%, 30%, or 15% of the whole
class. These are utility illustrations, not re-identification probabilities.

For a typical class, do not publish merely because a numerical default permits
it. Start with epsilon 0.5 or lower, a small fixed universe, one release per
reporting period, and simulated utility tests. Increase privacy cost only after
the data protection lead and educational users document why the lower-cost
output is unusable.

The mechanism follows the Laplace mechanism and basic composition described in
[Cynthia Dwork and Aaron Roth, *The Algorithmic Foundations of Differential
Privacy* (2014)](https://privacytools.seas.harvard.edu/book/reading-algorithmic-foundations-differential-privacy),
and should be assessed using [NIST SP 800-226, *Guidelines for Evaluating
Differential Privacy Guarantees*](https://csrc.nist.gov/pubs/sp/800/226/final).
These references define
the mathematics; they do not approve EII’s deployment choices.

## Database lineage and cloning

Each Weather database contains an instance identifier and append-only lineage
history. The production CLI requires a stable
`--database-instance-id` from protected deployment configuration. Opening a
clone under another identifier fails closed. `--allow-database-fork` records an
explicit parent/child transition and is a break-glass action: it does not make
budgets across independently operating clones compose automatically. The
operator must coordinate or conservatively account for all branch expenditure.

Backups intended only for restoration retain the same instance identifier.
Never run a restored copy concurrently with its source unless the institutional
privacy owner has approved and recorded the fork.
