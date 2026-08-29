# ADR-001: Python + YAML manifests + thin driver, over Nix/kas/west/repo

## Status
Accepted

## Context
emblab needs to describe many bootloader/firmware components (TF-A, OpenSBI,
OP-TEE, U-Boot, barebox, EDK2) across multiple architectures, and compose
them into named, buildable, runnable QEMU targets — declaratively, so adding
a new architecture or bootstack combination means adding data, not code.
Several existing tools solve *adjacent* problems: Nix expresses fully
hermetic, reproducible build environments; `kas` composes Yocto layers; West
manages Zephyr's multi-repo manifests; Google's `repo` tool syncs many git
repos against an XML manifest (as OP-TEE's own `qemu_v8.xml` does). None of
them solve the specific problem emblab has: composing independently-built
firmware components where one component's build inputs (e.g. TF-A's
`BL32`/`BL33`) are *another* component's build outputs.

## Decision
Use YAML manifests (`manifests/images/`, `manifests/components/`,
`manifests/targets/`) read by a thin Python driver (stdlib `argparse` for
the CLI, PyYAML for parsing — the only mandatory runtime dependency).
Components describe how to build one piece of firmware in isolation and
never reference each other; targets compose an ordered stack of components
and wire their artifacts together via `${component.artifact}` tokens
resolved by a small custom templating layer.

Rejected: Nix (steep learning curve for a tool meant to bootstrap in under 5
minutes on a fresh machine, and doesn't map naturally onto "run this
cross-compiler inside a container"); `kas` (Yocto-specific layer
composition, no fit for non-Yocto firmware builds); West (Zephyr-specific
manifest semantics, no generic build-orchestration layer); `repo` (XML,
solves multi-repo sync only — it's what feeds *into* a build, not a build
tool itself).

## Consequences
Minimal dependency footprint (`pip install pyyaml` is the entire external
install). Manifest authors get comments, anchors, and readable multiline
block scalars for documenting *why* a flag is set. The custom
variable-substitution mechanism is emblab-specific and not reusable outside
this project, but it is small (roughly 50 lines) and fully unit-tested.
