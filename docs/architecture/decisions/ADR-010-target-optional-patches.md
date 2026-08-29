# ADR-010: target-specific extra patches, and the FvBootDxe integration

## Status
Accepted

## Context
ADR-007 gave each component a fixed `build.patches` list, always applied
on every build of that component, for every target. That fits a patch
that fixes something objectively broken for every consumer (`optee-os`'s
`CFG_WITH_DUMMY_HWRNG` patch — every target using `optee-os` needs it).
It doesn't fit a patch that changes *behavior* only some targets want:
bundling `edk2` needs a custom BDS driver
(https://codeberg.org/anischali/FvBootDxe, now real source — the
`barebox-arm64-poc/edk/EFI_CRASH_COURSE.md` design ADR-009 found
undocumented as code has since been implemented there) wired in via a
patch to `ArmVirtQemu.dsc`/`ArmVirtQemuFvMain.fdf.inc`/etc. — but
`qemu-arm64-edk2-barebox` (the existing chain-load target, ADR-009's
answer to the same original gap) deliberately does *not* want it: it's a
different, already-working, already-tested way to combine the same two
components. Making the patch a fixed `build.patches` entry on `edk2`
would force it onto every target building `edk2`, including that one.

Adapting the driver's own reference integration patch
(`FvBootDxe/poc-how-to-integrate-with-qemu.patch` in that repo) also
turned out not to be a plain drop-in: applied against current `edk2`
`master`, every hunk either fails outright or only succeeds with fuzz —
`ArmVirtQemu.dsc` no longer lists `BdsDxe.inf` directly (moved into a
shared `ArmVirtPkg/ArmVirt.dsc.inc` also used by other `ArmVirt*`
platforms), a `PcdResetOnMemoryTypeInformationChange` anchor the POC patch
used is gone, and edk2's `.dsc`/`.fdf.inc` files are CRLF while the POC
patch is LF-only. The patch shipped here
(`manifests/components/edk2/files/0001-fvbootdxe-bundle-app.patch`) was
reconstructed by hand against a fresh clone of current `master` — same
semantic changes (add `FvBootDxe.inf`, its `PcdFvBootApplicationGuid`
PCD — declared in `MdeModulePkg.dec`, defaulted to zero there and
overridden to a real GUID in `ArmVirtQemu.dsc`'s `[PcdsFixedAtBuild]`,
matching a `FILE APPLICATION` GUID added to `ArmVirtQemuFvMain.fdf.inc`),
adapted to today's actual file layout, verified with `git apply --check`
against two independent fresh `master` clones. One deliberate deviation
from the POC: it does **not** comment out `SecurityPkg/RandomNumberGenerator/
RngDxe/RngDxe.inf` — every existing target already passes QEMU
`-device virtio-rng-pci` expecting a working RNG, that POC line looked
like an unrelated environment workaround rather than an `FvBootDxe`
requirement (nothing in `FvBootDxe`'s own dependency list touches RNG),
and disabling working functionality to graft in unrelated, unverified
functionality is the wrong trade by default.

## Decision
- `StackEntry` gains `patches: list` (default `[]`) — extra patch
  filenames (from the same component `files/` dir `build.patches` already
  uses) that only *this* target applies to *this* component, on top of
  whatever the component's own `build.patches` always applies. Validated
  at `load_target()` time exactly like `build.files`/`build.patches`
  already are (`ManifestError` if the file doesn't exist on disk).
- `sources.ensure_source()` and `state.component_hash()` both take the
  full, already-merged patch list as an explicit parameter now — same
  pattern ADR-009 established for `builddeps` — rather than reading
  `component.build.patches` internally. `build.py` assembles
  `component.build.patches + entry.patches` once per component and
  passes that single list to both. `cli.py`'s standalone `fetch` command
  (no target in play) passes just `component.build.patches`.
- `edk2.yaml` gains `vars.fv_boot_app_flag`, empty by default (same
  conditionally-populated-var trick as `tf-a.yaml`'s `bl32_flags`/
  `bl33_flags` — `make`/`build` needs the `-D FV_BOOT_APP_PATH=...` flag
  entirely absent for a plain build, not present-with-empty-value). A
  target that opts into the `FvBootDxe` patch also sets this to
  `-D FV_BOOT_APP_PATH=${<payload-component>.<artifact>}` — demonstrated
  by the new `qemu-arm64-edk2-fvbootdxe-barebox` target, pointing it at
  `${barebox.images}/barebox-dt-2nd.img`. That's the same file
  `qemu-arm64-uefi-barebox`/`qemu-arm64-edk2-barebox` already use as a
  kernel/EFI payload — barebox's `efi_v8_defconfig` output *is* a PE32
  EFI application (confirmed against a real build: `barebox.efi` in the
  source tree is a build-time symlink to this exact file), so no new
  barebox variant or component was needed, only a different filename
  reference into the same already-built artifact.
- The cross-component reference inside `vars.fv_boot_app_flag`'s value
  needs no new dependency-graph handling: `graph.py` already scans every
  stack entry's `vars` values for `${component.artifact}` tokens
  regardless of which var carries them, so `barebox` building before
  `edk2` falls out for free, the same way `tf-a.yaml`'s `bl33` already
  orders `barebox`/`u-boot` before `tf-a`.

## Consequences
Purely additive: `StackEntry.patches` defaults to `[]`, so every existing
target is unaffected. `qemu-arm64-edk2-barebox` (chain-load) and
`qemu-arm64-edk2-fvbootdxe-barebox` (real bundling) now both exist,
sharing the same `edk2`/`barebox` components with no fork between them —
exactly the point of making the patch and the flag both target-owned
instead of component-level.

Like `build.patches` before it (ADR-007), a `patches:`-bearing stack entry
only ever gets (re)applied at a fresh clone — if two targets share the
same component's `workspace/src/<path>` but request different
`patches:` lists, alternating between building them will force a re-clone
each time the combined patch list changes, exactly as if the component's
own `build.patches` had changed. Accepted for the same reason ADR-007
accepted it: correctness (never reapplying onto an already-patched,
possibly-mid-build tree) over the cost of an avoidable re-clone in an
already-uncommon situation (two *different* targets actively alternating
builds of the *same* component with *different* patch sets).

The hand-reconstructed `FvBootDxe` integration patch is UNVERIFIED against
a real build — `git apply --check` only proves it applies cleanly to
current `master`, not that the resulting firmware actually builds or
boots `FvBootDxe`/loads `barebox` correctly. Both `edk2.yaml`'s
`fv_boot_app_flag`-driven behavior and the new target need a real
`emblab build qemu-arm64-edk2-fvbootdxe-barebox` to confirm — see
CONTEXT.md's Next section.
