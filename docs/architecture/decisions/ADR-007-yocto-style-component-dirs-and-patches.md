# ADR-007: Yocto-style per-component directories, and build.patches

## Status
Accepted

## Context
ADR-005 gave each component a `manifests/files/<component>/` directory for
static assets (Kconfig fragments, `.its` templates), separate from its
`manifests/components/<component>.yaml` manifest. Two components now need
patches applied to their cloned source before building (a real, in-progress
`optee-os` fix among them) — patches are inherently per-component, ordered,
and belong to the same component they modify, and having their home
(`manifests/files/<name>/`) live in a whole separate top-level tree from the
manifest that declares them (`manifests/components/<name>.yaml`) was already
a minor case of "related things living apart"; adding patches on top made it
worth fixing rather than compounding. Yocto's own recipe layout —
`recipes-*/<pn>/<pn>.bb` next to a sibling `recipes-*/<pn>/files/` holding
that recipe's own patches — is the well-known solution to exactly this, and
`emblab` borrows it directly.

## Decision
- Every component now owns a directory:
  `manifests/components/<name>/<name>.yaml`, with a sibling
  `manifests/components/<name>/files/` holding that component's own patches
  and static files. The separate top-level `manifests/files/` tree from
  ADR-005 is gone — `manifests.files_dir()`/`component_file_path()` now
  resolve into the component's own directory instead.
  `manifests.component_path()`, `list_names("components")` (which now globs
  `*/*.yaml` instead of `*.yaml`), and every test fixture were updated to
  match. Images and targets are unaffected — they stay flat
  (`manifests/images/<name>.yaml`, `manifests/targets/<name>.yaml`); only
  components, which are the only manifest kind that owns extra per-item
  files, get the directory treatment.
- `build.patches: [filename, ...]` (optional, default `[]`) lists patch
  files from that same `files/` dir, applied **in order** with `git apply`
  after a fresh clone. Validated at `load_component()` time exactly like
  `build.files`: every entry must exist on disk, and (new) a component with
  no `source:` (a sourceless packaging component, ADR-005) cannot declare
  patches — there's no cloned tree to patch.
- Patches are applied **only** right after `sources.ensure_source()`
  performs an actual fresh clone — never onto an already-checked-out tree.
  A patch is not idempotent to reapply (`git apply` fails or silently
  no-ops depending on the exact diff), and the existing checkout also holds
  incremental build state (compiled objects, `.config`, etc.) that a
  reset-and-reapply-every-time approach would destroy, hurting rebuild
  ergonomics for exactly the large C trees (kernel, barebox, OP-TEE) most
  likely to want patches. `sources.ensure_source()` already had exactly one
  code path that produces a guaranteed-pristine tree — the clone block — so
  patch application hooks in right there, nowhere else.
- To know *when* a fresh clone (and therefore a reapply) is needed beyond
  the existing "ref moved upstream" check, `ensure_source()` now also
  tracks a `state.patches_hash()` of the declared patch files' content, via
  a small marker file (`.emblab-patches-hash`) written inside the source
  dir itself after a successful clone+apply — not under `workspace/state/`
  like every other marker, deliberately: it's scoped to that one checkout's
  identity, not to a `(target, component)` pair, and it self-invalidates
  for free whenever `shutil.rmtree(dest)` fires for a re-clone, with no
  separate bookkeeping to keep in sync. If the ref hasn't moved but the
  patch set has, that's also treated as "re-clone and reapply cleanly."
  `state.patches_hash()` is order-sensitive (a list, not a dict, keyed by
  content) since applying patches in a different order is a different
  tree. The same hash also folds into `state.component_hash()` — shared via
  the same `state.patches_hash()` call — so an edited patch forces the
  build *command* to rerun too, not just the source-level reapply.

## Consequences
Purely additive and mechanical for existing components: none has patches
yet, so `build.patches` defaults to `[]` everywhere and behaves exactly as
before. The directory move itself has no behavioral effect — only where
`manifests.py`'s path-resolution functions point — but it *is* a breaking
path change for anything that assumed the old flat
`manifests/components/<name>.yaml` layout; every fixture, inline test
manifest, and doc comment referencing that path was updated in the same
change.

`git apply` (not `git am`/`quilt`) was chosen for simplicity: it doesn't
need the patch to be a properly-formatted commit, just a unified diff —
sufficient for every real case anticipated, and it's already guaranteed to
exist wherever `git clone` does, since patch application always immediately
follows a clone in the same code path. If a component ever needs
`git am`-only features (patch authorship/message preserved as real commits
in the shallow clone), revisit then — `--depth 1` shallow clones make `git
am` awkward anyway (no parent history to commit onto cleanly), so `git
apply` is also the better fit for how `sources.py` already clones.
