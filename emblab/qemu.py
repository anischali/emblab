"""Resolve a target's qemu invocation and run it inside the `qemu.image`
udocker container declared by the target manifest.

Containerized as of ADR-012, which supersedes ADR-003: on this project's
targets (arm64/riscv64 guests, always run from other host arches so far)
KVM acceleration was never on the table either way, so ADR-003's namespace/
`/dev/kvm`-passthrough rationale doesn't actually apply yet — only its
serial/console-access half did, and udocker's `run` already inherits the
caller's stdio (proven by `emblab shell`'s interactive use), which is all
`-nographic` needs. Uses the same token resolver as build.py so
`${component.artifact}` means exactly the same thing in a qemu arg as it
does in a build command; artifact paths are bind-mounted into the container
at their own host path, so args need no rewriting between host and
container namespaces.
"""

from pathlib import Path

from . import containers, manifests, state, templating
from .errors import BuildError


def resolve_args(target, workspace):
    env = templating.default_env(workspace, target.arch)
    artifacts_by_component = {}
    for entry in target.stack:
        component = manifests.load_component(entry.component)
        if not state.artifacts_exist(workspace, target.name, entry.component, component.artifacts):
            raise BuildError(
                f"component '{entry.component}' has not been built for target "
                f"'{target.name}' yet — run `emblab build {target.name}` first"
            )
        artifacts_by_component[entry.component] = state.artifact_paths(
            workspace, target.name, entry.component, component.artifacts
        )

    return [
        templating.resolve_value(arg, merged_vars={}, env=env, artifacts=artifacts_by_component)
        for arg in target.qemu.args
    ]


def run(target_name, workspace, *, log=print):
    target = manifests.load_target(target_name)
    args = resolve_args(target, workspace)
    image = manifests.load_image(target.qemu.image)
    containers.ensure_image(image, workspace, log=log)

    # Bind-mount this target's whole artifacts tree at the same absolute
    # host path inside the container — every resolved ${component.key} token
    # above is already an absolute host path under here, so the qemu args
    # need no rewriting to be valid container-side paths too.
    artifacts_dir = Path(workspace) / "artifacts" / target.name
    cmd = [target.qemu.binary, *args]
    log("run (containerized): " + " ".join(cmd))
    return containers.run(
        image,
        workspace,
        command=cmd,
        workdir="/",
        bind_mounts=[(artifacts_dir, artifacts_dir)],
        check=False,
        log=log,
    )
