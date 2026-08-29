# CONTEXT.md

Read this first. Then `CLAUDE.md`, then `docs/architecture/decisions/`.

## Status
Phase 1 scaffolding complete (CLI, manifest schema, seed manifests, ADRs,
offline unit tests). Phase 2 — actually running a build against the network
— has not started.

## Proven
- 2026-08-29: `bash bootstrap.sh` — venv + `pip install -e ".[dev]"` +
  `emblab doctor` all succeeded from a clean checkout in well under a
  minute (no network beyond PyPI). `doctor` confirmed git, udocker, and all
  three qemu-system-* binaries already present.
- 2026-08-29: `pytest` — 26/26 offline tests pass (manifest validation,
  templating, graph ordering/cycle detection, and a full build-plan dry run
  whose rendered `tf-a` command was asserted to exactly match the flag
  structure transcribed from `barebox-arm64-poc/build.sh`).
- 2026-08-29: `emblab list`, `emblab show target ...`, `emblab clean --all`,
  and the error path for an unknown target (`emblab build
  nonexistent-target` → clean `error: manifest not found: ...` + exit 1)
  all exercised manually against the real CLI and behave as designed.
- **Not yet proven**: an actual `emblab build <target>` against the real
  network/udocker/git, or `emblab run` actually booting QEMU. This is
  Phase 2 — see Next below. In particular `barebox.yaml`'s build command is
  still unverified against a real clone.

## In progress
Nothing in flight.

## Next
1. `bash bootstrap.sh`, then `source .venv/bin/activate`.
2. `emblab doctor` — confirm git/udocker/qemu are all present on this machine.
3. `emblab build qemu-arm64-uefi-barebox` — the smaller of the two seed
   targets (barebox only, no TF-A/OP-TEE). This is where
   `manifests/components/barebox.yaml`'s build command gets validated
   against a real clone for the first time — it is currently marked
   UNVERIFIED. Fix the command there if it doesn't match reality, and
   record what actually worked in this file's Proven section.
4. `emblab run qemu-arm64-uefi-barebox` — confirm it actually boots.
5. Once barebox is confirmed, attempt `emblab build qemu-arm64-secureboot`
   (three components: optee-os, barebox, tf-a — this is a long build,
   expect real wall-clock time for OP-TEE and TF-A from clean).
6. `emblab run qemu-arm64-secureboot`.

## Open questions
- Pin exact git refs (tags/SHAs) for `tf-a`, `optee-os`, `barebox` once a
  known-good combination is found — all three currently pin `ref: master`,
  which is intentionally provisional.
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
