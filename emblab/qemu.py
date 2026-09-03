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

from . import containers, graph, manifests, sources, state, templating
from .errors import BuildError

# Every target here runs QEMU inside a headless qemu-runner container (see
# module docstring / ADR-012) — none of them ever wants a real gtk/sdl
# window. Without an explicit display backend, QEMU probes for gtk then
# sdl (neither module is installed, see qemu-runner.yaml's provision:),
# then falls back to a VNC server on localhost:5900, which fails DNS
# resolution inside the container — confirmed for real. A target that
# already picked its own display handling (`-nographic`, e.g. the
# coreboot/riscv64 targets whose qemu-runner image has no display module
# at all either way, or an explicit `-display` of its own) is left alone;
# this is a driver-level default, not a per-manifest one, so a target's
# own args: never needs to repeat it.
_DISPLAY_OVERRIDE_FLAGS = {"-nographic", "-display"}


def resolve_args(target, workspace):
    env = templating.default_env(workspace, target.arch)
    entries_by_component = {entry.component: entry for entry in target.stack}
    artifacts_by_component = {}
    # Same topo order build.py builds in, and the same active-artifacts
    # filtering it applies before collecting (see build.py's
    # active_artifacts): a component's declared artifacts: dict is not what
    # actually landed on disk when one of its paths template-resolved to ""
    # (e.g. tf-a's fip/qemu_fw are never produced for a target that drops
    # "fip" from make_targets) — checking the raw, unfiltered dict here
    # would report a fully-built component as "not built yet".
    for component_name in graph.topo_order(target):
        entry = entries_by_component[component_name]
        component = manifests.load_component(component_name)
        # Same per-component ${files} token build.py exposes (see there) —
        # e.g. coreboot's own defconfig var embeds it, and resolve_vars below
        # would otherwise raise "no files directory available here".
        component_env = {**env, "FILES": str(sources.source_dir(workspace, component))}
        merged_vars = {**component.build.vars, **entry.vars}
        resolved_vars = templating.resolve_vars(merged_vars, env=component_env, artifacts=artifacts_by_component)
        active_artifacts = {
            key: rel_path
            for key, rel_path in component.artifacts.items()
            if templating.render_command(rel_path, resolved_vars=resolved_vars, env=component_env) != ""
        }
        if not state.artifacts_exist(workspace, target.name, component_name, active_artifacts):
            raise BuildError(
                f"component '{component_name}' has not been built for target "
                f"'{target.name}' yet — run `emblab build {target.name}` first"
            )
        artifacts_by_component[component_name] = state.artifact_paths(
            workspace, target.name, component_name, active_artifacts
        )

    args = [
        templating.resolve_value(arg, merged_vars={}, env=env, artifacts=artifacts_by_component)
        for arg in target.qemu.args
    ]
    if not _DISPLAY_OVERRIDE_FLAGS & set(args):
        args = ["-display", "none", *args]
    return args


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
