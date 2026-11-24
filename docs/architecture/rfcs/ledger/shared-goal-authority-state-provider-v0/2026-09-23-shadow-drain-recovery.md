# L7: Native drain decisions before whole-Goal migration

This slice removes the second interpretation of proved shadow history from the
Python drainer and repairs byte-change detection before checkpoint effects.
It supports the existing whole-Goal sequence: capture legacy writes, drain the
candidate, qualify exact lineage, fence legacy writers, migrate the reviewed
snapshot and verify canonical consumers. Recovery of a committed transaction
must not become another mutation or a provider-promotion approval.

The accompanying [TS checkpoint](../typescript-control-plane-migration-v0/2026-09-23-shadow-drain-planning.md)
records ownership, lock ordering and transport limits. Real public CLI crash
recovery uses a disposable copy of a complete source population; File and SQLite
canonical readback is checked independently. No active Goal, writer fence or
registry is promoted by this validation. These checks do not substitute for a
reviewed cohort migration, sustained mixed-writer qualification or SQLite D2.

The remaining **5–8 cohesive PR packages** estimate is still conditional:

| Delivery package | Estimate | Decisive remaining outcome |
| --- | --- | --- |
| L2/L3 caller adoption and executor fences | 1–2 | Every shipped caller uses the qualified owner and rejects stale writers. |
| L5/D1 consumer and projection closure | 1 | CLI, packaged clients and projections read canonical state consistently. |
| L6 SQLite D2 | 1–2 | Contributor-owned capacity, crash, restore and genuinely elapsed sustained-run evidence. |
| L7 continuity plus L8 whole-Goal migration | 1–2 | Mixed-writer continuity, reviewed cohort migration and fenced export/rollback. |
| L9 defaults and bounded Python retirement | 1 | New-Goal defaults, onboarding, compatibility guidance and deletion of writers whose final callers have migrated. |

This PR improves L7 and retires a concrete Python rule group; it does not close
one of those complete packages by itself. The required at-least-ten-day SQLite
soak cannot be replaced with more synthetic transactions. PostgreSQL remains a
separate service/credential/tenant and operational qualification path, while the
provider-neutral promotion and canonical-read contracts remain reusable.
