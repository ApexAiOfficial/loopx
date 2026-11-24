# T3 archive capture keeps compatibility decoding separate from authority

The existing `todos/archive_capture.ts` owner now admits a legacy read class
only when the source records an Agent role. Python reuses the established
Markdown classifier and transports a compact classification, not source prose;
TS still owns identity admission, authority contradictions and dependency closure.
The result carries the selected class so Python does not independently choose it
after admission. No new capability, provider, CLI option or frontend state owner
is introduced. The shipped entry points are `todo archive-completed`, shadow
bootstrap and writer-outbox capture; the generic CLI error surface remains valid.

The related simplification is one class-resolution rule for inferred successor
indexing and record selection, plus reuse of existing Markdown normalization for
archive writes. The prose classifier itself remains legacy compatibility code;
its later T3 retirement needs active-read parity and is outside this admission
repair. No new prose-based authority rule is added.

See the paired [authority checkpoint](../shared-goal-authority-state-provider-v0/2026-09-23-archive-classification-continuity.md)
for whole-source evidence and remaining promotion boundaries. Internal request v2
and result v1 require the bundled Python/TS pair; persisted historical receipts
are unchanged. Synthetic negative cases retain missing-user-role rejection,
explicit-class precedence, deferred non-completion and duplicate-identity holds.
