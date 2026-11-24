# Event replay integrity and the remaining cutover work

Owner: overall roadmap #4574 R1/R5, shared authority L7/L8 and TS migration T3.
Baseline: `2e1e63260`, 2026-09-25. PR states below are an inventory at this
checkpoint, not a promise of acceptance or a continuously updated counter.

## Delivered boundary

The legacy event source had independent Python state rules. A second
`todo_added` with a different event identity could overwrite a completed Todo;
a priority-only update left old text, a role update left its old source section,
and planner order zero sorted as missing. Four independent counterexamples fail
on the baseline and pass with the typed replay owner.

`goals/state_event_replay.ts` owns ordered replay admission, Todo identity,
lifecycle, role/priority, binding immutability, exclusive addressing and removed
continuation-policy repair. Python retains legacy value decoding, content,
checksums and rendering. The runtime receives compact facts and content-field
names; the returned field-source ordinals address that same immutable batch.
Evidence, validation commands and arbitrary payload bodies do not cross this RPC.
One large evidence regression preserves more than 2 MiB of content with under
4 KiB of replay facts. The adapter folds at most 256 events per call, carrying
only the affected Todo continuation rows. A 4,100-event history crosses 17
calls without losing original fields or duplicate-creation protection. Individual
facts and continuation rows remain subject to the existing RPC budget; no
unlimited per-field size is promised. Historic byte/checksum ordering remains
in the legacy codec; TS returns the final display sort keys.

Exact duplicate event identities retain existing codec replay/conflict behavior.
Different create events targeting one Todo now reject with an actionable update
instruction. Invalid role/priority and unsafe sequence/order facts reject instead
of producing an ambiguous typed projection. Existing stored logs are not
rewritten. Reverting restores the earlier reader; no storage migration is needed.

A detached real-source rehearsal preserves the complete baseline projection and
checksum, with 900 backfilled events and 398 Todos. A disposable registry and real
CLI read back an original record. The original source stays unchanged. Synthetic
mixed history covers dependencies, validation declarations, claims, deferred and
completed work, independent review, owner work, attribution and all event kinds.
Seven alternating warm samples on the same detached input measured median
9.28 ms before and 66.12 ms after. This is an explicit RPC/type-owner cost, not
a speedup. No latency budget was increased; wider cold/throughput qualification
is not claimed. Existing compaction, Markdown-backfill, task-graph and API smokes retain their
original assertions. File/SQLite caller regression remains real, not in-memory.

This does **not** append or bind event writes to the outbox. The
`event_log_writer_not_bound` hold remains. #5003 owns atomic append/completion;
this change does not reproduce its writer or change its persistent event schema.
No provider default, live promotion, PostgreSQL store or external executor changes.
The existing source-readback type narrowing also matches the small correction
already carried by #5012/#5013; it adds no new projection rule.

## Count requirements, open implementations and evidence separately

The older 5–8 / 7–9 estimates mixed units and must not be reused. The reconciled
inventory in #5006 already identifies source transport as implemented on an open
branch. It is not unstarted work. The remaining *planned new code deliveries*
are four including this event-replay slice:

| Planned PR boundary | Exit | After this delivery |
| --- | --- | --- |
| Event replay integrity (this PR) | One typed replay owner; corruption counterexamples and real-source parity/readback | Ready for review, not merged |
| External-effect executor fence | Audit real executor consumers; prove how current execution ownership protects the actual effect interval and uncertain result recovery | Unstarted; downstream idempotency/fencing must be explicit, a pre-call check alone cannot promise this |
| Event-writer binding + integrated whole-Goal migration/rollback | Reuse #5003/#5006, bind actual writer locks/publication to outbox, mixed-writer crash/replay/drain, canonical consumers and fenced rollback on one exact revision/profile | Unstarted; this replay slice closes a proven reader gap within that boundary, not capture admission |
| Default/onboarding + bounded Python retirement | Qualified profile selected by new-Goal creation/settings/install and packaged entrypoints; explicit existing-Goal migration and rollback; delete only writers with no remaining legal callers | Depends on preceding acceptance and applicable D1–D3 |

Thus **three planned new implementation boundaries remain after this PR**;
that is not an assertion that three more merges enable a global default.
Combining writer binding and migration is a plan to verify; if their integration
reveals a defect, record the concrete defect and revised boundary here rather
than keep a floating range. The replay slice is separated because its source
reader and state rules are independently testable/reversible while #5003's
writer is still under review. It also fixes shipped behavior immediately.

Existing open work to integrate, not implement again:

- #5006 complete source transport; #5003 atomic event completion; #5011 observer
  retirement: three source/authority integrations.
- #4991, #4992, #4995: three quota/lease caller repairs. #4994 merged during
  this delivery and is now included in the rebased baseline, not the open count.
- #5005, #5012, #5013: three demonstrated long-horizon recovery fixes. These are
  relevant R1 reliability work, not three additional storage implementations.
- #4931 and contributor-owned #4224: SQLite D2 performance/qualification.
  #4915 changes local filesystem placement, not authority selection; #5010/#5008
  are release/platform integration work, not unstarted provider implementations.

D2 has a measured 1 MiB receipt/scan failure and outstanding recovery, lag,
restore/upgrade, runtime/OS and elapsed-soak evidence. A stated soak end date is
not a verified final result. Its further PR count cannot be inferred from this
inventory. D1 command/consumer coverage and D3 exact-profile/cohort acceptance
also remain evidence gates. Do not add them to code PR counts or subtract them
because an unrelated refactor merged. Maintainer approval is needed for actual
cohort cutover; this task does not modify an active Goal.

PostgreSQL already implements the provider contract. Deployed authentication,
tenancy, operations/restore/failover and capacity qualification remain separate
medium-term outcomes. Local default does not wait for that deployment; provider
conformance alone is not a production service qualification.
