# ADR-003: Build inside containers, run QEMU on the host

## Status
Accepted

## Context
Build toolchains benefit from container isolation (pinned package versions,
no host pollution). QEMU experimentation has the opposite needs: it wants
KVM acceleration where available, and direct access to serial console and
display, neither of which udocker's namespace-based execution backends
reliably expose (in particular `/dev/kvm` passthrough is not guaranteed).

## Decision
`emblab build` always runs component build commands inside udocker
containers. `emblab run` always execs the host's native `qemu-system-*`
binary directly, never inside a container. The two are strictly separated
by ADR-002/ADR-003: containers build artifacts onto the host filesystem;
QEMU then consumes those host-filesystem artifacts directly.

## Consequences
Avoids nested-virtualization / KVM-passthrough-into-udocker complexity
entirely. QEMU becomes a host prerequisite emblab cannot auto-install —
`emblab doctor` checks for `qemu-system-aarch64`/`-riscv64`/`-arm` and
reports clearly if any are missing, but installing them is left to the host
package manager (documented in README.md).
