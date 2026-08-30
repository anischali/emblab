# ADR-012: Containerize QEMU too — supersedes ADR-003

## Status
Accepted

## Context
ADR-003 kept `emblab run` execing the host's native `qemu-system-*` binary
directly, for two stated reasons: KVM acceleration passthrough into
udocker's namespace-based execution backends isn't guaranteed, and QEMU
wants direct access to serial console and display.

Revisiting both against what emblab's targets actually are today: every
target so far emulates arm64 or riscv64 guests, always from a different
host architecture (cross-arch emulation via QEMU's TCG). KVM acceleration
requires host/guest architecture to match — it was never available to these
targets whether QEMU ran on the host or in a container, so ADR-003's KVM
rationale doesn't apply in practice yet. The remaining rationale, serial
access, is what every proven target so far actually needs — `-nographic`
routes the guest's serial console over the process's own stdio, and
`containers.run()`/`containers.shell()` already inherit the caller's stdio
through udocker `run` with no special flags (proven by `emblab shell`'s
existing interactive use) — no display/VNC passthrough is required.

Meanwhile ADR-003 left `qemu-system-*` as a host prerequisite `emblab`
"cannot auto-install", which is exactly the kind of host-package-manager
dependency ADR-002 tries to avoid everywhere else — it's the one place the
"working lab in under 5 minutes, no root" story still depended on something
outside emblab's own control.

## Decision
Every target's `qemu:` block now declares an `image:` (like a stack entry's
own `image:` — see ADR-009), naming the udocker image container to exec
`qemu.binary` inside. A new shared `manifests/images/qemu-runner.yaml` image
is arch-agnostic (Debian's `qemu-system-arm` package covers both
`qemu-system-arm` and `qemu-system-aarch64`; `qemu-system-misc` covers
`qemu-system-riscv64`), so it's the same `image:` value for every target
regardless of arch — no per-arch qemu image needed, unlike the build-time
cross-toolchain images.

`emblab/qemu.py`'s `run()` resolves the target's qemu args exactly as
before (same token resolver, same `${component.artifact}` semantics), then
provisions the `qemu.image` container and execs `[qemu.binary, *args]`
inside it via `containers.run()`, bind-mounting the target's whole
`workspace/artifacts/<target>/` tree at the *same* absolute host path
inside the container — since every resolved artifact token is already an
absolute host path, this means the qemu args need no rewriting between host
and container namespaces. `containers.run()` gained a `check=False` option
so `qemu.py` can propagate QEMU's real exit code (via
`subprocess.CompletedProcess.returncode`) back through `emblab run` instead
of raising on whatever exit code an interactive QEMU session happens to end
with.

`emblab doctor` no longer checks for host `qemu-system-*` binaries — they're
not a host prerequisite anymore. `git` and `udocker` are the only two
prerequisite checks left.

## Consequences
`udocker` (plus `git` to clone sources) is now the only real host
dependency emblab has — closer to ADR-002's original "rootless, daemonless,
ready in under 5 minutes" goal, with no host package-manager step for QEMU
itself. `emblab run`'s interactive serial console now depends on udocker's
`run` correctly passing through the caller's stdio for however long a QEMU
session stays open — proven pattern (`emblab shell`), but not yet
proven for a long-running, interactive QEMU session specifically; the first
real target to re-verify this against is `qemu-riscv64-opensbi-barebox`,
since its boot-to-shell-prompt behavior over serial is already proven from
the ADR-003-era host-exec path (see CONTEXT.md), making it the cheapest
apples-to-apples comparison.

Honest limitation this reintroduces risk around: if a future target ever
needs a host-architecture guest (e.g. a `qemu-system-x86_64` target on an
x86_64 host) or genuinely wants KVM acceleration, containerizing QEMU loses
that possibility for good — udocker's execution backends still don't
reliably expose `/dev/kvm`. That tradeoff wasn't live for any target that
exists today, so it's accepted here, but a future arch/accel-sensitive
target should reopen this ADR rather than silently work around it.
