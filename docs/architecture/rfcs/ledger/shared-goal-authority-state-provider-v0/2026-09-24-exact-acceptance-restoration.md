# Exact acceptance restoration without a lease cycle

Source: #4971. An Agent could clear an owner-confirmed Todo's existing wait while
holding a hard lease, release it, and then be unable to restore it: stale
acceptance prohibited acquire, while update demanded an active lease.

The existing TS reviewed-update boundary now admits a narrow restoration after
ordinary registered actor / claim / exclusion checks. With no active lease or
supplied execution proof, the same claimed Agent may restore prior text/wait
only when the candidate's complete work digest equals the current owner binding.
The provider revision CAS and existing operation receipt guard the transaction;
criteria, binding, lifecycle and lease generation are unchanged. Historical
schema-less lease records are normalized once at the shared TS read boundary
so activity checks cannot mistake a live lease for an inactive one; deferred
reopen reuses that normalization instead of injecting the tag itself. Execution still
requires a new ordinary acquire. Unknown prior values or other scope changes
project an explicit owner-review/rebind requirement.

This advances native long-horizon recovery, not provider default selection or
D3 promotion. Real File/SQLite CLI regressions exercise acquire, stale edit,
release, rejected reacquire, restoration and fresh acquire; provider tests also
exercise a disposable PostgreSQL server. Managed frontier projection drops the
stale hold after restoration. The original managed Turn then completes its Todo,
writes back and settles; replaying restoration and spend consumes quota once.
#5000 remains separately owned by Turn settlement
and its retry policy; restoring acceptance does not settle a Turn.

See the [caller contract](../../../../reference/goal-acceptance-observations.md#restore-an-unintended-textwait-edit-after-lease-release).
