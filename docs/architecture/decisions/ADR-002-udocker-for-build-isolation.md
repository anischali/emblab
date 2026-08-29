# ADR-002: udocker for build isolation instead of Docker/Podman

## Status
Accepted

## Context
Cross-toolchain builds (OP-TEE, TF-A, EDK2, barebox) need hermetic,
reproducible build environments with specific package sets, without
requiring a Docker daemon or root access — a hard requirement given the
goal of a working lab in under 5 minutes on a freshly provisioned machine.
`udocker` is a pure-Python, rootless, daemonless tool that pulls and runs
standard container images using unprivileged execution backends (PRoot,
runc, etc.).

## Decision
Use udocker exclusively for build-time containerization: pulling base
images and running build commands inside them. Do not require a real
Docker or Podman daemon anywhere in the critical path. QEMU itself is
explicitly out of scope for containerization (see ADR-003).

## Consequences
Rootless and daemonless on Linux, matching the "ready in under 5 minutes,
no root" requirement — no privileged daemon install/setup step. Honest
caveat: udocker itself needs a Linux kernel underneath (its execution
backends rely on Linux namespace/chroot-style mechanisms). On macOS or
Windows, "cross-platform" for emblab means the manifests and CLI behave
identically everywhere, not that udocker runs natively there — those hosts
need a one-time Linux substrate first (WSL2 on Windows, Lima/Colima on
macOS), documented in README.md as a host prerequisite, not something
emblab manages or installs itself.
