# Replan consumer checkpoint and default-path estimate

The replan history decision family now shares a TS owner across legacy and
canonical consumers. See the [TS checkpoint](../typescript-control-plane-migration-v0/2026-09-22-replan-history-policy.md)
for the four semantic fixes and isolated real-source readback. This advances T3;
it does not establish a new provider durability, capture, or promotion claim.

The planning range remains **5–8 cohesive delivery packages**, conditional on
acceptance rather than line counts: remaining caller/executor fences (1–2),
consumer/projection recovery (1), SQLite durability and qualification (1–2),
whole-Goal capture/migration (1–2), then default onboarding and bounded retirement
(1). These categories can overlap in a complete package; their maxima are not
independent additive promises. The current history slice does not retire an
entire package. The existing SQLite long-running qualification owner (#4224)
and the required elapsed soak remain dependencies.

A complete capture attempt exposed a still-open archive dependency role/class
hold. Active read-model parity is useful but cannot discharge this hold. Existing
Goal migration must keep its exact-source qualification, old-writer fence and
rollback acceptance; no active Goal was promoted for this validation. PostgreSQL
remains separately qualified and opt-in; this PR changes no store transaction,
connection, selection, schema or migration contract.
