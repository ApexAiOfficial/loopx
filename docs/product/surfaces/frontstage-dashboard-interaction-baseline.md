# Public Presentation Interaction Baseline

The [surface strategy](frontstage-two-surface-strategy.md) owns route migration.
Personal Workspace is the operator product; the homepage, research pages, and
case directory are the public presentation. Frontstage's duplicate showcase
and Ops boards are retired.

## Navigation

- Homepage exploration exposes Personal Workspace's video and guide,
  SWE-Marathon, DeepSWE behavior analysis, and the full case directory.
- English and Chinese navigation use the corresponding localized pages where
  available; the DeepSWE article is identified as Chinese in English copy.
- Contributor tools remain discoverable at `/developers/projections/`.
- Direct fragment URLs must land on the rendered section after the React shell
  mounts, including cold loads and reloads. Fragment targets must remain visible
  and stationary during entrance effects. Browser tests must assert the initial
  viewport before calling any scroll or focus helpers; checking URL text or
  clicking a link after render does not validate a shared deep link.
- Both React pages share fragment restoration after mount and language reflow.
  Back/forward navigation restores the URL language; section actions use native
  links so they create normal history entries. Explicit `index.html` research
  URLs select the same page as directory URLs. Research navigation stays sticky,
  with fragment destinations below the bar; decorative overflow must not create
  an intermediate scroll container.
- Late font reflow may correct the initial destination once; user input or a
  subsequent navigation cancels that correction so reading is never interrupted.
- Do not link primary navigation to retired or deprecated surfaces.
- Old bookmarks redirect to the current owner; public aliases discard live
  status parameters instead of passing them into the local workspace.

## Visual and interaction rules

Follow [the design system](../../development/design.md). Reuse existing
homepage learning cards, typography, spacing, keyboard focus, and mobile menu.
Resource cards collapse to one column on phones. Preserve the hero and primary
setup action while making public resources easy to find.

Personal Workspace owns task navigation, status sources and write affordances.
Retiring the old boards does not change those contracts. Developer tools stay
read-only and independent of live status state. Public product demonstrations
must label synthetic data and reuse the current workspace if expanded.

## Checks

`smoke:frontstage-route` protects retired-route ownership and source isolation;
`smoke:frontstage-browser` exercises migration, current homepage navigation,
language switching, keyboard focus, and narrow layouts in a real browser.
`smoke:frontstage-share-bundle` checks the production export and its public
boundary. The historical script names remain compatible for existing CI.
