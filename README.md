# emblab

A declarative build/experiment lab for embedded bootloader and firmware
stacks — TF-A, OpenSBI, OP-TEE, U-Boot, barebox, EDK2 — across multiple
architectures, built through containerized cross-toolchains and run in
QEMU.

Read `CONTEXT.md` for current status and next steps, and
`docs/architecture/decisions/` for why it's built this way.

## Quick start

```bash
git clone <this-repo> emblab && cd emblab
./bootstrap.sh
source .venv/bin/activate
emblab list
```

`bootstrap.sh` only touches PyPI (a venv + `pip install -e .`) — it does not
clone any firmware source or pull any container image, so it finishes in
well under a minute on a normal connection. It ends by running `emblab
doctor`, which checks for `git`, `udocker`, and the `qemu-system-*` binaries
your target architectures need.

## Host prerequisites

- Python ≥ 3.9 and `pip` (bundled with Python).
- `udocker` (`pip install --user udocker` if `emblab doctor` reports it
  missing) — pure Python, rootless, no daemon. **Linux only**: udocker's
  execution backends need a Linux kernel underneath. On macOS or Windows,
  run emblab inside a lightweight Linux VM (Lima/Colima on macOS, WSL2 on
  Windows) — the manifests and CLI are identical there, only the host
  substrate differs. See `docs/architecture/decisions/ADR-002-*.md`.
- `git`.
- The `qemu-system-*` binaries for whichever architectures you're
  targeting (e.g. `qemu-system-aarch64`), installed via your host package
  manager. emblab runs QEMU natively on the host, never inside a container
  — see `docs/architecture/decisions/ADR-003-*.md`.

## How it's organized

```
manifests/
  images/       # cross-toolchain container profiles (base image + apt-get provisioning)
  components/   # one bootloader/firmware piece each: source repo+ref, image, build command, artifacts
  targets/      # a named, composed boot chain: ordered components + a QEMU invocation
```

**Components are pure.** A component (`manifests/components/tf-a.yaml`, say)
describes how to build one piece of firmware in isolation — where its
source comes from, which container image builds it, the build command, and
which output files are its declared "artifacts". A component never
references another component; this is what keeps `tf-a.yaml` reusable
whether or not the target it's composed into also uses OP-TEE.

**Targets wire the graph.** A target (`manifests/targets/qemu-arm64-secureboot.yaml`)
lists an ordered `stack` of components plus per-component `vars`. A
stack entry's vars can reference a *sibling* component's artifact with
`${<component-name>.<artifact-key>}` — e.g. TF-A's `bl33` var is set to
`${barebox.barebox-dt-2nd}`. emblab topologically sorts the stack so
dependencies build first, then substitutes the token with the real host
path of the already-built artifact before rendering the build command.

The same `${...}` token syntax resolves `vars.NAME` (this component's own
variables), `env.JOBS`/`env.WORKSPACE` (a small fixed set of emblab-injected
values), and bare `<component>.<artifact>` references — see
`emblab/templating.py` for the exact rules.

## CLI

```
emblab list [images|components|targets]     # what's defined
emblab show <image|component|target> <name> # print a loaded manifest
emblab fetch <component>                    # clone/update just one component's source
emblab build <target> [--force] [--only X]  # build a target's full stack
emblab run <target> [--rebuild]             # boot a target in QEMU (builds first if needed... run build yourself first)
emblab shell <image>                        # interactive shell in a provisioned build container, for debugging
emblab clean [<target>] [--images] [--all]  # remove artifacts/state
emblab doctor                               # check host prerequisites
```

## Seed targets

- `qemu-arm64-uefi-barebox` — barebox only, booted via plain UEFI. No
  secure boot, the simplest possible target — start here.
- `qemu-arm64-secureboot` — TF-A (BL1/BL2/BL31) + OP-TEE (BL32) + barebox
  (BL33), `-M virt,secure=on`. Exercises the full manifest schema:
  multi-component stack, cross-component artifact wiring, and a
  conditionally-populated flag group (TF-A's `BL32`/`BL32_EXTRA1`/
  `BL32_EXTRA2` must be entirely absent, not empty, when there's no secure
  payload).

Both were ported from a working hand-scripted PoC, so their build commands
and QEMU invocations are grounded in commands known to actually work — see
each manifest's `description:` for provenance. The one exception is
`manifests/components/barebox.yaml`, whose build command is marked
`UNVERIFIED` and needs confirming against a real clone (see `CONTEXT.md`).

## Adding a new component or target

1. New component: add `manifests/components/<name>.yaml` — `source`
   (`git`/`ref`/`path`), `image` (must exist under `manifests/images/`),
   `build` (`command` + `vars`), `artifacts` (name → path relative to the
   source tree, after building). Never reference another component here.
2. New target: add `manifests/targets/<name>.yaml` — an ordered `stack` of
   `{component, vars}`, wiring cross-component artifacts via
   `${component.artifact}` in the `vars` of whichever component needs them,
   plus a `qemu` block (`binary` + `args`, same token syntax available).
3. `emblab show target <name>` to sanity-check it loads; `emblab build
   <name>` to try it for real.
