# Validated Todo publication recovery

Source: #5007. This closes a local create/revision delivery gap in the native
mutation path: provider commit could precede private validator publication, so a
lost response stranded the entire Goal's Markdown projection.

The host now durably prepares immutable, digest-addressed private declarations
before dispatch. Only the canonical Todo's digest selects authority; prepared
but rejected content is inert. Projection and completion share this reader,
with strict legacy sidecar compatibility. TS remains the single owner of Todo
admission, CAS and operation receipts. `todo add --operation-id` provides exact
create recovery without count-derived identities or a second Python journal.
Historical retries cannot revert the current validator.

File/SQLite regression cases cover lost responses, abrupt process exit with
public CLI recovery, later edits/revisions, corrupt selected declarations and
preparation failure before commit. These are isolated synthetic stores, not a
live Goal migration or a PostgreSQL publication test. The change leaves
provider selection, D1–D3 qualification and cross-host distribution of private
commands unchanged. See the [caller contract](../../../../reference/canonical-todo-completion-update.md).
