# ADR-009: components are agnostic of image/arch/builddeps — the target owns all three

## Status
Accepted

## Context
Every component manifest hardcoded `image: gnu-aarch64` (or `image: go`),
and several (`tf-a`, `u-boot`, `fit-image`, `edk2`) also hardcoded their own
`build.builddeps`. ADR-006 had already introduced a per-target
`image:` *override* on a stack entry, but the component's own `image:`
was still the default — meaning a component was never actually agnostic of
which toolchain/image it assumed, only occasionally overridable. That
default baked in more than a container reference: `gnu-aarch64` is itself
an arch-specific name and toolchain (`aarch64-linux-gnu-*`), so a component
declaring `image: gnu-aarch64` was implicitly declaring "this only builds
for aarch64" even when its actual recipe (`make ARCH=... CROSS_COMPILE=...`)
had no such restriction. `build.builddeps` had the same shape of problem:
which extra packages a build needs is really a property of the *(image,
component)* pairing a target chooses, not a fixed fact about the component
alone.

`tf-a.yaml` additionally hardcoded `CROSS_COMPILE=aarch64-linux-gnu-` as a
literal in its command — inconsistent with every other component, which
all read the real `$CROSS_COMPILE` shell env var from whichever image is
in play. `barebox.yaml`/`linux-kernel.yaml` used `${env.ARCH}` (ADR-006),
`u-boot.yaml` hardcoded `ARCH=arm`, `uroot-ramdisk.yaml` hardcoded
`GOARCH=arm64`, and `edk2.yaml` hardcoded `-a AARCH64` /
`GCC5_AARCH64_PREFIX` — four different ways of a component assuming a real
architecture. An initial pass at fixing the latter three turned each
hardcoded literal into a `build.vars` entry carrying the *same value as its
default* (e.g. `vars.arch: arm`) — better than a bare literal, but still a
component-level assumption about which arch it builds for, just phrased as
a default instead of a hardcode. That isn't actually agnostic: "arch and
image are per-target, not per-component" (this ADR's namesake principle)
means a component should carry no arch opinion at all, the same way it now
carries no image opinion.

## Decision
- `image:` and `build.builddeps:` are no longer legal fields on a
  component manifest — `load_component()` now raises a clear
  `ManifestError` if either is present, rather than silently ignoring
  them. `Component`/`Build` lost those fields entirely.
- A target's stack entry now *always* sets `image:` (`_require`d, not
  optional — ADR-006's "override" framing is gone along with the
  component-level default it was overriding) and may set `builddeps:`
  (a plain list, default `[]`). `StackEntry` gained both fields;
  `state.component_hash()` and `containers.ensure_builddeps()` take
  `builddeps` as an explicit parameter now (the same way
  `component_hash()` already took `resolved_vars` as a parameter, never
  read off the component) instead of reading `component.build.builddeps`.
- Every component that referenced a real architecture — `barebox`/
  `linux-kernel` (`${env.ARCH}`), `u-boot` (`ARCH=arm`), `uroot-ramdisk`
  (`GOARCH=arm64`), `edk2` (`-a AARCH64`/`GCC5_AARCH64_PREFIX`) — now
  reads an arch-flavored `build.vars` entry (`vars.arch`, `vars.goarch`,
  `vars.edk2_arch`) that carries **no default value**. A component that
  references `${vars.arch}` but never declares it in its own
  `build.vars` relies entirely on `resolve_vars`'s existing behavior: if
  no target stack entry supplies it either, rendering fails with a clear
  `TemplateError: unknown token '${vars.arch}': no such var` — the same
  enforcement `image:`'s `_require` gives at the schema level, just
  arriving at build/render time instead of load time (there's no
  schema-level way to know which `vars.*` names a command references
  without parsing shell, so this is the mechanism available). Every
  target manifest was updated to set the relevant var(s) on the
  component's actual real-arch value(s) it always used anyway (mostly
  `arm64`; `u-boot`'s own Kbuild spelling is `arm`) — behavior is
  unchanged, only where the value lives moved.
  `linux-kernel.yaml`'s `artifacts: image: arch/${vars.arch}/boot/Image`
  also templates its arch-dependent output path this same way (see the
  driver fix below). `tf-a.yaml`'s hardcoded
  `CROSS_COMPILE=aarch64-linux-gnu-` was changed to the real
  `$CROSS_COMPILE` shell env var, matching every other component.
  `${env.ARCH}`/`target.arch` (ADR-006) remain available, tested,
  driver-level infrastructure — nothing currently uses them by default,
  but a target that wants `target.arch` to flow automatically into a
  component can still wire it explicitly per stack entry
  (`vars: {arch: ${env.ARCH}}`) instead of a literal.
- Driver fix needed to make the above actually work: `build.py`'s
  artifacts-collection loop resolves each declared `rel_path` through
  `templating.render_command()` before using it (previously only
  `build.command` was rendered — an artifacts: value with `${vars.X}`
  tokens, like `edk2.yaml`'s `Build/${vars.platform}-${vars.edk2_arch}/...`,
  would have looked for a literal, unresolved `${...}` directory name on
  disk and failed). `render_command`'s docstring was broadened to
  describe this as its real scope: rendering any single component-owned
  string against vars./env. tokens, not just `build.command` specifically.
- Every existing target manifest now sets `image:` on each of its stack
  entries (previously implicit via the component default), the relevant
  arch var(s) (previously implicit via a component default or hardcode),
  and whatever `builddeps:` its components used to declare
  (`tf-a`/`u-boot`: `libgnutls28-dev`; `fit-image`: `u-boot-tools`;
  `edk2`: `iasl`/`uuid-dev`/`cmake`).

## Consequences
This is a breaking schema change for the manifest *authoring* surface
(every component and target manifest needed editing in the same change —
there's no meaningful way to make `image:`/`builddeps:` "optional at the
component level, ignored if the target also sets it," since that would
just resurrect the same "which one wins, and does a reader have to check
two places" ambiguity ADR-006 already introduced and this ADR removes).
It is not a breaking change to any manifest's *build behavior* — every
target still builds exactly the same image/toolchain/arch/package
combination it did before, just declared in one place (the target)
instead of scattered across component defaults and hardcodes.

A component is now provably reusable across images and architectures the
way `CLAUDE.md`/ADR-001 always intended: nothing in a component manifest
can reference or assume a specific container or a specific architecture.
The trade-off is that every target's stack entry is now more verbose
(`image:`, arch var(s), and `builddeps:` all explicit per entry) — accepted
deliberately: implicit, component-level defaults are exactly what made a
component's assumptions invisible to a reader in the first place.
