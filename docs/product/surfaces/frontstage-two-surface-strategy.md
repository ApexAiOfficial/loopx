# Public Presentation and Personal Workspace

Frontstage is retired as a standalone product surface. Personal Workspace owns
operator workflows; the homepage and case directory own public discovery.
The old showcase and Ops board implementations and their dedicated styles are
removed. Keep compatibility redirects for existing bookmarks.

## Current owners

| Surface | Purpose | Entry |
| --- | --- | --- |
| Homepage | Product overview, research and case discovery | Hosted `/` |
| Personal Workspace | Goals, Tasks, Chat, outputs and reports | `loopx dashboard` |
| Product demo | Workspace video and operating guide | `docs/guides/personal-workspace-user-guide/` |
| Research | SWE-Marathon and DeepSWE behavior analysis | `benchmarks/` links from the homepage |
| Case directory | Catalog cases, interactive pages and evidence boundaries | `docs/showcases/index.en.html` and `index.html` |
| Projection developer tools | Static contracts, projection diffing and fixture examples | `/developers/projections` |

## Compatibility

In the dashboard app, `/frontstage` redirects to the public case directory;
`mode=developer` and `/frontstage/developer` redirect to contributor tools.
`mode=ops` and `/deprecated/frontstage/ops` redirect to Personal Workspace,
preserving `goalId` and a validated relative or loopback `statusUrl`. Invalid
sources show an error before the workspace loads. Old board-specific filters
are dropped because the workspace owns task navigation.

On static hosting, `/frontstage/` redirects to the case directory,
`/frontstage/developer/` to contributor tools, and `/deprecated/frontstage/ops/`
to the workspace guide. All hosted aliases discard query parameters; legacy
`mode=ops` links on public hosting cannot activate local inspection.

## Public/private boundary

Public presentation uses reviewed articles, the showcase catalog, and public
assets. It must not load live registry state, status URLs, raw sessions,
credentials, or browser write APIs. Compatibility links do not add authority.
Workspace demos should reuse current product components with synthetic data
when an interactive demo is needed, rather than create a second operator UI.

The case catalog and existing case pages retain the public evidence and
narratives previously repeated in Frontstage. Shared projection schemas and
fixtures remain available to their existing consumers; retirement does not
change their semantics. The homepage must not promote deprecated destinations.

## Validation

Run the route and browser migration smokes, public share-bundle boundary smoke,
Personal Workspace smokes, and production builds. Browser checks cover both
root and repository-prefix hosting, mobile and desktop, English and Chinese,
and negative status-URL cases. Preserve static redirects without a JavaScript
requirement and verify their destinations exist after the documentation build.
