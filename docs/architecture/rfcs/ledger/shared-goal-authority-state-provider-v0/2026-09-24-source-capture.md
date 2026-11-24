# Complete source capture has one typed assembly owner

Goal: overall-roadmap G2/R5 and shared-authority L7. A migration snapshot must
represent a complete, unambiguous source before it can serve as promotion
input. This change closes source assembly, not event-writer continuity, D2/D3,
existing-Goal migration or a provider default.

`coordination/source_projection.ts` now owns the complete Todo partition and
whole coordination snapshot: record identity, strict consumer fields, Unicode
ordering, current-graph lease membership and the revision-bound read manifest.
The native source verifier rebuilds the same shape before checking locked source
bytes. Todo-partition folding uses the same current-graph membership helper.
Python retains source IO, Markdown/archive normalization and exact-byte
witnesses; it sends one complete collection, not one RPC per record.

Behavior changes:

- Missing/non-array Todo collections, malformed rows and missing IDs reject;
  they cannot silently turn into empty evidence.
- Duplicate Todo/lease identities reject. Lease identity and explicit Goal
  identity are checked before retained-history filtering, including rows that
  would otherwise be discarded.
- Float values remain rejected. Integers outside the common safe range now
  reject in Python before JSON transport and in the typed source decoder.
  JSON parsing must not silently round a source integer before its digest.
- Valid semantics stay unchanged: archived Todo dependencies remain records;
  only leases whose Todo belongs to the active section enter the current graph.
  A released or expired lease for a retained Todo is not discarded merely for
  being inactive: it carries generation history. Query-only succession
  evaluation is excluded; unknown machine-owned fields reject.

No persisted schema, source lock order, authority choice or mutation permission
changes. The existing 2 MiB RPC limits remain. The extra assembly RPC is migration
and legacy capture overhead; it is not a new provider call or a claimed speedup.
Delete this Python transport with its final legacy capture caller. Keep source
import/export and exact byte verification while their callers remain.

Validation uses independently authored rejection cases, the shared mixed
production-scale fixture across real provider implementations, and isolated
source-copy CLI/readback. Failed and missing durability evidence remains a hold.

## Remaining local-default delivery program

The estimate is still **5–8 delivery PRs**, conditional on actual integration
findings, in addition to reviewing the existing open prerequisites. These are
outcomes, not a promise to manufacture that many changes.

| Package | PRs | Exit |
| --- | --- | --- |
| Public caller coverage | 1–2 | Reconcile CLI/Turn/Chat mutations and actual external-effect consumers. Distinguish legacy locks from canonical CAS; do not invent an unused executor framework. |
| Consumer/display closure | 1 | Integrate the open projection recovery, full-source summary and snapshot paging work; prove stale/missing display, complete sources and affected packaged clients. |
| SQLite D2 | 1–2 | Contributor-owned #4224: close capacity, crash/restore/upgrade, lag, supported runtime/OS and elapsed-soak gaps on one selected profile. |
| Capture continuity and whole-Goal rehearsal | 1–2 | Mixed writers/event sources, restart/replay, capture drain, old-writer fencing, canonical readback and fenced export/rollback on one exact revision. This capture assembly is a prerequisite, not full L7 acceptance. |
| Default and bounded retirement | 1 | New-Goal creation/settings/install select the qualified local profile; retire old business writers only after final callers and migration windows close. |

File remains an explicit reference profile; SQLite remains the long-lived local
default candidate. PostgreSQL already has an implementation and scoped factory,
but its service authentication, deployment/restore/failover and capacity
qualification remain independent medium-term work. Passing provider conformance
is neither local-default acceptance nor permission to cut over an active Goal.

Measured tradeoff: with the same parsed 1,018-record input over seven warm assembly samples, median assembly moved from about 35 ms to 186 ms. This adds one batch RPC and is not a speedup claim. Semantic source digests and isolated File/SQLite readback match; the real bootstrap CLI on a disposable copy verifies all 188 source lease files while retaining nine current-graph leases. Existing record/manifest compatibility remains; no budget increase or D2 long-running experiment was performed.
