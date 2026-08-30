# ADR-014: manual-edit marker for component sources (`emblab modify`/`reset`)

## Status
Accepted

## Context
Several components intentionally pin a floating `ref` (e.g. `master`) rather
than an exact SHA (see Open questions in CONTEXT.md) — upstream moving that
ref is by design, and `sources.ensure_source()` already re-clones when it
detects that (`git ls-remote` vs. the local `HEAD`). That re-clone is a
`shutil.rmtree(dest)` followed by a fresh `git clone`: it has no way to tell
"upstream moved" apart from "someone is mid-way through hand-editing this
tree under `workspace/src/<path>`" — both look like a normal, trackable
source dir. A build run (or even just `emblab fetch`) while a component was
being hand-patched for local debugging would silently discard that work the
moment the pinned branch got a new upstream commit.

Reported directly: refetching happens "even if nothing changed" from the
user's point of view (they didn't touch anything locally) but is in fact
correct per the existing ref-moved check — the actual gap is that there is
no way to tell the driver "leave this one alone for now."

## Decision
Add a Yocto `devtool modify`/`devtool reset`-style escape hatch, scoped to
one component's source tree:

- `sources.mark_modified(workspace, component)` — requires the component
  already has a real clone on disk (raises `EmblabError` otherwise, pointing
  at `emblab fetch`); drops an empty `.emblab-manual-edit` marker file into
  the source dir.
- `sources.ensure_source()` checks that marker **first**, before its
  existing ref-moved/patches-changed logic, and before the new `force`
  parameter (below) — if present, it logs and returns the tree exactly as
  it sits on disk, with zero git calls (no `ls-remote`, no clone, no patch
  reapply). This ordering is deliberate: a marked component must survive
  even a `force=True` caller, so the only way back to driver-tracked
  fetching is through `mark_finished`.
- `sources.mark_finished(workspace, component)` — removes the marker if
  present (a no-op, logged, if it isn't). It does **not** itself re-clone;
  the tree is handed back to normal tracking, and the *next*
  `ensure_source()` call re-clones only if the pinned ref actually moved or
  `patches` actually changed while the component was marked — same rule as
  any other component, just deferred.
- `ensure_source()` gained a `force=False` keyword: `force=True` re-clones
  unconditionally even if neither the ref nor patches changed. Only used by
  the CLI's `--reclone` flag below; `build.py`'s existing calls are
  unaffected (they never pass it).
- CLI: `emblab modify <component>` and `emblab reset <component>
  [--reclone]`. `--reclone` calls `mark_finished()` then immediately
  `ensure_source(..., force=True)`, restoring a pristine, driver-cloned
  tree on the spot instead of waiting for the next natural ref/patches
  change to trigger it.

## Consequences
A component someone is actively hand-editing is now completely inert to
`emblab fetch`/`emblab build`/`emblab run` — no network calls, no risk of a
concurrent upstream commit wiping the edit — until they explicitly run
`emblab reset`. This is a new manual step, not automatic: forgetting to
`reset` means that component silently stops tracking its pinned ref/patches
until someone notices.

`mark_finished` without `--reclone` intentionally leaves the edited tree in
place; if the ref didn't move and patches didn't change while marked,
`ensure_source` will report "up to date" and keep the hand edits, same as
if they'd never been marked at all. This is the expected way to permanently
graduate a local experiment into the tracked tree (edit, mark, edit more,
reset, keep building against it) — deliberately not "reset always wipes."

`--reclone` is the explicit opt-in for the opposite intent — throw the edit
away, get back exactly what the manifest says. It reuses the same
`shutil.rmtree` + clone + submodule-init + patch-reapply path `ensure_source`
already had, so it isn't a second code path to maintain.

Doesn't touch `state.py`'s component/setup/image markers or `build.py`'s own
`--force`/`--setup-force` — this is purely about `sources.py`'s fetch
freshness check, one layer below all of that.
