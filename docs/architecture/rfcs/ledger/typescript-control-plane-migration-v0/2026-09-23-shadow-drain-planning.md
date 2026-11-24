# T3: One owner for receipt-proven shadow drain recovery

The migration gap was duplicate recovery authority: TS validated the complete
File shadow lineage, then Python received its transaction history and separately
interpreted receipt continuity, cursor anchors, replay budgets and commit ACKs.
`coordination/shadow_drain_plan.ts` now owns those decisions. Its existing drain
caller sends filesystem identities and raw-byte digests; TS obtains history from
the native verifier and returns checkpoint, reclamation and pending-entry plans.
Historical transactions and full projections no longer cross this drain RPC.

The owner is the existing coordination runtime-shadow boundary, with the built-in
File shadow provider. There is no new capability, extension, configuration, CLI
flag or persistent format. The internal request/result v0 pair ships together.
`authority-shadow drain`, inline post-write drain and their existing CLI feedback
consume the same planner; frontend configuration does not change because this
is neither a new setting nor a new user action.

Python retains the source-specific adapter: source readback, primary/maintenance
locks, filesystem observation, byte revalidation, durable cursor writes and
unlink. It releases the maintenance lock before native commit, then reacquires
it for exact ACK readback. The read-only planner does not take that lock again.
A plan is not an unlocked deletion permit: inventory, cursor and bytes must
still match under both locks before effects.

The related semantic repair moves complete raw-byte revalidation before cursor
writes. A formatting-only JSON change after proof formerly escaped decoded-object
comparison: unlink failed, but the cursor could already have advanced. Now the
checkpoint and residue remain untouched in that case. The existing reclamation
byte check is shared with pre-checkpoint validation, not copied.

Characterization covers receipt identity, interleaved partition sequences,
no-op applied markers, corrupt tails outside the budget, marker-only residue,
ACK mismatch and process crash recovery. Real File tests retain the full native
and legacy production-scale Todo populations. A synthetic 4,000-receipt proof
exceeds 2 MiB while its empty-backlog plan remains under 2 KiB; this tests response
amplification, not long-history provider capacity.

This retires Python's history/proof interpretation, not all legacy source codecs.
The existing native 10,000-transaction verification ceiling and verifier cost are
unchanged. Response size depends on pending/recovered entries rather than all
settled history. Large backlog admission and sustained qualification remain their
existing boundaries. See the paired [authority checkpoint](../shared-goal-authority-state-provider-v0/2026-09-23-shadow-drain-recovery.md).
