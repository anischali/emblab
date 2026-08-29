# ADR-006: Per-component builddeps, per-target image override, target.arch as a template token, directory artifacts

## Status
Accepted

## Context
Building out the FIT-image demo (ADR-005) surfaced four related frictions,
all variations on the same theme — a manifest needing to influence its
*container's* runtime environment without hand-editing an unrelated shared
manifest or hardcoding a value that only the target actually knows:

1. `fit-image`'s `mkimage` call needs Debian's `u-boot-tools` package. The
   only place to add it was `gnu-aarch64.yaml`'s shared `provision:` list —
   but that image is also used by `linux-kernel`, `tf-a`, and `optee-os`,
   none of which need it. Every extra package a single component needs
   would permanently bloat every other component's container.
2. `barebox.yaml`'s command referenced the unbraced shell var `$ARCH`,
   copying `$CROSS_COMPILE`'s style, but nothing ever set `ARCH` — not the
   image's `env:` block (which is toolchain-specific, not architecture-
   specific: the same `gnu-aarch64` image could in principle build more
   than one target arch), and not `build.py`. Every real build would have
   silently run with an empty `ARCH`. `linux-kernel.yaml` had independently
   worked around the same gap by hardcoding `ARCH=arm64` directly in its
   command — the inconsistency itself is a signal the value belongs at the
   driver level, not copy-pasted into each component. The first fix
   attempted was to inject `ARCH` as a real container env var (`extra_env`
   on every `containers.run` call, mirroring `CROSS_COMPILE`) — this broke
   a real `emblab build qemu-arm64-secureboot` run: `optee-os`'s command
   never mentions `ARCH` at all, but OP-TEE's own Makefiles read `ARCH`
   from the environment regardless and default it internally to `arm`;
   force-setting `arm64` there made it look for
   `lib/libutee/arch/arm64/sub.mk`, which doesn't exist (OP-TEE treats
   AArch64 as a sub-case of `arch/arm`, not a separate arch tree). A real
   env var is visible to every process in a container whether or not that
   component's own command asked for it — the wrong tool for a value only
   some components want.
3. Composing barebox into two different targets (`qemu-arm64-uefi-barebox`,
   `qemu-arm64-secureboot`) exposed that barebox's build drops several
   files into `images/`, and which one a given target's boot/BL33 path
   needs is a target-level concern — the component itself has no reason to
   pick one, and `build.py`'s artifact collection only knew how to copy a
   single file (`shutil.copy2`).
4. No mechanism let a target choose a different container image for a
   component than the one hardcoded in that component's manifest — forcing
   a component fork any time two targets wanted the same build logic under
   a different toolchain image.

## Decision
- `build.builddeps: [pkg, ...]` (optional, default `[]`) declares apt
  packages a *component* needs beyond its image's base `provision:`. Driven
  entirely by `containers.ensure_builddeps()`, called only on an actual
  (non-skipped) build: `apt-get install -y --no-install-recommends <deps>`
  runs against the component's already-provisioned container, gated by its
  own idempotency marker keyed on `(image, component)` — separate from
  `ensure_image`'s marker, because several components can share one image
  container while each wanting a different extra package set; installs
  accumulate in the shared container rather than replacing each other.
  Included in `state.component_hash()` so an edited `builddeps` list forces
  a rebuild like any other resolved input.
- `ARCH` is resolved as `${env.ARCH}` — an emblab template token, exactly
  like `${env.JOBS}` already was — not a real container env var.
  `templating.default_env()` takes the target's `arch:` field and adds it
  to the same small `env.*` dict `${env.JOBS}`/`${env.WORKSPACE}` already
  come from; `build.py` and `qemu.py` both now pass `target.arch` through.
  Because a template token is pure string substitution into the one
  command that names it, a component that never writes `${env.ARCH}` is
  structurally unaffected by it — no environment leaks into unrelated
  tools, by construction, not by convention. `barebox.yaml` and
  `linux-kernel.yaml`'s hardcoded/unbraced `ARCH=` were both changed to
  `ARCH=${env.ARCH}`.
- A target's stack entry may set `image: <name>`, overriding which image
  manifest a component builds under for that target only
  (`StackEntry.image`, default `None` meaning "use the component's own
  `image:`"). Resolved once in `build.py` as
  `manifests.load_image(entry.image or component.image)` and validated at
  `load_target()` time like any other cross-reference.
- `build.py`'s artifact collection now branches on `src.is_dir()`:
  directory artifacts are copied with `shutil.copytree` (recreating `dst`
  fresh if something is already there), file artifacts still use
  `shutil.copy2`. A component can therefore declare a whole output
  directory as one artifact (`barebox.yaml`'s `images: images/`) and leave
  picking a specific file to whichever target needs it —
  `${barebox.images}/barebox-dt-2nd.img` — the same string-substitution
  token mechanism as ever, no new templating syntax.

## Consequences
All four changes are additive: an existing component with no `builddeps`,
a stack entry with no `image:` override, and a file-shaped artifact all
behave exactly as before. `gnu-aarch64.yaml`'s `provision:` list no longer
carries `u-boot-tools` — it now lives on `fit-image.yaml`'s `builddeps:`,
the only component that actually calls `mkimage`.

The trade-off on builddeps: because installs accumulate in a shared,
per-image container rather than isolating each component in its own
derived image, a component's build is not perfectly hermetic against
packages other components installed into the same container — acceptable
here since `apt-get install` is additive/idempotent and every image in
this project is Debian-based; revisit (isolated per-builddeps-set
containers) only if that stops being true.

`ARCH` deliberately does *not* join `CROSS_COMPILE*` as a raw shell env
var — see the OP-TEE incident above. `env.ARCH` differs from
`env.JOBS`/`env.WORKSPACE` in one respect: it's resolved fresh per
*target* (via `target.arch`), not fixed for the whole `emblab` process,
since the same toolchain image can in principle serve more than one
target arch. `GOARCH` in `uroot-ramdisk.yaml` was deliberately left
hardcoded rather than wired to `${env.ARCH}`: Go's arch names don't
always match Linux kernel `ARCH=` names, and building that translation is
out of scope until a second architecture is actually attempted (see
CONTEXT.md's Next section).
