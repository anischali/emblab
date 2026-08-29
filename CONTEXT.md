# CONTEXT.md

Read this first. Then `CLAUDE.md`, then `docs/architecture/decisions/`.

## Status
Phase 1 scaffolding complete (CLI, manifest schema, seed manifests, ADRs,
offline unit tests). Phase 2 — running builds against the real
network/udocker — has started: `barebox` now builds for real (see Proven).
Schema also grew several additive mechanisms since Phase 1: sourceless
components + `build.files` (ADR-005, for packaging steps like `fit-image`
with no upstream repo); per-component `build.builddeps` + per-target image
override + directory-valued artifacts + `${env.ARCH}` (ADR-006); and a
Yocto-style per-component directory layout
(`manifests/components/<name>/<name>.yaml` + a sibling `files/`) plus
`build.patches`, git-applied in order onto a fresh clone (ADR-007).
`optee-os` now carries the first real one — see Proven. `source.submodules`
(ADR-008) lets a component's clone run `git submodule update --init
--recursive` — needed for the new `edk2` component.

## Proven
- 2026-08-29: `bash bootstrap.sh` — venv + `pip install -e ".[dev]"` +
  `emblab doctor` all succeeded from a clean checkout in well under a
  minute (no network beyond PyPI). `doctor` confirmed git, udocker, and all
  three qemu-system-* binaries already present.
- 2026-08-29: `pytest tests/` — 41/41 offline tests pass (manifest
  validation, templating, graph ordering/cycle detection, a full
  build-plan dry run whose rendered `tf-a` command matches the flag
  structure transcribed from `barebox-arm64-poc/build.sh`, the ADR-005
  sourceless-component/`build.files` mechanism including the `fit-image`
  target's kernel+ramdisk composition, and the ADR-006 additions:
  `build.builddeps` install-once idempotency, per-target `image:`
  override, `${env.ARCH}` template-token resolution, and directory-artifact
  copying). `pyproject.toml` now sets `testpaths = ["tests"]` — a bare
  `pytest` from the repo root previously recursed into
  `workspace/src/barebox` (a real cloned repo with its own test suite)
  once a real build had populated it, turning a sub-second run into a
  many-minute one.
- 2026-08-29: `emblab list`, `emblab show target ...`, `emblab clean --all`,
  and the error path for an unknown target (`emblab build
  nonexistent-target` → clean `error: manifest not found: ...` + exit 1)
  all exercised manually against the real CLI and behave as designed.
- 2026-08-29: **`emblab build qemu-arm64-uefi-barebox` succeeded for
  real** — real `git clone` of `https://github.com/barebox/barebox`
  (`ref: master`, not the original `git.pengutronix.de` mirror), real
  `gnu-aarch64` udocker container, `efi_v8_defconfig` (not
  `vexpress_v8_defconfig`), producing a genuine 918528-byte
  `barebox-dt-2nd.img` collected under
  `workspace/artifacts/qemu-arm64-uefi-barebox/barebox/images/`. This is
  what motivated the artifacts-can-be-a-directory change in ADR-006:
  barebox drops several files into `images/`, and picking
  `barebox-dt-2nd.img` out of it is now the target's job via
  `${barebox.images}/barebox-dt-2nd.img`, not the component's.
  `emblab run qemu-arm64-uefi-barebox` (actually booting it in QEMU) is
  still unconfirmed — see Next.
- 2026-08-29: A real `emblab build qemu-arm64-secureboot` attempt reached
  `optee-os` (after `gnu-aarch64` provisioning and a real source clone) and
  failed: `make: *** No rule to make target 'lib/libutee/arch/arm64/sub.mk'`.
  Root cause: at that point `build.py` was injecting `ARCH=arm64` as a real
  container env var for every component build (an earlier, since-reverted
  version of the ADR-006 `${env.ARCH}` mechanism) — `optee-os.yaml`'s
  command never mentions `ARCH` at all, but OP-TEE's own Makefiles read it
  from the environment anyway and default it internally to `arm`; the
  forced `arm64` broke that. Fixed by making `ARCH` a template token
  (`${env.ARCH}`, resolved purely at render time, exactly like
  `${env.JOBS}`) instead of a real env var — see ADR-006's Context/Decision
  for the full writeup.
