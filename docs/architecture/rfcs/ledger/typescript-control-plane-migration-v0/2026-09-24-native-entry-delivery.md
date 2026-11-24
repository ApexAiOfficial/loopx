# T1/T4: Native outbox entry delivery

The active drainer previously made two source-resolution decisions: Python
classified primary bytes and transported a rebuilt partition; TS checked the
same conclusion under its own locks. One Goal's entire Todo graph therefore
crossed the effect RPC for each captured Todo write.

`shadow_entry_delivery.ts` owns the strict identity/witness selection boundary
and receipt replay. `shadow_entry_evidence.ts` owns recorded partition decoding
and source locks; the existing shadow transaction owner retains lineage,
continuity, CAS and receipt semantics. Missing-marker recovery derives its
resolution under the primary lock and keeps that lock through commit. Existing
resolved transaction assertions remain an internal semantic seam, not a second
RPC format. The old request schema is retired from the active RPC contract;
persisted entry and receipt schemas stay unchanged.

Python's projection/digest builder, source readers and prepared-entry resolution
rules are deleted. Host-specific legacy flock probing remains; it cannot decide
whether the transaction committed. Drain budgeting and exact receipt-backed
cleanup remain with their current owner. Default-off capture creates no new
primary effect. The runtime/CLI user flow is unchanged, with existing
`primary_writer_busy` and `outbox_source_unproved` drain feedback preserved.

Native input rejects caller-supplied resolution/projection/source paths,
duplicate lease identities and malformed UTF-8. `TextDecoder` uses fatal UTF-8
validation rather than replacing invalid bytes before JSON decoding. Exact
byte hashes and semantic partition digests keep separate purposes.

No new capability, provider, persisted ACK or promotion authority is added.
This belongs to the existing coordination capture owner and built-in local
outbox profile. No frontend/settings/Lark configuration changes are needed:
those surfaces do not author this package-internal request. Their end-to-end
transport is not newly qualified here. Full-stage evidence and remaining
packages are in the [shared-authority checkpoint](../shared-goal-authority-state-provider-v0/2026-09-24-native-entry-delivery.md).
