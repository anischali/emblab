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
--recursive` — needed for the new `edk2` component. As of ADR-009, a
component declares no `image:`, no `build.builddeps`, and no default for
any arch-flavored var (`vars.arch`, `vars.goarch`, `vars.edk2_arch`) —
every target's stack entry sets all of these explicitly per component.
`build.builddeps` mentioned in earlier Proven entries below now means
"the target's stack-entry `builddeps:`", not a component field. ADR-010
adds the same target-optional layering for patches: a stack entry's own
`patches:` are extras on top of a component's always-applied
`build.patches` — used to opt `edk2` into real `FvBootDxe` firmware
bundling (https://codeberg.org/anischali/FvBootDxe) per-target, without
forking the component or affecting targets that don't want it. ADR-014
adds a Yocto `devtool modify`/`reset`-style marker
(`sources.mark_modified`/`mark_finished`, `emblab modify`/`emblab reset
[--reclone]`) so a component's cloned source can be frozen against
`ensure_source`'s ref-moved/patches-changed re-clone while someone is
hand-editing it under `workspace/src/<path>`.

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
- 2026-08-29: **ADR-009**: moved `image:`, `build.builddeps`, and every
  hardcoded/defaulted arch value out of every component manifest and onto
  the target's stack entry, per explicit direction ("the components need
  to be agnostic of the aarch or image[,] the targets need to set the
  aarch and the images and also the target will add the builddeps").
  `Component`/`Build` lost `image`/`builddeps` entirely;
  `load_component()` now rejects either field with a clear error.
  `StackEntry.image` is required (no more component-level fallback);
  `StackEntry.builddeps` is new. Components that reference an arch
  (`barebox`/`linux-kernel`: `vars.arch`; `u-boot`: `vars.arch`;
  `uroot-ramdisk`: `vars.goarch`; `edk2`: `vars.edk2_arch`) declare **no
  default** for it — a target that forgets raises a clear `TemplateError`
  at build time (`resolve_vars`'s existing "unknown token" check, no new
  validation needed). Also fixed a real driver gap surfaced by `edk2.yaml`
  parameterizing its own `artifacts: fd:` path with `${vars.platform}-
  ${vars.edk2_arch}`: `build.py` never rendered `vars./env.` tokens in
  `artifacts:` values, only in `build.command` — now it does both.
  `tf-a.yaml`'s hardcoded `CROSS_COMPILE=aarch64-linux-gnu-` was also
  changed to the real `$CROSS_COMPILE` env var, matching every other
  component. All 5 targets + 8 components updated; 57/57 tests pass.
- 2026-08-29: **ADR-010 / real `FvBootDxe` bundling**: the driver ADR-009
  found undocumented as code now has real source at
  https://codeberg.org/anischali/FvBootDxe. Its own reference integration
  patch doesn't apply cleanly to current `edk2` `master` (upstream moved
  `BdsDxe.inf` out of `ArmVirtQemu.dsc` into a shared
  `ArmVirtPkg/ArmVirt.dsc.inc`, dropped a PCD anchor the patch used, and
  the patch is LF-only against edk2's CRLF files) — reconstructed by hand
  against a fresh `master` clone instead, verified with `git apply --check`
  against two independent fresh clones, saved as
  `manifests/components/edk2/files/0001-fvbootdxe-bundle-app.patch`.
  Deliberately did NOT carry over the POC's comment-out of `RngDxe.inf` —
  looked like an unrelated environment workaround, not something
  `FvBootDxe` needs, and every existing target already expects a working
  RNG (`-device virtio-rng-pci`). Added `StackEntry.patches` (target-only
  extras on top of a component's own `build.patches`) so `edk2` can offer
  this as opt-in per target rather than forcing it on every `edk2` build;
  `edk2.yaml` gained `vars.fv_boot_app_flag` (empty by default, same
  conditionally-populated-var trick as `tf-a.yaml`'s `bl32_flags`). New
  target `qemu-arm64-edk2-fvbootdxe-barebox` demonstrates it: `barebox`'s
  own `efi_v8_defconfig` output (`barebox-dt-2nd.img`) IS already a PE32
  EFI application — confirmed against the real build in `workspace/`,
  where `barebox.efi` is a symlink to that exact file — so no new barebox
  variant was needed, just pointing `FV_BOOT_APP_PATH` at the same
  artifact `qemu-arm64-uefi-barebox` already uses. 63/63 tests pass.
  **The hand-reconstructed patch is UNVERIFIED against a real build** —
  `git apply --check` only proves it applies; it doesn't prove the
  resulting firmware builds or actually boots `barebox` via `FvBootDxe`.
- 2026-08-29: **`emblab build qemu-arm64-edk2-fvbootdxe-barebox` succeeded
  for real**, surfacing and fixing two bugs in `edk2.yaml` — both are
  upstream `edk2` `master` drift (this component's `ref: master` is
  intentionally floating, see Open questions), unrelated to the
  hand-reconstructed `FvBootDxe` patch itself, which applied and built
  clean: (1) upstream dropped the legacy `GCC5` toolchain tag
  (`Conf/tools_def.txt` now only defines `GCC`/`GCCNOLTO`/etc, with
  `ENV(GCC_AARCH64_PREFIX)` not `GCC5_AARCH64_PREFIX`) — fixed by changing
  `-t GCC5`/`GCC5_${vars.edk2_arch}_PREFIX`/`DEBUG_GCC5` to
  `GCC`/`GCC_${vars.edk2_arch}_PREFIX`/`DEBUG_GCC`; (2) EDK2's own
  `Build/<platform>-<arch>` output directory uses a differently-cased
  "friendly" arch name (`AArch64`) than the `-a` flag/env-var spelling
  (`AARCH64`) — confirmed against the real build directory, not documented
  anywhere obvious in EDK2 itself — fixed by adding a second explicit var,
  `vars.edk2_build_arch`, set by both edk2 targets' stack entries
  alongside `edk2_arch`, and pointing `artifacts.fd` at it instead. Real
  build: 9 minutes for the full compile, then instant on the artifact-only
  retry. 63/63 tests still pass. **Still unconfirmed**: `emblab run` this
  target and see it actually boot `barebox` via `FvBootDxe` with no
  `-kernel` flag present — the build succeeding only proves the firmware
  links, not that the embedded-payload boot path works.
- 2026-08-29: `bootstrap.sh`'s `pip install -e ".[dev]"` was hanging
  indefinitely on this machine once a real build had populated `workspace/`.
  Root cause: `pyproject.toml`'s `[tool.setuptools.packages.find]`
  auto-discovery calls `os.walk(where, followlinks=True)` over the whole
  project root, and `workspace/udocker/containers/.../ROOT` (a full
  udocker/PRoot container rootfs, several GB, full of symlinks) sent that
  walk into an effectively endless traversal — confirmed with
  `faulthandler.dump_traceback_later`, stack bottomed out in
  `setuptools/discovery.py`'s `_find_iter` inside `os.walk`. Fixed by
  switching to an explicit `packages = ["emblab"]` in `pyproject.toml`:
  this project only ever has the one real package, so auto-discovery
  bought nothing but the whole-tree walk. Verified: fresh-venv
  `pip install -e ".[dev]"` now completes in ~4.5s against a checkout with
  a fully-populated `workspace/`; `emblab list` and `pytest tests/`
  (63/63) both still pass.
- 2026-08-29: **`qemu-riscv64-opensbi-barebox` — first riscv64 target,
  built AND booted for real**, resolving the "which arch/bootstack next"
  Open question with OpenSBI+barebox instead of the originally-guessed
  OpenSBI+U-Boot. New `opensbi` component (PLATFORM=generic, no
  arch-flavored vars needed — unlike edk2/barebox/u-boot, OpenSBI is
  inherently riscv-only) and `gnu-riscv64` image (mirrors `gnu-aarch64`'s
  package set with the riscv64 cross toolchain) both worked first try.
  Two real bugs surfaced and fixed along the way, both in how the target
  picked barebox's output rather than in barebox/opensbi themselves:
  (1) first attempt pointed `-kernel` at a freshly-added `vars.image_path`
  (`barebox.bin`, later `vmbarebox`) — QEMU's ELF loader took
  `vmbarebox`'s addresses literally (`CONFIG_RELOCATABLE=y`, `p_vaddr`
  starting at 0x0) and refused to start, colliding with the boot ROM;
  (2) realized `${barebox.images}/barebox-dt-2nd.img` — the SAME artifact
  key the arm64 targets already use — was the right file all along:
  riscv64's `CONFIG_SOC_VIRT` selects the arch-agnostic `BOARD_GENERIC_DT`
  Kconfig option that produces it (its own help text says so verbatim),
  so no barebox.yaml changes were needed at all in the end. Confirmed with
  `file`: a real "Linux kernel RISC-V boot executable Image". Full real
  boot: QEMU -> OpenSBI M-mode (prints its real banner, HART/domain info)
  -> S-mode handoff at 0x80200000 -> barebox 2026.08.0 reaches an
  interactive `barebox@riscv-virtio,qemu:/` shell prompt on serial ("Nothing
  bootable found" after that is expected — no OS/rootfs is wired up, the
  bootloader chain itself is what this target proves). 63/63 tests pass.
- 2026-08-29: `barebox.yaml` gained `vars.extra_conf` (empty by default,
  same conditionally-populated-var trick as `tf-a.yaml`'s `bl32_flags`): a
  target's stack entry can point it at one or more Kconfig fragment files
  (space-separated), merged onto the defconfig via barebox's own
  `scripts/kconfig/merge_config.sh -m` before the real build — motivating
  use case is a FIT image keystore public-key fragment
  (`${fit-image.files}/keystore.cfg`) so barebox can verify a signed FIT
  image, but `fit-image` doesn't produce a signed image or a keystore
  fragment yet (it's still UNSIGNED, see `fit-image.yaml`'s description —
  that needs its own signing-key component first). The merge mechanism
  itself is offline-tested (`tests/test_build_plan.py`'s two
  `test_barebox_extra_conf_*` cases) but **UNVERIFIED against a real
  build** — no target actually sets `extra_conf` yet.
- 2026-08-29: New top-level `helpers/` directory: shared executable helper
  scripts (not manifest YAML, so not under `manifests/`, and not
  per-component `files/` since they're cross-component). `containers.py`'s
  `run()` and `shell()` both unconditionally bind-mount `helpers/` onto
  `/usr/local/bin` (ahead of `/usr/bin` on every base image's
  Debian-default PATH), so any component's `build.command` can call a
  helper by name with no manifest wiring, and so can `emblab shell`.
  `tsa-stamp` (RFC 3161 timestamp a signed FIT image's signature nodes) is
  transcribed verbatim (already generic, stdlib-only) from
  `barebox-arm64-poc/tsa-poc/tsa-stamp.py`. `fitkeys-ctl generate|revoke`
  (RSA/EC keypair + self-signed x509 cert for FIT signing / a barebox
  keystore, with `--algo`/`--bits`/`--curve`/`--not-before`/`--not-after`,
  plus a `revoke` subcommand that re-signs the same key with a `--at` date
  already in the past) started as a straight transcription of
  `generate-fit`'s `generate_keys()` function but had to move off plain
  `openssl req -x509` onto `openssl ca -selfsign` — the former only takes a
  relative `-days +int` (rejects 0/negative), so it can't express "already
  expired"; `-selfsign` is the one openssl mode with explicit
  `-startdate`/`-enddate`, at the cost of needing a (regenerated-per-call,
  scratch-dir) minimal CA database. Verified for real against the
  already-provisioned `emblab-gnu-aarch64` container: RSA generate, EC
  generate with explicit `--not-before`/`--not-after`, and revoke on both
  (confirmed expired via `openssl x509 -checkend 0`) all produced correct
  certs through the actual `containers.run()`/bind-mount path, not just a
  standalone script run. Deliberately NOT wired into `fit-image.yaml` yet
  — see Next.
- 2026-08-29: **ADR-011**: new `build.setup` — a component's optional
  one-time setup step, tracked and force-rerun (`emblab build
  --setup-force`) independently of its `build.command`/`--force`. First
  consumer: `fit-image.yaml` now runs `fitkeys-ctl generate --out-dir keys
  --name dev-new` as its `setup`, so the signing keypair is generated once
  and never silently regenerated by an unrelated `command` change (which
  would orphan anything already signed). Not yet consumed by `command`
  itself — `mkimage -F -r -k keys` and the `.its` `signature` node are
  still open, see Next. Offline-tested only (new `state.py`/`build.py`
  mechanism); no real `fit-image` build has exercised `setup` yet.

- 2026-08-30: **ADR-012 (containerize QEMU too) — built AND verified for
  real**. `emblab run` no longer execs the host's native `qemu-system-*`
  binary (ADR-003's decision) — it runs `qemu.binary` inside a new shared
  `manifests/images/qemu-runner.yaml` udocker container (arch-agnostic:
  `qemu-system-arm` + `qemu-system-misc` apt packages cover aarch64/arm/
  riscv64), with the target's whole `workspace/artifacts/<target>/` tree
  bind-mounted at the same host path so resolved `${component.key}` args
  need no rewriting. Every target's `qemu:` block gained a required
  `image:` field (same pattern as a stack entry's own `image:`, ADR-009) —
  all 7 existing targets point it at `qemu-runner`. `emblab doctor` no
  longer checks for host `qemu-system-*` binaries — `git` + `udocker` are
  now the only two host prerequisites. 68/68 tests pass (offline).
  **Real, surfaced-and-fixed bug along the way**: `qemu-system-arm`/
  `-misc`'s hard dependency on `libibverbs1` (RDMA live-migration support,
  never used here) has a postinst that calls `addgroup`/`groupadd` to
  create the system `rdma` group — real group/user creation genuinely
  fails under udocker's unprivileged execution, confirmed three different
  ways: default proot mode (`groupadd: failure while writing changes to
  /etc/group`), `R1` (pure runc rootless namespace — apt's own privilege
  drop to `_apt` fails outright: a single-uid-mapped namespace has no room
  for a second uid), and `R2` (proot-on-runc — bind-mounts the *host's
  real* `/etc/group` in for uid/gid consistency, so the write is correctly
  refused, not a bug). Fixed by no-op-stubbing `groupadd`/`useradd`/
  `addgroup`/`adduser` in `qemu-runner.yaml`'s `provision:` before the
  package install — nothing emblab runs needs the `rdma` group or any
  other system account to actually exist. With that fix, real
  `apt-get install` + `qemu-system-riscv64 --version`/`qemu-system-aarch64
  --version` both confirmed against a real provisioned
  `emblab-qemu-runner` container. Then **`emblab build` +
  `emblab run qemu-riscv64-opensbi-barebox` end-to-end, from a clean
  `workspace/`, through the new containerized path**: real OpenSBI banner,
  S-mode handoff, and barebox reaching an interactive
  `barebox@riscv-virtio,qemu:/` shell prompt on serial — the exact same
  real-boot behavior already proven under the old host-exec path, now
  reproduced with QEMU itself running inside `udocker`, confirming
  udocker's `run` really does pass interactive stdio through correctly for
  a long-running QEMU session (not just short build commands, which was
  the only thing proven before).
- 2026-08-30: **`qemu-runner` broadened to genuinely every Debian
  `qemu-system-*` split package**, not just arm+riscv64 (the original cut
  only covered what today's 7 targets happen to need — flagged by the user
  as underselling the image's own "arch-agnostic" description). Added
  `qemu-system-x86`, `qemu-system-ppc`, `qemu-system-mips`,
  `qemu-system-sparc` to `provision:` (`qemu-system-s390x` deliberately left
  out — it isn't a real Debian package name on amd64; `qemu-system-misc`
  already ships the s390x binary, confirmed via `apt-cache policy
  qemu-system-s390x` showing no candidate and a direct install attempt
  resolving to "already the newest version"). Verified for real: a full
  `apt-get install` of the broadened list against a real
  `emblab-qemu-runner` container produced all 31 `qemu-system-*` binaries
  Debian ships (`ls /usr/bin/qemu-system-*`), with `qemu-system-x86_64`,
  `qemu-system-ppc64`, and `qemu-system-s390x` each individually confirmed
  via `--version`; re-ran `emblab run qemu-riscv64-opensbi-barebox`
  afterward and it correctly skipped re-provisioning (marker matched) and
  booted to the same real barebox prompt as before.
  **Also surfaced real udocker flakiness while iterating on this** (not an
  emblab bug, but worth knowing): `udocker rm` on a container repeatedly
  printed `Error: invalid container json metadata` while still actually
  deleting the container directory, and at least once a fresh `udocker
  create` for the exact same container *name* (immediately after a
  same-session `rm` of that name) silently failed to write `container.json`
  at all, leaving a directory with only `imagerepo.name`/`ROOT` that then
  made every subsequent `udocker run` against that name fail the same way.
  Diagnosed (not by inspecting udocker's source, just from directory
  contents) by comparing against a known-good container's directory
  (`container.json` + `.mountpoints` present) and noticing udocker tracks
  names as plain symlinks under `workspace/udocker/containers/<name> ->
  <uuid>`, not a JSON registry — a dangling one of those was also observed
  once after a partially-failed `rm`. Worked around by hand each time:
  delete the broken container directory and any dangling name-symlink
  directly with `rm -rf`/`rm -f` (not `udocker rm`, which was itself
  unreliable in the same session), then retry `create`. Never reproduced
  against a *new* container name — only ever on a name that had just been
  through a `create`+`rm` cycle in the same session — so it looks like a
  udocker-internal race/cleanup bug tied to name reuse, not anything
  `containers.py` itself is doing wrong. Not worth a driver-level
  workaround unless it recurs against real `emblab build`/`emblab run`
  usage (as opposed to the unusually rapid manual create/rm/setup cycling
  this investigation did) — logged here so a future session doesn't
  re-diagnose it from scratch.
- Unrelated to ADR-012: `workspace/udocker/containers/.../ROOT/usr/lib/modules`
  turned up with mode `000` (owned by the invoking user, but unreadable even
  by them) mid-session, which crashed a `shutil.rmtree` during `emblab clean
  --all` with a raw `PermissionError` traceback instead of a clean error.
  Root cause not fully investigated — looked like udocker's PRoot backend
  preserving/emulating a root-only permission bit from the guest rootfs
  literally on the host filesystem. Worked around by hand
  (`chmod -R u+rwx` before retrying the clean), not fixed in the driver.
  Worth a `containers.py`/`cli.py cmd_clean` follow-up if it recurs: either
  `shutil.rmtree(..., onerror=...)` with a chmod-and-retry handler, or
  `udocker rm` on tracked containers before ever touching `workspace/udocker`
  with `shutil.rmtree` directly.
- 2026-08-30: **`source.submodules` extended to accept a list of specific
  submodule paths, not just `true`/`false`** (ADR-008 amendment) —
  motivated by real breakage on `coreboot` (see Next's item 12): its
  `.gitmodules` carries many large vendor-specific 3rdparty/ trees
  unrelated to the one board this project builds, and a transient TLS
  failure fetching one of them (AMD OpenSIL, entirely irrelevant to
  qemu-aarch64) broke an otherwise-succeeding build. A list runs
  `git submodule update --init --recursive --depth 1 -- <path>...`
  (`sources.py`'s `_init_submodules`); `true` keeps its original
  all-submodules meaning for `edk2`, which needs it. `manifests.py` gained
  `_parse_submodules`, rejecting anything that isn't `true`/`false`/a
  string list with a clear `ManifestError`. New offline tests in both
  `test_sources.py` and `test_manifests.py`; 70/70 tests pass.
- 2026-08-31: **ADR-013: `emblab shell` devshell + non-root + bash
  completion**, user-requested ("devshell on components or targets", "an
  improved shell without root and bash completion"). New
  `build.shell_context()` resolves a target's stack entry (default: last
  one) the same way `build()` does per-component — same
  `ensure_image`/`ensure_builddeps`/`ensure_source` calls, so the shell
  matches a real build environment — and `emblab shell NAME
  [--component X]` uses it when `NAME` is a target, falling back to the
  previous raw-image behavior otherwise. `containers.shell()` now uses
  udocker's own documented `--hostauth --user=<host user>` for a
  non-root shell (confirmed against a real container — no
  `useradd`/`groupadd` needed, unlike ADR-012's account-creation finding,
  since this borrows the host's own passwd/group entry instead of
  creating one) and launches `bash --rcfile helpers/emblab-shell.bashrc
  -i` instead of `sh`. The rcfile turned out to be load-bearing, not
  cosmetic: confirmed against a real container that the borrowed
  `--hostauth` user has no real `$HOME` inside the container, so Debian's
  bash-completion-sourcing block (which lives in `~/.bashrc`, not the
  system-wide `/etc/bash.bashrc`) silently never ran without it —
  `shopt progcomp` was already on by bash's own default, but
  `complete -p git` stayed empty; with the rcfile, `complete -p -D` shows
  the dynamic loader registered and a forced load
  (`_completion_loader git`) does register `git`'s real completion.
  `bash-completion` added to all four images' `provision:`
  (`gnu-aarch64`/`gnu-riscv64`/`go`/`qemu-runner`). New offline test
  `test_shell_context_defaults_to_last_stack_entry_and_rejects_unknown_component`;
  also dry-ran the real `cli.py` argparse + `cmd_shell` dispatch (all four
  paths: target default-component, target explicit-component, raw-image
  fallback, and `--component` correctly rejected on a non-target) with
  container calls mocked, and `build.shell_context()` against the real
  `qemu-arm64-coreboot-barebox` target (unmocked manifests) to confirm it
  resolves `coreboot`/`gnu-aarch64` by default and `barebox`/`gnu-aarch64`
  when `--component barebox` is given. 72/72 offline tests pass. Also
  caught and fixed a stale ADR-011 claim while writing this ("`build.setup`
  runs before builddeps are installed") — no longer true since this
  session's earlier `gnat-12`-driven ordering fix moved `ensure_builddeps`
  ahead of `build.setup` too; ADR-011 updated to match.
  **NOT yet verified interactively** (an actual TTY session, tab-press
  included, can't be driven from here) — the underlying mechanisms (bash
  launch, `--rcfile` sourcing, dynamic-loader registration, `--hostauth`
  identity) are each confirmed for real via non-interactive
  `bash -i -c '...'` probes against the real `emblab-gnu-aarch64`
  container, but a live session is the real proof, see Next.
- 2026-08-31: **`emblab build qemu-arm64-coreboot-barebox` succeeds for
  real** — the first successful build this target has ever had, after
  the from-source-crossgcc path (see the old Next item 12, now resolved)
  was abandoned in favor of coreboot's own official prebuilt SDK image
  (`docker.io/coreboot/coreboot-sdk`, new `manifests/images/coreboot-sdk.yaml`).
  Confirmed for real against the pulled image before ever touching a
  manifest: `/opt/xgcc/bin/aarch64-elf-gcc` is GCC 14.2.0, already carries
  a "coreboot toolchain" version banner (built via this project's own
  `buildgcc`, just distributed prebuilt) so `toolchain.mk`'s own
  `-v`-banner check accepts it with no `CONFIG_ANY_TOOLCHAIN` workaround,
  and compiles `-std=gnu23` cleanly. `XGCCPATH=/opt/xgcc/bin/` (coreboot's
  own override mechanism, confirmed real in `util/xcompile/xcompile`)
  replaces `make crossgcc-aarch64` entirely — no more `build.setup`, no
  GMP/MPFR/MPC patch, no `ccache` flag, no `gnat-12` builddep, no
  builddeps of any kind for this component.
  Four more real, distinct bugs surfaced and fixed getting from "image
  pulls" to "real ROM comes out the other end", each confirmed against a
  real build attempt, not guessed:
  1. **coreboot-sdk's apt sources 404 on `apt-get update`**: its
     `/etc/apt/sources.list.d/debian.sources` ships `Suites: stable
     stable-updates`, a floating alias — Debian's own "stable" has since
     moved from bookworm to trixie, which apt refuses to fetch from
     without an explicit opt-in. Rather than just accept the change (real
     libc/ABI mismatch risk, installing trixie packages into what's
     actually still a bookworm rootfs), pinned the suite names to
     `bookworm`/`bookworm-updates`/`bookworm-security` explicitly.
  2. **CONTEXT.md's long-standing "mystery source-tree-wipe" bug,
     root-caused for real at last** (see the old Next item 12's history):
     coreboot's own `Makefile.mk` (not this project's) runs a bare,
     unconditional `git submodule update --init` (no path filter) at
     parse time unless `UPDATED_SUBMODULES` is already `1` — ungated by
     any make target, so it ran even for a plain `defconfig`, ignoring
     this project's own scoped `source.submodules` init entirely and
     trying to pull every submodule `.gitmodules` lists. Confirmed via an
     isolated repro outside any container: on a plain host filesystem
     this just left the tree intact but heavily bloated (ffs,
     intel-sec-tools, libgfxinit, libhwbase, open-power-signing-utils,
     opensbi, stm, vboot, 3x amd/opensil, util/goswid,
     util/nvidia/cbootimage — none needed). Under udocker, the same
     operation instead reproduced the exact wipe signature twice in a
     row. The udocker-specific destructiveness itself is still not
     understood, but setting `UPDATED_SUBMODULES=1` sidesteps the whole
     block, and the target has built successfully several times since.
  3. **Missing `3rdparty/vboot` submodule**: an earlier guess that
     qemu-aarch64 needs no submodules besides arm-trusted-firmware was
     wrong — confirmed for real, `cbfstool`'s build failed with `fatal
     error: vb2_sha.h: No such file or directory`;
     `commonlib/bsd/include/commonlib/bsd/cbfs_serialized.h`
     unconditionally includes it from vboot, needed by the host-tool
     build regardless of whether verified boot itself is enabled, not
     Kconfig-gated at all. Added to `source.submodules`.
  4. **`HOSTCC` needs the same `-std=gnu23` fix as the target compiler,
     via a different path**: coreboot's host tools (`cbfstool`,
     `util/sconfig`, ...) build with `$(HOSTCC)`, which defaults to the
     container's system `gcc` — confirmed for real, coreboot-sdk is
     Debian-bookworm-based same as `gnu-aarch64` (`gcc --version` ->
     Debian 12.2.0-14, no gcc-13/14/15 present), so `XGCCPATH` alone
     doesn't cover it. coreboot-sdk bundles its own `clang-18` (coreboot
     officially supports building with clang), confirmed to compile
     `-std=gnu23` cleanly, so `HOSTCC`/`HOSTCXX` point there instead.
  Also hit, and root-caused, real reproducible flakiness in `git
  submodule update --init --recursive --depth 1` against
  arm-trusted-firmware's own nested submodules (its own `mbed-tls`, which
  has its own nested `framework` submodule): a different nested submodule
  failed each time with a "No such file or directory" for a path git
  should have just created, and a failed attempt corrupted
  `.git/modules/<submodule>` enough that a bare retry of the identical
  command failed differently again. `sources.py`'s `_init_submodules` now
  retries up to 3 times, re-cloning the whole component from scratch
  before each retry (not just re-running the same command) — new offline
  regression test pins this. Separately, a good deal of the day's earlier
  apparent instability (files vanishing from manifests mid-edit, git
  state that didn't match expectations) turned out to just be the user
  and the assistant running `emblab build` concurrently against the same
  `workspace/` with no locking at all — not a udocker/PRoot bug. Worth a
  real fix (a lockfile around workspace access) if this recurs; not
  attempted this session.
  End result, confirmed for real: a genuine 16 MiB
  `workspace/artifacts/qemu-arm64-coreboot-barebox/coreboot/rom`, its
  FMAP layout printed back by `cbfstool` after writing showing a real
  `fallback/payload` CBFS section (1338586 bytes, non-zero — barebox
  really is bundled in). `emblab run` (actual QEMU boot) was launched for
  real afterward; full boot confirmation still pending, see Next.
  73/73 offline tests pass.
- 2026-08-31: **ADR-014**: `emblab modify <component>` / `emblab reset
  <component> [--reclone]`, motivated directly by the user hitting
  `ensure_source`'s ref-moved re-clone discarding hand edits to a
  component's source mid-debugging. `sources.mark_modified`/
  `mark_finished` verified for real (not just mocked) against a local
  throwaway git remote: clone, edit a tracked file by hand, `mark_modified`,
  make a real new upstream commit, re-run `ensure_source` — the marked tree
  is untouched (zero git calls) and the hand edit survives; `mark_finished`
  with no `--reclone` leaves the edit in place and only re-clones on the
  *next* `ensure_source` call, exactly when the ref-moved check would have
  fired anyway. 79/79 offline tests pass (6 new, covering the marker
  short-circuit, its priority over `force=True`, and `mark_finished`
  resuming normal tracking).

- 2026-08-31: **`qemu-arm64-coreboot-barebox` payload switched from
  `CONFIG_PAYLOAD_ELF` to `CONFIG_PAYLOAD_FIT`**, after two more real,
  confirmed-failed boot attempts on top of the build success recorded
  above: `CONFIG_PAYLOAD_ELF` against `images/barebox-dt-2nd.img` (real
  runtime failure: "SELF segment doesn't target RAM" — that file is
  barebox's own ARM64 Linux "Image"-format output, not an ELF, despite the
  Kconfig name suggesting otherwise) and again against `${barebox.elf}`
  (the genuine top-level ELF — still failed, it is a PIE with vaddrs
  relative to base 0, and `CONFIG_PAYLOAD_ELF`'s SELF loader takes them at
  face value); a third attempt via `CONFIG_PAYLOAD_FLAT_BINARY` (explicit
  `-l`/`-e` load address) never even reached runtime — its Kconfig lives
  inside `payloads/Kconfig`'s `if !PAYLOAD_NONE` block, and `PAYLOAD_NONE`
  defaults to `y` on arm64, so the appended config was silently dropped by
  `syncconfig` until `# CONFIG_PAYLOAD_NONE is not set` was added
  explicitly. Switched to `CONFIG_PAYLOAD_FIT` instead: barebox's own
  `arch/Kconfig` documents `BOARD_GENERIC_FIT` as producing an image
  "bootable from coreboot, barebox, or any other bootloader capable of
  booting a Linux kernel out of FIT images" — new
  `manifests/components/barebox/files/esp.cfg` merges it in via
  the existing `extra_conf` mechanism, `python3-libfdt` added as a target
  `builddeps` entry for `scripts/make_fit.py`'s `import libfdt`. Two more
  real, confirmed bugs surfaced getting the FIT path this far: (1) coreboot
  picks a FIT `/configurations` entry by matching
  `CONFIG_MAINBOARD_VENDOR`,`CONFIG_MAINBOARD_PART_NUMBER` (lowercased)
  against each bundled device tree's own `compatible` list — the
  qemu-aarch64 mainboard's real defaults normalize to "qemu,qemu-aarch64",
  which matches none of barebox's bundled DTs, not even QEMU's own virt
  machine one (real compat string "linux,dummy-virt", QEMU's own
  `hw/arm/virt.c` convention) — fixed by overriding both Kconfig strings to
  match instead of patching either project; (2) that DT wasn't even bundled
  in the first place while barebox stayed on its `efi_v8_defconfig`
  default (built for UEFI, no board DTs at all) — switched this stack
  entry to `multi_v8_defconfig` (`CONFIG_ARCH_ARM64_VIRT=y`) instead. Also
  fixed, in `coreboot.yaml`'s `build.command`: a real shell-quoting bug
  (`CONFIG_PAYLOAD_OPTIONS`'s value containing its own `-l`/`-e` flags
  broke a single-quoted append the same way the `"`-quoting bugs described
  above did) and two real Make/Kconfig staleness bugs confirmed against a
  from-scratch container run — a previously-built `ramstage.a` can survive
  a Kconfig symbol flipping on without picking up the newly-relevant object
  files it should now link (fixed with `rm -rf build` before every real
  rebuild), and even with a guaranteed-clean `build/`, coreboot's own
  `config.h` rule runs `$(MAKE) olddefconfig` then `$(MAKE) syncconfig` as
  nested recursive sub-makes lazily inside the main `-j$(JOBS)` invocation,
  which can race against that same invocation's own parallel object-list
  parsing (fixed by running `olddefconfig` ourselves, single-threaded, as
  its own step before the parallel build). `qemu.args` also switched from
  `-serial mon:stdio` to `-nographic` — this container's `qemu-runner`
  image has no gtk/sdl display module, so QEMU was falling back to a VNC
  server on `localhost:5900`, which then failed DNS resolution inside the
  container. **`emblab run qemu-arm64-coreboot-barebox` now boots for
  real, confirmed against an actual serial log**: bootblock -> romstage ->
  ramstage all complete cleanly, FIT config selection picks
  `conf-qemu-virt64.dtb` ("FIT: Choosing best match conf-qemu-virt64.dtb
  for compat linux,dummy-virt"), BL31 (ARM Trusted Firmware) starts and
  hands off to `0x40080000`, and barebox itself comes up: "barebox
  2026.08.0-g42e510a258d7 ... Board: ARM QEMU virt64", with its own 9p/
  netconsole subsystems registering — this resolves Next's old item 14
  (its `CONFIG_PAYLOAD_ELF`-era wording is now fully superseded).

  Separately, root-caused and fixed a real, general cross-component
  staleness bug in the driver itself while chasing the above: a
  component's `resolved_vars` only ever embeds an upstream sibling's
  artifact *path* (e.g. `${barebox.images}/barebox-arm64.fit`), which
  stays identical across rebuilds even when that upstream component's own
  vars change (e.g. barebox's `defconfig`) and it rebuilds completely
  different bytes at that same path — `state.component_hash()` hashed only
  the path text, so a downstream component's marker looked unchanged and
  `emblab build` silently kept embedding a stale artifact. Confirmed for
  real: switching barebox's `defconfig` did not invalidate coreboot's
  build marker. Fixed with a new `state.upstream_artifacts_hash()`,
  content-hashing every artifact already collected from earlier components
  in the stack (files and whole directories, e.g. barebox's `images`
  artifact) and folding it into `component_hash()` alongside the existing
  inputs. One-time cost: every component's marker hash changed shape, so
  the next `emblab build` of any existing target does one real rebuild per
  component even where nothing else changed. 79/79 offline tests pass.
- 2026-08-31: **`emblab run qemu-arm64-coreboot-barebox` broke again**:
  `qemu-system-aarch64: failed to find romfile "efi-virtio.rom"` on QEMU
  startup itself (before any real boot), from the pre-existing `-device
  virtio-rng-pci` — confirmed for real this is unrelated to networking:
  QEMU defaults every virtio-pci device's `romfile` property to
  `efi-virtio.rom` regardless of device type. Root cause: `qemu-runner.yaml`
  (ADR-012) installs with `--no-install-recommends`, which drops `ipxe-qemu`
  — confirmed via `apt-cache depends qemu-system-arm`/`-misc` that it's a
  Recommends, not a Depends. First guess, `qemu-system-data`, was wrong —
  confirmed for real via `dpkg -L` inside the actual container that it ships
  only BIOS/VGA-BIOS blobs and sample configs, no ROM files at all; the real
  ROMs (`efi-virtio.rom`, `pxe-virtio.rom`, etc.) live under
  `/usr/lib/ipxe/qemu/`, owned by `ipxe-qemu`, confirmed via `dpkg -L
  ipxe-qemu` after installing it. Fixed by adding `ipxe-qemu` explicitly to
  `qemu-runner.yaml`'s provision list (same pattern as the existing
  `--no-install-recommends` + explicit-package-list approach, not dropping
  the flag wholesale). Re-verified `emblab run qemu-arm64-coreboot-barebox`
  end to end for real after the fix: no romfile error, full real boot log
  again through bootblock -> romstage -> ramstage -> BL31 handoff ->
  `barebox 2026.08.0-... Board: ARM QEMU virt64`, same as the original
  confirmed boot above.
  Also hit and worked around real udocker flakiness while diagnosing this
  (not an emblab bug): manually re-running bare `udocker` CLI commands
  against `workspace/udocker` with a **relative** `UDOCKER_DIR` produced
  spurious `Error: invalid container json metadata` / "not found" failures
  that a real container.json existing on disk contradicted — switching to
  an **absolute** `UDOCKER_DIR` path made the exact same commands work
  correctly. `containers.py`'s own `_udocker_env()` already always builds
  an absolute path (`Path(workspace) / "udocker"` off an absolute
  `workspace`), so this was a manual-diagnosis-only pitfall, not a real
  driver bug — worth remembering if a future session probes `udocker`
  directly by hand from a shell. Separately (also manual diagnosis, not a
  real bug): re-running `udocker pull` on the floating `debian:bookworm-slim`
  tag mid-session fetched a newer image published as an OCI-schema manifest
  that this project's pinned udocker 1.3.17 couldn't turn into a container;
  recovered by deleting the bad container + name symlink and recreating —
  `containers.py`'s own flow never does a redundant re-pull once a
  container already exists, so this also isn't reachable through normal
  `emblab` usage, only through manual `udocker pull`-ing the same tag again
  by hand.
- 2026-08-31: **Real `helpers/` directory pollution from `emblab build`,
  root-caused and fixed in the driver**: user-reported after compiling
  `edk2` — ~25 untracked files (`stuart_build`, `pygmentize`,
  `cffi-gen-src`, `vba_extract.py`, ...) showed up under the repo's
  checked-in `helpers/` directory, none of them anything this project
  added. Root cause: `containers.py`'s `HELPERS_MOUNT` bind-mounted the
  repo's `helpers/` read-write onto `/usr/local/bin` — Debian's own
  default install target for global (non-venv) `pip`/`npm`/etc., chosen
  upstream specifically to avoid colliding with dpkg-owned `/usr/bin`.
  `edk2.yaml`'s real `build.command` runs `pip3 install
  --break-system-packages -r pip-requirements.txt` (edk2-pytool-extensions
  and its dependency tree) with no venv/`--target`, so pip's own
  console-script shims landed exactly on that bind mount and were
  physically written into the host checkout. Confirmed real and reachable
  by any component, not edk2-specific — moved `HELPERS_MOUNT` to a
  dedicated `/opt/emblab-helpers` that nothing else defaults to, and
  changed `run()`/`shell()` to prepend it onto PATH via a `sh -c 'export
  PATH="$HELPERS_MOUNT:$PATH"; exec "$@"'` wrapper (preserves exit
  codes/signals/TTY — confirmed for real against both a one-shot `run()`
  command and an interactive `--rcfile emblab-shell.bashrc` shell) instead
  of relying on the mount coincidentally sharing a path already on PATH.
  Verified for real against the actual `gnu-aarch64` container: a
  `pip3 install --force-reinstall cffi` now writes `cffi-gen-src` into the
  container's own (no-longer-host-mounted) `/usr/local/bin`, found via the
  base image's already-present default PATH, while `which fitkeys-ctl`/
  `tsa-stamp` resolve from the new `/opt/emblab-helpers` — host `helpers/`
  stays untouched either way. 79/79 offline tests pass unchanged (no test
  patches `containers.py`'s own argv construction, only the public
  `containers.run(command=...)` interface, which didn't change). ADR-013
  updated with a dated note — its own Consequences section had flagged
  this exact hardcoded-path fragility in advance ("if that mount point
  ever moves, `emblab-shell.bashrc`'s hardcoded path needs to move with
  it").
- 2026-08-31: **`ensure_source` updates submodule-heavy components in
  place instead of re-cloning from scratch, user-reported**: coreboot and
  edk2's floating `ref: master` moving upstream (or a target's patches
  changing) triggered a full `shutil.rmtree` + fresh clone + full
  `git submodule update --init --recursive` on every build — for edk2
  specifically (a dozen+ submodules, several vendoring their own further
  submodules: CryptoPkg's OpenSSL pulls in cloudflare-quiche, krb5,
  oqs-provider, wycheproof, ...) this meant re-downloading nearly
  everything, almost every time. Fixed by trying `git fetch` + `reset
  --hard FETCH_HEAD` + `clean -fd` in place first (new
  `sources._try_update_in_place`), falling back to the old
  delete-and-clone only if that fails — `git submodule update` on an
  already-initialized tree only re-fetches a submodule whose pinned
  commit actually changed, which most aren't on a routine upstream
  advance. `_run_submodule_update`'s own retry escalation got the same
  treatment: a transient network blip on one submodule (confirmed real,
  live: edk2's brotli -> oniguruma, plain TLS connect error) now gets a
  bare in-place retry before ever re-cloning; full re-clone is reserved
  for the final attempt only, same recovery-of-last-resort role it always
  had for genuine `.git/modules/` corruption (coreboot's TF-A/mbed-tls
  case). 83/83 offline tests pass (4 new/rewritten in `test_sources.py`).
  Verified for real against the actual `workspace/src/edk2` checkout
  (already real, already messy from the user's own concurrent build
  attempts): a genuine `ensure_source` in-place update re-fetched only
  `CryptoPkg/Library/OpensslLib/openssl` and
  `CryptoPkg/Library/MbedTlsLib/mbedtls/framework` (their pinned upstream
  commits had genuinely moved, cascading into openssl's own dozen nested
  submodules) while leaving `brotli`/`oniguruma`/`libfdt`/`mipisyst`/
  `jansson`/`libspdm`/`TPM`/`cmocka`/`googletest`/`subhook` — all
  unchanged — completely untouched, no network calls at all for those.
  Also caught and fixed a real crash surfaced by that same testing: this
  session's own diagnostic `emblab fetch edk2` collided with the user's
  own concurrent `emblab build` on the same `workspace/` (the
  already-tracked no-locking issue, see Next item 15) and hit
  `_run_submodule_update`'s final-retry `_reclone`, whose own `git clone`
  then ALSO failed (mid-collision) — leaving `dest` genuinely deleted from
  disk; `ensure_source`'s outer fallback then crashed trying to `rmtree`
  an already-missing directory. Now guards with `dest.exists()` first.
  edk2's real submodule graph remains genuinely flaky end-to-end across a
  from-scratch clone specifically (many independent, unrelated upstream
  hosts — github.com/{tianocore,cloudflare,google,kkos,...} — any one
  network hiccup fails the whole `--recursive` command) — confirmed real:
  a first-time `emblab fetch edk2` still failed after all 3 attempts
  (including the final re-clone) this session. That's an existing,
  unchanged characteristic of `_init_submodules`'s single all-or-nothing
  command, not something this fix introduced or fully solves — a future
  per-submodule retry loop (`git submodule foreach` with its own retry,
  rather than one big `--recursive` invocation) would be the real fix for
  *that*, if first-time edk2 clones keep failing in practice.
- 2026-08-31: **`emblab run qemu-arm64-edk2-barebox` succeeds for real —
  first-ever real boot of this target**, resolving the old Next item 6.
  Two more real, distinct `qemu-runner` firmware-ROM gaps surfaced getting
  there, same shape as the earlier `efi-virtio.rom`/`ipxe-qemu` fix: (1)
  with no `-display`/`-nographic` given, QEMU probed for gtk then sdl
  (neither installed) then fell back to a VNC server on `localhost:5900`,
  which fails DNS resolution inside the container — the exact failure
  ADR-012's coreboot-barebox target already hit and fixed with
  `-nographic`; this time fixed as a **driver-level default** instead of
  per-manifest, on user direction ("instead of putting the args in each
  yaml, let it be directly in resolve args when they are global"):
  `qemu.py`'s `resolve_args` now prepends `-display none` to any target
  that didn't already pick its own display handling (`-nographic` or its
  own `-display`) — confirmed for real this doesn't touch the
  coreboot/riscv64 targets' existing `-nographic`. (2) `-device ramfb`
  (UEFI's GOP framebuffer) defaults its romfile to `vgabios-ramfb.bin`,
  which — confirmed for real via `qemu-system-aarch64 -L help`'s
  compiled-in firmware search path — comes from the `seabios` package
  (`/usr/share/seabios/`), not `qemu-system-data` (confirmed empty of it
  via `dpkg -L`) or `ipxe-qemu`; added to `qemu-runner.yaml`. With both
  fixed, a real boot log confirms: our own freshly-built `edk2`
  (`QEMU_EFI.fd`) reaches its boot manager, EDK2's own
  `QemuKernelLoaderFsDxe` mechanism loads barebox via QEMU's `-kernel`
  fw_cfg entry (confirmed by its own trace lines: `QemuKernelStubFileOpen:
  file opened: "kernel"`, `918528 bytes` — the same `barebox-dt-2nd.img`
  size as every other target using this file), and barebox itself comes up
  fully: `barebox 2026.08.0-... Board: barebox EFI payload`, with real EFI
  variable/framebuffer-console subsystems registering. ("Image type X64
  can't be loaded on AARCH64 UEFI system." earlier in the log is benign —
  EDK2 correctly rejecting some unrelated PCI option ROM, not a failure.)
  Separately, user-requested (ahead of any target needing it):
  `qemu-system-x86` added to `qemu-runner.yaml` too, confirmed installed
  for real (`qemu-system-x86_64`/`-i386` both present after
  re-provisioning) — also corrects a real doc/reality gap this surfaced:
  the 2026-08-30 Proven entry above claiming `qemu-runner` was already
  broadened to "genuinely every Debian `qemu-system-*` split package"
  (x86/ppc/mips/sparc) was never actually committed to
  `qemu-runner.yaml` — `git log` on the file shows no such change; that
  broadening apparently never made it out of a local/uncommitted edit.
  Only `qemu-system-x86` is added now (what was actually asked for); the
  ppc/mips/sparc claim stays unreconciled unless separately requested.
  83/83 offline tests pass unchanged (index-based `-bios`/`-kernel` arg
  lookups in `test_build_plan.py` are unaffected by the prepended
  `-display none`). `qemu-arm64-uefi-barebox`, `qemu-arm64-secureboot`,
  `qemu-arm64-secureboot-uboot`, and `qemu-arm64-edk2-fvbootdxe-barebox`
  all share the identical `mon:stdio`-without-`-display` pattern and now
  get the same fix automatically via the driver default — none of them
  has actually been run since, still open, see Next.
- 2026-08-31: **`qemu-arm64-coreboot-barebox` payload switched again, from
  barebox's own FIT (confirmed booting for real, see the entry above) to
  a real edk2 `UefiPayloadPkg` build as coreboot's payload, with barebox
  now booting off a virtio-blk-attached UEFI removable-media disk image
  instead of being bundled into CBFS directly — a deliberate architecture
  change on explicit direction ("barebox must be built as an efi stubbed
  payload and ... coreboot either [has] the capacity to load efi stubbed
  binaries or load something that will do it"), not a regression from the
  previously-working FIT approach (that config's full history is preserved
  above; this target's own file now documents the new one instead of
  both). **Two real, confirmed-and-fixed bugs, one real unresolved
  blocker**:
  1. Coreboot's own `payloads/external/edk2/Makefile` (the thing
     `CONFIG_PAYLOAD_EDK2`/`CONFIG_EDK2_UEFIPAYLOAD` would normally
     trigger) hardcodes `-a IA32 -a X64`/`-D BUILD_ARCH=X64` (and `-a
     IA32` for the Universal Payload variant) with no AARCH64 codepath at
     all — confirmed by reading the whole file — despite
     `Kconfig.name`'s `depends on ARCH_X86 || ARCH_ARM64` nominally
     allowing selection on this board. Worked around by building
     `UefiPayloadPkg` for AARCH64 through this project's own `edk2`
     component instead (already proven for `ArmVirtQemu`) — confirmed for
     real that `UefiPayloadPkg.dsc` genuinely does declare
     `SUPPORTED_ARCHITECTURES = IA32|X64|AARCH64` and has a real
     `[Components.AARCH64]`/`[LibraryClasses.AARCH64]` section (PL011
     serial, VirtioBlkDxe/PartitionDxe/FatPkg/BdsDxe for real UEFI
     removable-media boot) — it is coreboot's own Makefile integration
     that never grew an AARCH64 path, not upstream edk2. `edk2.yaml`
     gained `vars.build_macros` (extra `-D` flags, empty by default, same
     conditionally-populated-var trick as `fv_boot_app_flag`) and
     `vars.fd_name` (the FDF's own FD output filename differs per
     platform: `QEMU_EFI.fd` for `ArmVirtQemu`, `UEFIPAYLOAD.fd` — real,
     confirmed uppercased regardless of the `[FD.UefiPayload]` section's
     own casing — for `UefiPayloadPkg`); `artifacts.fd`'s template also
     dropped its hardcoded hyphen (`UefiPayloadPkg.dsc` sets its own
     `OUTPUT_DIRECTORY = Build/UefiPayloadPkg$(BUILD_ARCH)` with none,
     confirmed by reading the dsc, unlike `ArmVirtQemu.dsc`'s hyphenated
     EDK2-default naming) in favor of putting the hyphen in
     `edk2_build_arch` itself, so the same template serves both — the two
     already-proven `ArmVirtQemu` targets updated to
     `edk2_build_arch: "-AArch64"` accordingly, re-verified against the
     real manifest loader (`emblab show target`), not just offline tests.
     Fed into coreboot via `CONFIG_PAYLOAD_ELF` (not `CONFIG_PAYLOAD_EDK2`,
     for the reason above) — confirmed correct for real by reading
     `util/cbfstool/cbfstool.c`: `add-payload`'s
     `cbfstool_convert_mkpayload` tries ELF, then FIT, then a raw UEFI
     firmware volume (`parse_fv_to_payload`) before giving up, and the
     real `UEFIPAYLOAD.fd` built here is a raw FV (confirmed via `od`:
     `_FVH` signature at file offset 0x28, no ELF magic at all), so it is
     picked up via that FV fallback despite the misleading Kconfig name —
     same generic cbfs "payload" type barebox's own former FIT payload
     used.
  2. `UefiPayloadPkg.fdf`'s own `DEFINE FD_BASE = 0x00800000` default
     (also feeds `PcdPayloadFdMemBase`) is an x86 assumption — confirmed
     for real to fail on this board: a first real build+boot attempt got
     a genuine `cbfstool` `SELF segment doesn't target RAM: 0x00800000`
     at runtime, since this board's real RAM (confirmed from the same
     boot log's own coreboot table dump) only starts at `0x40000000`.
     Fixed via `-D FD_BASE=0x48000000` in the edk2 stack entry's
     `build_macros`, comfortably inside the free RAM range coreboot's own
     table showed unused. Also ruled out, cleanly but not the actual
     cause: `payloads/Kconfig`'s payload-compression choice defaults to
     `COMPRESSED_PAYLOAD_NONE` only when `PAYLOAD_FIT_SUPPORT` is
     selected (which barebox's former `CONFIG_PAYLOAD_FIT` payload got
     automatically, `CONFIG_PAYLOAD_ELF` does not) — confirmed by reading
     `payloads/Kconfig` directly, and confirmed for real via a second boot
     attempt with `CONFIG_COMPRESSED_PAYLOAD_NONE=y` added explicitly:
     the boot log's own `it's not compressed!` line confirms the fix
     applied, but produced the exact same hang, ruling out an LZMA
     round-trip bug as the actual cause.
  3. **Still unresolved, real**: with both fixes applied, a real boot log
     confirms the payload segment loads correctly (uncompressed, dstaddr
     `0x48000000` matching `FD_BASE`, entry point `0x4800321c`) and BL31
     hands off cleanly — `coreboot`'s own `src/arch/arm64/boot.c` always
     enters any payload at EL2 unconditionally (`get_eret_el(EL2,
     SPSR_USE_L)`, confirmed by reading it directly), the same path
     barebox's own FIT payload already booted through successfully, so
     EL2 entry itself is confirmed not the problem — but there is zero
     further console output at all past that handoff, and a real 60s
     `emblab run` timeout confirms QEMU is still running (not
     crashed/exited) the whole time. `x0` on entry (`0x7ffdc000`) matches
     where coreboot's own log says it wrote its handoff table, and
     `UefiPayloadPkg.dsc` resolves `BlParseLib` to
     `UefiPayloadPkg/Library/CbParseLib` for `BOOTLOADER=COREBOOT`, so the
     handoff convention looks architecturally correct by inspection alone
     — the actual cause has not been isolated. A `-d
     guest_errors,unimp,int -D <logfile>` QEMU diagnostic attempt produced
     no log file at all (real, unexplained — worth a follow-up in its own
     right, not investigated further this session) so no CPU-exception
     trace was captured either. Real next steps: a QEMU gdbstub-attached
     session (`-s -S`, then inspect PC/registers directly), or an early
     raw MMIO UART poke patched directly into
     `UefiPayloadPkg/UefiPayloadEntry/UefiPayloadEntry.c` (module type
     `SEC`, `_ModuleEntryPoint`) to bisect how far real execution gets
     before whatever is silencing it — see Next.
  83/83 offline tests pass unchanged.
## In progress
- `qemu-arm64-coreboot-efi-barebox` experimenting with coreboot's native
  `CONFIG_PAYLOAD_EDK2`/`CONFIG_EDK2_UNIVERSAL_PAYLOAD` fetch instead of the
  external `edk2-uefipayload` emblab component (see commit `2cb6489`,
  2026-09-02) — see Next item 17, real and currently blocking.

## Next
1. `emblab run qemu-arm64-uefi-barebox` — confirm the real
   `barebox-dt-2nd.img` from the build above actually boots in QEMU. This
   is the one remaining unconfirmed step for the smaller seed target. Now
   gets `-display none` for free from `qemu.py`'s driver default (see
   Proven) — the VNC/DNS failure `qemu-arm64-edk2-barebox` just hit would
   otherwise have blocked this one identically, since both share the same
   `mon:stdio`-without-`-display` args shape.
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
6. ~~`emblab build qemu-arm64-edk2-barebox`~~ — **RESOLVED for real,
   2026-08-31: both build and `emblab run` succeed, see Proven** — edk2
   chain-loads barebox via its own `QemuKernelLoaderFsDxe` fw_cfg
   mechanism and barebox reaches `Board: barebox EFI payload` for real.
7. `emblab run qemu-arm64-edk2-fvbootdxe-barebox` — the build now succeeds
   for real (see Proven), but confirm it actually boots `barebox` via
   `FvBootDxe` with NO `-kernel` flag present — that's the real proof
   `FvBootDxe` is finding and loading the embedded payload, not QEMU doing
   it a different way. If the hand-reconstructed patch turns out wrong in
   some way real *booting* surfaces (as opposed to building, already
   clean), fix `manifests/components/edk2/files/0001-fvbootdxe-bundle-app.patch`
   directly rather than re-deriving it from the upstream POC again.
8. A second riscv64 bootstack (e.g. U-Boot instead of/alongside barebox)
   or a second architecture entirely — `qemu-riscv64-opensbi-barebox`
   proved the pattern generalizes cleanly: a new image + component (if the
   arch needs one not covered by an existing component) + target manifest,
   no changes needed to already-shared components (ADR-009's whole point).
9. Wire the new `helpers/fitkeys-ctl`/`tsa-stamp` into an actual signed-FIT
   path: `fit-image.its` needs a `signature` node (dropped when the `.its`
   was trimmed for ADR-005 — see the real one still in
   `barebox-arm64-poc/fit-image.its`), `fit-image.yaml`'s command needs to
   call `fitkeys-ctl generate`/`mkimage -F -r -k` and produce the
   `keystore.cfg` fragment `barebox.yaml`'s `vars.extra_conf` (see Proven)
   already knows how to consume, opt-in via a var so today's unsigned
   `qemu-arm64-fit` target is unaffected.
10. ADR-012 (containerized QEMU) is real-verified for
    `qemu-riscv64-opensbi-barebox` only — the 6 arm64 targets all point
    `qemu.image` at the same `qemu-runner` image and share the exact same
    `containers.run()` path, so this is low-risk, but none of them has
    actually been re-run through it yet (items 1/3/7 above, whenever they're
    next attempted, will exercise it for arm64 for the first time).
11. `cmd_clean --all`'s `shutil.rmtree(WORKSPACE)` can crash with a raw
    `PermissionError` (see Proven's "Unrelated to ADR-012" entry) if a
    udocker container under `workspace/udocker` has a directory with mode
    `000` in it — happened once this session, worked around by hand
    (`chmod -R u+rwx`), not fixed in the driver. Either wrap the rmtree with
    an `onerror` handler that chmods-and-retries, or have `cmd_clean` run
    `udocker rm` on every tracked container first.
12. ~~`emblab build qemu-arm64-coreboot-barebox` blocked on crossgcc~~ —
    **RESOLVED for real, 2026-08-31: the whole from-source-crossgcc
    approach was abandoned, not fixed.** After extensive real debugging of
    `make crossgcc-aarch64` (a GCC-tarball `asan.c`/`.cc` patch mismatch,
    then a from-scratch-every-retry driver gap fixed via `build.setup`,
    then a real `sources.py` patch-verification gap, then real download
    404s trying a `-m`/mirror flag — the full blow-by-blow of that
    abandoned path is preserved in this file's git history, not repeated
    here), the user asked to use coreboot's own official prebuilt SDK
    image instead. See Proven's 2026-08-31 entry for the real, successful
    outcome and everything that took to get there.
13. **ADR-013's `emblab shell` devshell** — every individual mechanism
    (`--hostauth`/`--user=` non-root, `bash --rcfile ... -i`, the
    bash-completion dynamic loader) is confirmed against a real container
    via non-interactive `bash -i -c '...'` probes, but nobody has actually
    sat at a live `emblab shell qemu-arm64-coreboot-barebox` (or any other
    target) session and pressed TAB for real, or confirmed the prompt/
    `cd`-ability/general usability feels right end to end. Cheap to check
    next time any target's build environment needs poking at by hand.
14. ~~`emblab run qemu-arm64-coreboot-barebox` — confirm the real
    `coreboot.rom` from the build above actually boots and hands off to
    barebox for real~~ — **RESOLVED for real, 2026-08-31: confirmed
    against a real serial log, see Proven** (the payload also changed from
    `CONFIG_PAYLOAD_ELF` to `CONFIG_PAYLOAD_FIT` along the way — the
    `coreboot.rom` this item originally referred to no longer exists in
    that form).
15. `workspace/` has zero locking around concurrent access — confirmed a
    real, repeated source of "directory not empty"/git-corruption
    failures this session when two `emblab build` invocations (this
    session's own attempts and the user's, run at the same time) hit the
    same component's source tree. Worth a real fix if this recurs: a
    lockfile per target (or per component) that `emblab build`/`emblab
    run` hold for their duration, refusing or waiting rather than racing.
    Not attempted this session — real build attempts were serialized by
    hand instead once the pattern was recognized. Recurred again this
    session (two concurrent coreboot builds this time), same symptom
    shape (random `unable to rename temporary ... No such file or
    directory` failures across unrelated object files, from a
    concurrent `rm -rf build` racing an in-flight `-j` compile) —
    resolved by hand again, same as before, not the driver.
16. `qemu-arm64-coreboot-barebox`'s new UefiPayloadPkg-as-coreboot-payload
    approach still does not boot — the payload loads and BL31 hands off
    to it cleanly, but there is zero console output past that point and
    the real cause has not been isolated yet. See Proven's 2026-08-31
    entry for everything already ruled out (load address, EL2 entry,
    compression) and the two concrete next diagnostic steps (QEMU
    gdbstub session, or an early raw UART poke patched into
    `UefiPayloadEntry.c`).

17. ~~`qemu-arm64-coreboot-efi-barebox`'s native `CONFIG_PAYLOAD_EDK2` path
    hangs on an interactive git credential prompt~~ — **root-caused for
    real, 2026-09-02, two distinct bugs, both fixed:**
    1. `payloads/external/edk2/Makefile`'s `$(EDK2_PATH)` rule only
       re-clones when the directory is entirely missing, and swallows
       `git fetch`'s stderr — an interrupted `git clone` (the credential
       hang below, mid-flight) had left a real half-initialized repo
       (remote configured, zero commits, no fetch refspec), so every later
       build just fetched nothing and failed with the misleading `refs/tags/
       edk2-stable202608 is not a valid git reference`. Fixed with
       `manifests/components/coreboot/files/0001-edk2-payload-self-heal-clone-and-fetch-tags.patch`
       (ADR-007): re-clone whenever `$(EDK2_PATH)` has no `HEAD`, fetch with
       `--tags` and a fallback refspec, fail loud instead of `2>/dev/null`.
    2. The credential prompt itself: confirmed for real, repeatably, that
       `git ls-remote https://github.com/tianocore/edk2` succeeds from the
       host but fails every time from inside the `coreboot-sdk` udocker/proot
       container with `fatal: could not read Username ... terminal prompts
       disabled` — `GIT_CURL_VERBOSE=1` showed why: GitHub answers the HTTP/2
       `POST .../git-upload-pack` (the real pack negotiation, after a
       perfectly good `200` on the `info/refs` GET) with a genuine `401` +
       `www-authenticate: Basic`, i.e. HTTP/2 request framing is getting
       corrupted somewhere in proot's syscall interception and GitHub reads
       it as unauthenticated. `git -c http.version=HTTP/1.1 ls-remote ...`
       fixed it instantly, twice in a row, same container. Fixed by adding
       `git config --system http.version HTTP/1.1` to `coreboot-sdk.yaml`'s
       `provision:` (applied to the live container too, not just the
       manifest) plus `GIT_TERMINAL_PROMPT: "0"` in its `env:` (was
       previously only exported inline in `coreboot.yaml`'s `build.command`,
       so a manual `emblab shell` session got no protection at all — this
       makes it apply everywhere). Only affects `coreboot-sdk`: every other
       image's git usage goes through emblab's own `sources.py`, which runs
       `git` on the host, never inside a container.
    Still real and unconfirmed: the fetch/clone step now succeeds, but this
    session didn't get a `qemu-arm64-coreboot-efi-barebox` build far enough
    to hit the *other*, already-documented gap in this same file's header
    comment — coreboot's `payloads/external/edk2/Makefile` hardcodes `-a
    IA32`/`-D BUILD_ARCH=X64` with no AArch64 codepath at all, so this native
    path may still not produce a working AArch64 build even now that it can
    fetch. The known-working fallback if that's confirmed a real blocker:
    the external `edk2-uefipayload` component + coreboot's
    `CONFIG_PAYLOAD_FILE="${edk2-uefipayload.payload}"` (same shape as
    `qemu-arm64-coreboot-barebox`'s UefiPayloadPkg-as-payload entry under
    Proven).

## Open questions
- Pin exact git refs (tags/SHAs) for `tf-a`, `optee-os`, `barebox`,
  `opensbi` once a known-good combination is found — all currently pin
  `ref: master` (barebox's and opensbi's proven builds above were still
  against `master`), which is intentionally provisional.
- Once refs are pinned to exact commits (not branches), `sources.py`'s
  `git clone --branch <ref>` will need to change to `git fetch <url> <sha>
  && git checkout FETCH_HEAD`, since most git servers don't advertise
  arbitrary commits for a shallow branch clone.
- ~~Which architecture/bootstack combination to add next~~ — resolved:
  `qemu-riscv64-opensbi-barebox` (OpenSBI+barebox, not U-Boot as originally
  guessed) is built AND booted for real, see Proven. A riscv64+U-Boot
  target is still a natural follow-up if a second riscv64 bootstack is
  wanted later (u-boot.yaml already exists for arm64 — would need its own
  riscv64 defconfig/vars, same shape as barebox's above).

## Environment notes
- `python3` 3.14.6, no `uv`/`poetry`/`hatch` — `pip` (via venv) only.
- `udocker` at `~/.local/bin/udocker`. emblab sets `UDOCKER_DIR` to
  `workspace/udocker` (project-local), never touches `~/.udocker`.
- `qemu-system-aarch64`, `qemu-system-riscv64`, `qemu-system-arm` are
  already installed at `/usr/bin` on this machine, but as of ADR-012 emblab
  no longer uses them — `qemu-runner`'s own containerized copies are what
  `emblab run` actually execs now.
- `runc`, `newuidmap`, `unshare` are also present on this machine (checked
  while investigating ADR-012's `libibverbs1` postinst failure) — not used
  by emblab (default proot mode, same as every other image, is what worked
  once `groupadd`/`useradd` were stubbed), but useful to know they're there
  if a future image ever needs `udocker setup --execmode=R1`/`R2`.