- 2026-08-29: `optee-os.yaml`'s command sets `CFG_WITH_DUMMY_HWRNG=y`, but
  upstream `optee_os` (`ref: master`) has no such config at all —
  `CFG_WITH_SOFTWARE_PRNG=n` with no real hwrng would fail to build. Fixed
  with `build.patches: [0001-core-hwrng-add-dummy-hwrng-for-qemu.patch]`
  (from https://github.com/anischali/optee_os/commit/b23c4cf04e33, the
  first real user of ADR-007's patch mechanism) — adds the config plus a
  `hw_get_random_bytes()` that reads the QEMU virtual timer.
  `git apply --check` confirmed clean against the real
  `workspace/src/optee-os` clone already present. **Not yet re-attempted**
  as a full `emblab build qemu-arm64-secureboot` — see Next.
- 2026-08-29: New `qemu-arm64-secureboot-uboot` target — same TF-A+OP-TEE
  stack as `qemu-arm64-secureboot`, `u-boot` as BL33 instead of `barebox`.
  Required generalizing `tf-a.yaml`'s previously-hardcoded
  `ARM_LINUX_KERNEL_AS_BL33=1` into a conditionally-populated `bl33_flags`
  var (same trick as `bl32_flags`) — that flag is correct for barebox's
  EFI-mode build (TF-A loads it as a raw kernel/EFI payload) but wrong for
  a real bootloader BL33 like u-boot, which needs it entirely absent, not
  present-with-0. `u-boot.yaml` hardcodes `ARCH=arm` (not `${env.ARCH}`,
  which would resolve to `arm64`) — u-boot keeps one `arch/arm/` Kbuild
  tree for both AArch32/AArch64, same arch-naming mismatch already hit for
  OP-TEE. **Both `u-boot.yaml` and this target are UNVERIFIED** — offline
  dry-run only (`pytest`), no real build attempted yet.
- 2026-08-29: `tf-a` and `u-boot` both build host tools (`cert_create`,
  `mkimage`'s FIT signing) that link against GnuTLS — added
  `libgnutls28-dev` to both components' `build.builddeps`.
- 2026-08-29: New `edk2` component (ADR-008's `source.submodules: true` —
  `CryptoPkg` vendors OpenSSL/mbedTLS as submodules, needed since
  `ArmVirtQemu.dsc` pulls in `CryptoPkg`), transcribed from
  `barebox-arm64-poc/edk/build.run` + its `containers/Dockerfile`
  (`iasl`/`uuid-dev`/`cmake` `builddeps`). **Investigated and could not
  build a "barebox bundled into edk2" target**: `barebox-arm64-poc/edk`'s
  own `EFI_CRASH_COURSE.md` (section 16) *describes* a custom `FvBootDxe`
  BDS driver that finds a `FILE APPLICATION` PE32 section by GUID in
  `ArmVirtQemuFvMain.fdf.inc` — but `git status`/`git log`/branches/
  stash/reflog on that project's local `edk2` checkout all confirm it's a
  plain, unmodified upstream clone at the commit pinned in `edk2.commit`;
  no such driver source or `.fdf.inc` patch exists anywhere in that repo
  to transcribe. Asked the user how to proceed; chose NOT to author
  untested custom DXE driver C code — new target `qemu-arm64-edk2-barebox`
  instead chain-loads exactly like `qemu-arm64-uefi-barebox` already does
  (`-bios ${edk2.fd}` from our own compiled edk2, `-kernel` for barebox as
  two separate QEMU-loaded things, not one bundled firmware image).
  `edk2.yaml` and this target are both UNVERIFIED — offline dry-run only.

## In progress
Nothing in flight.

## Next
1. `emblab run qemu-arm64-uefi-barebox` — confirm the real
   `barebox-dt-2nd.img` from the build above actually boots in QEMU. This
   is the one remaining unconfirmed step for the smaller seed target.
2. Re-attempt `emblab build qemu-arm64-secureboot` now that the `ARCH`
   env-var leak into `optee-os` is fixed AND the `CFG_WITH_DUMMY_HWRNG`
   patch is wired up (three components: optee-os, barebox, tf-a — this is
   a long build, expect real wall-clock time for OP-TEE and TF-A from
   clean). `barebox`'s own build command is proven; `tf-a` and `optee-os`
   are not yet — this is the first real attempt at either since both
   fixes.
3. `emblab run qemu-arm64-secureboot`.
4. `emblab build qemu-arm64-fit` — `linux-kernel` and `fit-image`'s
   `mkimage` invocation are both still UNVERIFIED against a real kernel
   tree; `uroot-ramdisk` likewise unverified against real u-root.
5. `emblab build qemu-arm64-secureboot-uboot` — `u-boot.yaml`'s
   `qemu_arm64_defconfig` build command is UNVERIFIED against a real
   clone, same starting point `barebox.yaml`/`linux-kernel.yaml` began
   from; validate after `qemu-arm64-secureboot` itself is confirmed
   working, since they share `optee-os`/`tf-a`.
6. `emblab build qemu-arm64-edk2-barebox` — `edk2.yaml`'s build command
   (submodule init + `edksetup.sh`/`BaseTools`/`build -p ArmVirtQemu.dsc`)
   is UNVERIFIED against a real clone; expect real wall-clock time
   (CryptoPkg's vendored OpenSSL/mbedTLS submodules are large).
   `EFI_CRASH_COURSE.md`'s described `FvBootDxe` bundling driver still
   doesn't exist anywhere real — if a true bundled build is wanted later,
   it needs someone to actually author and test that DXE driver first.
7. If a second target architecture is attempted (see Open questions),
   revisit `uroot-ramdisk.yaml`'s hardcoded `GOARCH=arm64` — ADR-006
   deliberately left it hardcoded rather than wiring it to `$ARCH`, since
   Go's arch names don't always match Linux kernel `ARCH=` names and that
   translation isn't worth building until it's actually needed.

## Open questions
- Pin exact git refs (tags/SHAs) for `tf-a`, `optee-os`, `barebox` once a
  known-good combination is found — all three currently pin `ref: master`
  (barebox's proven build above was still against `master`), which is
  intentionally provisional.
- Once refs are pinned to exact commits (not branches), `sources.py`'s
  `git clone --branch <ref>` will need to change to `git fetch <url> <sha>
  && git checkout FETCH_HEAD`, since most git servers don't advertise
  arbitrary commits for a shallow branch clone.
- Which architecture/bootstack combination to add next after the two arm64
  seed targets are validated (riscv64+OpenSBI+U-Boot is a natural
  candidate — qemu-system-riscv64 is already installed on this machine).

## Environment notes
- `python3` 3.14.6, no `uv`/`poetry`/`hatch` — `pip` (via venv) only.
- `udocker` at `~/.local/bin/udocker`. emblab sets `UDOCKER_DIR` to
  `workspace/udocker` (project-local), never touches `~/.udocker`.
- `qemu-system-aarch64`, `qemu-system-riscv64`, `qemu-system-arm` are
  already installed at `/usr/bin` on this machine.
