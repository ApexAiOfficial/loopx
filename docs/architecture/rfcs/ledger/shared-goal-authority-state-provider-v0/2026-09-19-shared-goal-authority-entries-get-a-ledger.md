# Shared-goal-authority delivery records get a ledger directory

Non-normative for the shared Goal authority model: it adds no runtime invariant.
It relaxes one condition the ledger check imposed — a ledger directory had to
name an RFC whose *Appendix A* is the execution ledger — and points this RFC's
future delivery records at files.

- **The cost was measured by the maintainer, not by this entry.** #4677 surveyed
  every open PR against `origin/main = d8e7af141` on 2026-09-17 and found 19 of
  34 heads `mergeStateStatus=DIRTY`, three of them (`#3820`, `#4061`, `#4672`)
  colliding on this one file. This entry re-measures no head: GitHub computes
  mergeability lazily, so a same-day recount is not available without forcing a
  computation per PR.
- **Why records collide in this file.** Delivery records for this RFC are dated
  subsections inside Appendix C — `Provider-first terminal lifecycle checkpoint
  (2026-09-07)`, `Cross-RFC semantic and presentation conformance checkpoint
  (2026-09-12)`, `Next delivery and parallel provider work`. They sit at the end
  of a 3,125-line English file and a 2,474-line Chinese one, so two branches
  recording a delivery insert at the same position by construction.
- **The convention already existed and could not be adopted here.**
  `check_rfc_ledger_entries` in `examples/docs-governance-smoke.py` required a
  ledger directory's RFC to contain the literal heading
  `Appendix A: Execution ledger`. This RFC's Appendix A is
  `What This Evidence Proves`, so per-file entries would have meant renumbering
  Appendices A-C across both language files — a large mechanical diff that
  itself forces rework on the branches the change exists to help. The check now
  accepts `Appendix <letter>: Execution ledger` in the English document, and this RFC's
  Appendix D is the pointer.
- **Existing records stay put**, for the reason the semantic-vocabulary round
  recorded on 2026-09-18: they are append-only history nobody edits, so they
  were never the thing a later branch conflicts with — the shared insertion
  point ahead of them is.
- **What this does not do.** It resolves no conflict that already exists; each
  affected branch still rebases once. It does not make a ledger entry
  reviewable evidence — entries remain non-normative records of what a change
  measured and what it did not establish. And it adds no navigation entry: the
  hosted-docs check requires a file for every nav entry, not a nav entry for
  every file.
