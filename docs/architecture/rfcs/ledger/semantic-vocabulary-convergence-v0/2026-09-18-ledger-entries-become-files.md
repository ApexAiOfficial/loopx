# Ledger entries become files

Non-normative for the semantic model; it adds no invariant and changes no
check's verdict on any tree. What changes is where an execution-ledger entry
lives.

- **The problem was measured, not anticipated.** RFC Appendix A was one append
  cluster. During the #4447 repair round, four branches each added an entry and
  every pair conflicted at the same position — eight resolutions in one
  afternoon, all of the form "the two sides are disjoint additions, keep both".
- **The failure mode is silence.** A conflict that is always resolved the same
  way stops being read. The resolution that drops an entry looks exactly like
  the seven that did not, and nothing downstream notices: no code parses
  Appendix A, so a lost entry surfaces only when someone goes looking for a
  record that is no longer there.
- **A file per entry removes the shared line.** Two branches adding entries on
  the same day now touch two different files and merge with no resolution.
- **Nothing enumerates the entries.** An index in the RFC would be a one-line
  append cluster — smaller than the original, but the same class of problem.
  The directory listing is the index, and the `YYYY-MM-DD-slug` name sorts.
- **The convention is checked, not described.** `check_rfc_ledger_entries` in
  `examples/docs-governance-smoke.py` requires the dated name, a Chinese mirror
  beside each entry, and non-empty content. Verified by mutation: a file named
  `badname.md` and an entry with no mirror each fail the smoke.
- **Existing entries were left in place.** The entries already in
  Appendix A are append-only history that nobody edits, so they were never the
  thing that conflicted. Migrating them would have produced a large mechanical
  diff, forced rework on the one open #4447 branch, and fixed nothing.

What this does not do: it does not make ledger entries reviewable evidence.
They remain non-normative records of what a change measured and what it did not
establish. It also does not add them to the hosted documentation navigation —
the nav check requires a file for every nav entry, not a nav entry for every
file.
