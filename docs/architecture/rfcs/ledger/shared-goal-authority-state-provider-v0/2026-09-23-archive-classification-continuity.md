# Archive classification continuity during whole-Goal capture

This is an R5 / L7 capture-continuity repair under the overall roadmap, paired
with the TS RFC's T3 consumer migration. It does not change D1–D3 acceptance,
provider defaults, writer fences, permission policy or promotion approval.

A valid legacy Agent Todo may omit `task_class`: its active read already resolves
that class. Archive moves preserved its role but omitted the resolved class;
the capture selector then required both fields to have been explicitly recorded.
A reachable historical row could therefore stop bootstrap and every subsequent
writer-outbox capture even though its source role was unambiguous.

The shared TS selector now distinguishes recorded role/class from the codec's
legacy classification. Only a recorded Agent role can adopt the latter; an
explicit class always wins. The selected class drives both inferred successor
closure and canonical materialization. User decisions still require their
recorded authority. Duplicate identity, invalid archive status, contradictory
user scope, absent identity evidence and deferred-versus-done semantics retain
their rejection or unsatisfied outcomes. New legacy Agent archive moves retain
the same read class without rewriting original receipt metadata.

Validation covers baseline counterexamples, transitive and inferred dependencies,
negative authority cases, new archive writes, real CLI bootstrap followed by
writer capture, and File/SQLite canonical reads with the display removed. An
owner-authorized read-only local source rehearsal captured 346 active records,
664 archived dependencies/decisions and 9 current leases; 188 source lease files
remained unchanged, with retired inventory kept outside the current graph.
No active Goal was promoted or rewritten. Private source contents are excluded.

This removes one evidenced full-capture hold. The next boundary remains L7/L8
qualification and reviewed whole-Goal cutover on the intended provider, including
source continuity, drain, fence, rollback and real backend evidence. Passing this
capture does not establish those later gates or delete the legacy Python reader.
