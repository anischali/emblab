# ADR-011: `build.setup` — a component's optional one-time setup step

## Status
Accepted

## Context
`fit-image` needs a signing keypair (`helpers/fitkeys-ctl generate`)
generated once before it can sign a FIT image. That doesn't fit
`build.command`: `build.command` is re-run whenever its resolved inputs
change (ADR-007/state.py's `component_hash`), which is correct for an
actual build step but wrong for key generation — regenerating the keypair
on every unrelated `build.command` change would silently invalidate the
signature on anything already signed with the old key, with no explicit
signal that it happened.

The two steps also need independent forcing. `emblab build --force`
rebuilds `command` (e.g. after a source change); it must not imply "throw
away the signing key and mint a new one." Conversely, rotating a key on
purpose shouldn't require faking out `command`'s own change-detection.

## Decision
- `Build` gains an optional `setup: str` field (`""` = none), validated
  like `command` but not required.
- `state.py` tracks it as a **third, independent** marker layer
  (`setup_hash`/`setup_marker_path`, alongside the existing image and
  component-build markers): hashes `{setup, resolved_vars}` only — no
  source ref, builddeps, or patches, since `build.setup` runs before
  builddeps are installed and isn't expected to depend on the merged
  patch set the way `command` does.
- `build.py` runs `build.setup` (if present) once per component, before
  the existing `component_hash`/skip-if-unchanged check for `command`:
  resolve vars first (setup may reference `${vars.*}`/`${env.*}` the same
  way `command` does), skip if `setup_marker` already matches (unless
  `--setup-force`), else render and run it in-container exactly like
  `command` (same image, same `workspace/src/<path>` workdir, same
  `helpers/` bind-mount — so it can call `fitkeys-ctl` by name), then
  write its own marker.
- `emblab build` gains `--setup-force`, independent of the existing
  `--force`: `--force` alone reruns `command` but leaves an
  already-satisfied `setup` marker alone; `--setup-force` alone reruns
  `setup` (e.g. to rotate a key) without forcing an unrelated `command`
  rebuild.
- First real consumer: `fit-image.yaml`'s
  `setup: fitkeys-ctl generate --out-dir keys --name dev-new`. Not yet
  wired into `command` itself — `mkimage -F -r -k keys` and the `.its`
  `signature` node are still open (see CONTEXT.md's Next); this ADR only
  covers the setup-step mechanism, not the full signed-FIT path.

## Consequences
Purely additive: `Build.setup` defaults to `""`, so every existing
component is unaffected — the `if component.build.setup:` guard in
`build.py` means no setup marker is even written for them.

A component with a `setup` step now has two markers in
`workspace/state/components/`, not one; `emblab clean` already clears the
whole `workspace/state/` tree, so no separate handling was needed there.

`setup`'s hash deliberately omits `source`/`builddeps`/`patches` — if that
ever stops being safe for some future setup step (e.g. one that does need
a builddep), `setup_hash` will need those parameters too, the same way
`component_hash` already takes them explicitly rather than reading
`component.build` internally (ADR-009/ADR-010's pattern).
