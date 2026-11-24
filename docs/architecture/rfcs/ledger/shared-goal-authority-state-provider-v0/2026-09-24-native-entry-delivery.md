# L7: Deliver captured source transactions through one typed owner

The #4574 R5 outcome needs complete, recoverable capture before a reviewed
whole-Goal migration. Previously Python interpreted a prepared record, chose
its resolution, rebuilt its partition and sent that full projection to TS. TS
then read the same durable record and proved its source again before committing.
The active `coordination.runtime_shadow.commit_entry` entry now accepts only
Goal/partition/sequence/lineage identity and exact prepared/marker byte hashes.
TS reads the recorded projection and owns source resolution through commit.

The [TS checkpoint](../typescript-control-plane-migration-v0/2026-09-24-native-entry-delivery.md)
records the retired Python rules and the wire boundary. This changes the
package-internal request, not persisted outbox, history, receipt or cursor
schemas. Upgrade Python and TS together; do not introduce an old-request fallback.

## Delivered boundary

- A committed marker retains its durable meaning. Without a marker, the source
  owner holds the existing primary lock while deriving whether the write landed
  and while committing the candidate transaction. A later source transaction,
  unknown source bytes or ambiguous before/after identity remains a hold.
- A lost response can replay after local outbox cleanup, but only through a
  validated complete lineage and an exact receipt matching the selected bytes.
  Matching an operation id alone is insufficient.
- The TS source-evidence module shares lease identity/ordering and disk checks
  between preparation decoding and final verification. Python retains bounded
  drain scheduling, legacy flock busy detection and receipt-proven cleanup.
- Missing markers, changed witnesses, foreign lease bytes, stale lineages,
  concurrent selectors, malformed UTF-8 and corrupt retained history are covered
  by focused tests. Production-scale native/imported fixtures now enter the
  production delivery API before provider-neutral migration/recovery tests.

An authorized read-only source rehearsal captured 1,018 Todos and 188 lease
files (9 current-graph leases). A disposable real CLI write, process interruption,
native delivery, cleanup and replay produced exactly 1,019 Todos. The selection
parameters measured 554 bytes versus 1,618,597 bytes for the previous request
shape; the 1,734,347-byte prepared record was still read and checked in full.
This is transport reduction, not a latency or unbounded-capacity claim. No RPC
limit increased. Independent File/SQLite consumer copies verify full readback
and CLI reads with missing Markdown; they do not constitute a live promotion.

## Remaining local-default program

The conditional **5–8 cohesive PR packages** remain, in addition to integrating
existing in-review prerequisites. This slice narrows L7; it does not complete
the mixed-writer/event-source acceptance matrix or subtract a whole package.

| Delivery package | Estimate | Remaining acceptance |
| --- | --- | --- |
| L2/L3 actual caller adoption | 1–2 | Audit CLI/Turn/Chat writes and real effect boundaries; retire replaced Python rules with their last callers. |
| L5/D1 consumers and display | 1 | Integrate projection recovery, complete summary and pagination work; verify affected packaged interactions and stale/missing display. |
| L6 SQLite D2 | 1–2 | Continue contributor-owned #4224: capacity, crash/restore/upgrade, consumer lag, supported runtime/OS and genuinely elapsed soak. |
| L7 capture and L8 migration | 1–2 | Qualify sustained mixed writers, resolve event-only source coverage, drain/fence/readback and reviewed cohort export/rollback. |
| L9 default and retirement | 1 | New-Goal onboarding/settings/install select the qualified profile; preserve explicit choice and retire business writers after final callers/migration windows close. |

Reconcile in-review #4961 (display recovery), #4964 (summary owner), #4922
(snapshot pages), #4931 (SQLite read proof), #4960 (Node runtime) and #4967
(complete source assembly), rather than duplicating them. The native delivery
slice starts from main independently of those changes.

Event-only source writers remain explicitly unbound. D1–D3, elapsed SQLite
qualification, existing-Goal cohort approval and new-Goal default selection are
not granted by this change. PostgreSQL reuses the captured-state and recovery
contracts but retains independent authentication, deployment, restore/failover
and capacity qualification. Permanent Markdown rendering/import/export adapters
are not obsolete business writers.
