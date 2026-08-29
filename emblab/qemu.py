"""Resolve a target's qemu invocation and exec it natively on the host.

Never containerized (ADR-003): QEMU needs KVM acceleration and direct
serial/display access, and udocker's namespace-based execution doesn't
reliably expose /dev/kvm. Uses the same token resolver as build.py so
`${component.artifact}` means exactly the same thing in a qemu arg as it
does in a build command.
"""

import subprocess

from . import manifests, state, templating
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
    cmd = [target.qemu.binary, *args]
    log("exec: " + " ".join(cmd))
    return subprocess.run(cmd)
