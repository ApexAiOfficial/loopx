# Explicit leased continuation closes a canonical CLI gap

For #4574 G1/G2 and the shared-authority L2/L3 program, the explicit handoff
caller still rejected every hard-lease Todo even though metadata updates and
atomic claim/lease transfer already owned the necessary execution proof. It
also left committed prepare/adopt state waiting for Markdown delivery.

The same-host CLI now composes those existing owners: prepare with current
proof, transfer claim and lease atomically, then receive context under the new
execution proof. Transfer rebinds only a note valid against its original work
facts. Leased adoption writes a context receipt without changing claim/lease;
receipt replay is separately checked against current execution and acceptance.
Python retains host file IO and projection delivery; the closed context schema
and lease/claim decisions stay in TS. The lease-free path remains compatible.

The [operating contract](../../cross-session-memory-substrate-v0.md#leased-execution-continuation)
describes proof flags, retry/readback and the explicit host/session boundary.
This is not automatic delegation, host launch, independent result acceptance,
external-effect fencing or completion of the manager handoff RFC. No new UI
control is required for this existing CLI-only workflow. Existing Todo display
consumers receive the same record schema via permanent projection.

## Remaining local-default program

Retain the conditional **5–8 cohesive packages**, including integration of
already-open prerequisites. This completes one real caller path within L2/L3
and fixes its display delivery; it does not retire either entire package.
SQLite remains the long-lived default candidate, File the reference/explicit
profile. “New Goal default”, “migrate existing Goals” and “delete all Python”
are separate outcomes.

| Package | Estimate | Observable completion |
| --- | --- | --- |
| Remaining CLI/Turn/Chat callers and actual effects | 1–2 | Close the command matrix, exact execution proof and external-effect boundary; remove each replaced Python business rule with its last caller. |
| Consumer and permanent projection integration | 1 | Full readback/pagination and display recovery through affected packaged entry points; stale or missing Markdown cannot become authority. |
| SQLite D2 qualification, contributor-owned #4224/#4931 | 1–2 | Capacity/receipt/scan budgets, crash/restore/upgrade, platform coverage, consumer lag and at least ten genuinely elapsed days of soak. |
| Source capture plus whole-Goal migration | 1–2 | Sustained mixed writers and event-only coverage, drain/fence/readback, cohort rehearsal and recoverable export/rollback. |
| Default selection and legacy writer retirement | 1 | New-Goal creation/settings/install choose the qualified profile; explicit choices survive; obsolete business writers retire after migration windows close. |

These are delivery packages, not a prediction that five more arbitrary small
PRs finish migration. The elapsed soak cannot be replaced by accelerated tests.
PostgreSQL shares typed command semantics and real backend conformance, but
service authentication, tenant isolation, operations, restore/failover and
capacity remain an independent medium-term qualification. Permanent Markdown
rendering, import/export and host adapters are not duplicate business owners.
