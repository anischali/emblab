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
forking the component or affecting targets that don't want it.

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
6. `emblab build qemu-arm64-edk2-barebox` — the plain (non-`FvBootDxe`)
   edk2 target. `edk2.yaml`'s build command now has a real, working build
   behind it (see Proven — same component, same `GCC` toolchain fix and
   `edk2_build_arch` var apply here too), but this exact target hasn't
   been attempted for real yet; expect real wall-clock time on first build
   (CryptoPkg's vendored OpenSSL/mbedTLS submodules are large) even though
   `edk2`'s source is already cloned from the `fvbootdxe` build above.
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
12. `emblab build qemu-arm64-coreboot-barebox` — currently BLOCKED on a
    real upstream coreboot bug, not an emblab manifest issue. 2026-08-30
    session fixed every guessed detail this target originally shipped
    with (all confirmed against real clones — see Proven): the
    `crossgcc-aarch64` target name (was `crossgcc-arm64`); the defconfig
    (`configs/config.emulation_qemu-aarch64` doesn't exist upstream —
    replaced with a minimal fragment the component now supplies itself,
    `manifests/components/coreboot/files/configs/config.emblab_qemu_aarch64`);
    submodule scoping (was pulling in coreboot's entire unrelated
    `3rdparty/` vendor-submodule set — see ADR-008's amendment); and
    barebox's own defconfig (target had `efi_v8_defconfig`, an EFI/PE32
    build wrong for coreboot's raw `PAYLOAD_ELF` — fixed to
    `multi_v8_defconfig`, confirmed to produce the same `barebox-dt-2nd.img`
    every other target uses). Pointing coreboot at the image's external
    `aarch64-linux-gnu-` toolchain instead of building crossgcc was also
    tried for real (via `CONFIG_ANY_TOOLCHAIN=y`) and confirmed NOT
    viable: coreboot's `main` requires GCC 14+ (`-std=gnu23` in
    `Makefile.mk`), the `gnu-aarch64` image only has GCC 12.2.0 (host and
    cross), and bookworm-backports carries no newer `gcc` package at all —
    reverted to `make crossgcc-aarch64` per explicit user direction after
    presenting the tradeoff.
    **The real, current blocker**: `make crossgcc-aarch64` itself fails
    building coreboot's own toolchain — reproduced identically twice from
    a clean clone — applying
    `util/crossgcc/patches/gcc-15.2.0_asan_shadow_offset_callback.patch`:
    the patch's diff header targets `gcc/asan.c`, but the `gcc-15.2.0`
    tarball it's applied against has `gcc/asan.cc` (renamed upstream in
    GCC at some point after the patch was last updated) — `patch` can't
    auto-locate the file, prompts interactively for a filename with no
    tty attached, and the patch is skipped/fails, aborting the whole
    crossgcc build (`util/crossgcc/buildgcc`'s own `-y`/`--nocolor`
    auto-answer flags, used by upstream's own Jenkins CI per
    `Makefile.mk`'s `jenkins-build-toolchain` target, are NOT what our
    `crossgcc-aarch64` command invokes — worth trying next). This is
    upstream coreboot/GCC-tarball staleness on the currently-pinned
    `ref: main`, not anything in this project's manifests.
    **Also observed, real and 100% reproducible (not a one-off), but
    root cause NOT understood**: immediately after that crossgcc failure,
    the coreboot clone's top level is left stripped down to just
    `3rdparty/`, `payloads/`, `tests/`, `util/` — `Makefile`, `src/`,
    `configs/`, `.git`, `Documentation/`, etc. are all gone, confirmed via
    `find -maxdepth 1` both times, on two independent clean clones. Not
    disk space (282G free throughout). `emblab`'s own git repo is
    unaffected — `workspace/src/coreboot`'s `git status` was initially
    (wrongly) read as emblab's own repo status because `.git` itself was
    among the missing paths, which is what surfaced this. coreboot's own
    `clean-for-update` target (`rm -rf $(obj) .xcompile`, checked against
    a fresh scratch clone) is NOT the cause — too narrow. Never
    investigated further (would need tracing the actual `make`/`patch`
    process under udocker/PRoot, e.g. checking whether `$(top)`/`pwd`
    resolves differently than the real host bind-mount path under proot's
    syscall emulation) — worth a closer look if this recurs on a
    component that isn't already blocked upstream, since silently losing
    most of a source tree is a more serious class of udocker/PRoot issue
    than the container-registry flakiness ADR-012 already documented.
    Next attempt: either retry with `BUILDGCC_OPTIONS=-y` (skips the
    interactive prompt, may or may not actually fix the patch mismatch),
    hand-fix the patch's path (`gcc/asan.c` -> `gcc/asan.cc`) via this
    project's own patch-application mechanism if that's viable for
    crossgcc's internal patches, or pin `coreboot`'s `ref` to a commit
    before this GCC 15.2.0 bump.
    **2026-08-30 follow-up (not yet re-attempted for real)**: user reported
    a real `make crossgcc-aarch64` run getting further than the above (the
    `asan.c`/`asan.cc` patch applied clean this time — possibly upstream
    drift again, unconfirmed) but restarting the whole
    gmp/mpfr/mpc/binutils/gcc-15.2.0 download-and-build from scratch on
    every retry, plus hitting `buildgcc`'s "No compatible Ada compiler
    (GNAT) found" notice. Root-caused the rebuild-from-scratch part as an
    emblab driver gap, not upstream: `coreboot.yaml`'s `make
    crossgcc-aarch64` line lived in `build.command`, which has no
    inter-step idempotency of its own — any retry re-ran it in full even
    though `make crossgcc-aarch64` should itself be a no-op the second time.
    Fixed by moving it into `build.setup` (ADR-011's tracked/forced-
    independently-of-`command` mechanism, already proven for
    `fit-image`'s key generation) — a retry after a `command`-only failure
    now skips crossgcc entirely via its own marker; `emblab build
    --setup-force` still forces a real rebuild when wanted. Also added
    `gnat-12` to the target's `builddeps` (matches `gnu-aarch64`'s system
    `gcc` 12.2.0 — `buildgcc` needs a host GNAT matching the *host* gcc it
    bootstraps against, not the GCC 15.2.0 being built) so the Ada frontend
    builds instead of being silently skipped. Along the way, caught and
    fixed a real ordering bug this refactor would otherwise have hit:
    `build.py`'s `ensure_builddeps()` only ran inside the `build.command`
    branch, so a component's `build.setup` step (which now needs those same
    builddeps — e.g. `gnat-12`) would have run in a container that hadn't
    installed them yet. Fixed by hoisting the (already marker-based
    idempotent) `ensure_builddeps()` call to run once before `build.setup`,
    covering both steps; new regression test
    `test_setup_step_runs_after_builddeps_installed_and_is_skipped_when_unchanged`
    in `tests/test_build_plan.py` pins the ordering plus setup's own
    independent marker (skipped when unchanged, rerun only via
    `--setup-force`).
    **Also confirmed against the real clone**: no way exists to make
    `buildgcc` install GMP/MPFR/MPC/binutils/GCC instead of compiling them
    — `util/crossgcc/buildgcc`'s GCC step hardcodes
    `--with-gmp/--with-mpfr/--with-mpc` to its own from-source build tree
    (`util/crossgcc/xgcc`), with no flag to point at system packages, and
    there's no `myhelp()`-listed option for it either (checked the full
    flag list). What buildgcc DOES support, confirmed in the same script:
    `-y|--ccache` (`BUILDGCC_OPTIONS=-y`, the same flag coreboot's own
    `jenkins-build-toolchain` Makefile target passes) — added `ccache` to
    the target's `builddeps` and `BUILDGCC_OPTIONS=-y` to `coreboot.yaml`'s
    `setup`. Still compiles from source every time, but caches objects in
    the udocker container's persistent `$HOME/.ccache` (the container is
    reused across runs, not recreated — ADR-004), which should also help
    resilience against the mystery source-tree-wipe bug below since the
    cache lives outside the source tree.
    **User then asked to avoid building GMP/MPFR/MPC/binutils/GCC from
    source entirely, "install the deps instead of building them"**. Read
    the real `util/crossgcc/buildgcc` script in full to check feasibility:
    confirmed binutils/GCC 15.2.0 themselves have no install-instead-of-
    build option (no flag, and no matching pre-built aarch64-elf bare-metal
    GCC 15.2.0-with-coreboot's-patches exists as a distro package — same
    conclusion as the already-ruled-out CONFIG_ANY_TOOLCHAIN route above).
    But GMP/MPFR/MPC are different: they're pure host build-prerequisites
    for GCC's own configure (binutils's own build never references them at
    all — confirmed, `build_BINUTILS()` has no `--with-gmp`/etc), the
    `-P GCC` package list (`PACKAGES="GMP MPFR MPC BINUTILS GCC"`) is driven
    entirely by one script variable with no other conditional gating the
    download/build loops, and `bootstrap_GCC()`/`configure_GCC()`'s
    `--with-gmp=$TARGETDIR`/`--with-mpfr=$TARGETDIR`/`--with-mpc=$TARGETDIR`
    just needs to be **absent** for GCC's configure to auto-detect the
    system copies instead (standard distro-packaging practice, not a hack).
    New `files/0001-crossgcc-use-system-gmp-mpfr-mpc.patch` (against
    `util/crossgcc/buildgcc`, ADR-007's mechanism, first patch for this
    component) drops `GMP MPC MPFR` from that package list and removes the
    three `--with-*` flags from both functions — generated as a real `git
    diff` directly against the actual clone under
    `workspace/src/coreboot` (not hand-reconstructed), and confirmed with
    `git apply --check` against that same clone (reverted after generating
    the patch, clone left unmodified). `libgmp-dev`/`libmpfr-dev`/
    `libmpc-dev` were already in the target's `builddeps` from the earlier
    session (added in case buildgcc's own build of GMP/MPFR/MPC needed
    them as build-time deps — turns out they're now needed for a different
    reason, providing the system copies directly); Debian bookworm's
    versions (GMP 6.2.1, MPFR 4.2.0, MPC 1.3.1) are well above GCC 15.2.0's
    minimums. 71/71 offline tests pass (no new test — same precedent as
    the FvBootDxe/dummy-hwrng patches, which also aren't offline-content-
    tested, just `git apply --check`-verified and documented here). NONE of
    this session's coreboot-toolchain changes (setup/builddeps reorder,
    `gnat-12`, `ccache`, or this new patch) are real-build-verified yet —
    this doesn't touch the still-open `asan.c`/`.cc` or mystery-source-tree-
    wipe issues below, which need a real run to re-check; the source-tree
    wipe bug in particular could also wipe this new patch's applied state,
    same as anything else in that tree, forcing `sources.py`'s own
    patches-hash re-apply logic to redo it on the next build (expected
    behavior, not new risk).
13. **ADR-013's `emblab shell` devshell** — every individual mechanism
    (`--hostauth`/`--user=` non-root, `bash --rcfile ... -i`, the
    bash-completion dynamic loader) is confirmed against a real container
    via non-interactive `bash -i -c '...'` probes, but nobody has actually
    sat at a live `emblab shell qemu-arm64-coreboot-barebox` (or any other
    target) session and pressed TAB for real, or confirmed the prompt/
    `cd`-ability/general usability feels right end to end. Cheap to check
    next time any target's build environment needs poking at by hand.

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
