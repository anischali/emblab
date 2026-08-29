"""Orchestrates `emblab build <target>`:

resolve target -> topo-sort its stack -> for each component in order:
ensure the *stack entry's* declared image is provisioned (a component has
no image of its own — see ADR-009), ensure its source is fetched, resolve
its vars (which may reference already-built sibling artifacts), run its
optional build.setup step if present (tracked/forced independently of the
build step — see ADR-011), skip the build step if unchanged, else install
the stack entry's builddeps, render its build command and run it
in-container, then collect its declared artifacts onto the host.
"""

import shutil
from pathlib import Path

from . import containers, graph, manifests, sources, state, templating
from .errors import BuildError


def build(target_name, workspace, *, force=False, setup_force=False, only=None, log=print):
    target = manifests.load_target(target_name)
    order = graph.topo_order(target)

    if only is not None:
        if only not in order:
            raise BuildError(f"component '{only}' is not part of target '{target_name}'")
        order = order[: order.index(only) + 1]

    entries_by_component = {entry.component: entry for entry in target.stack}
    env = templating.default_env(workspace, target.arch)
    artifacts_by_component = {}

    artifacts_root = Path(workspace) / "artifacts" / target.name
    artifacts_root.mkdir(parents=True, exist_ok=True)

    built = []
    for component_name in order:
        component = manifests.load_component(component_name)
        entry = entries_by_component[component_name]
        image = manifests.load_image(entry.image)

        # entry.patches are target-specific extras on top of the component's
        # own always-applied build.patches — e.g. edk2's FvBootDxe bundling
        # patch, only for a target that asks for it (see ADR-010).
        merged_patches = list(component.build.patches) + list(entry.patches)

        containers.ensure_image(image, workspace, log=log)
        src_dir = sources.ensure_source(workspace, component, merged_patches, log=log)

        merged_vars = {**component.build.vars, **entry.vars}
        resolved_vars = templating.resolve_vars(merged_vars, env=env, artifacts=artifacts_by_component)

        if component.build.setup:
            setup_marker = state.setup_marker_path(workspace, target.name, component_name)
            setup_current_hash = state.setup_hash(component, resolved_vars)
            if not setup_force and state.marker_matches(setup_marker, setup_current_hash):
                log(f"[{component_name}] setup unchanged, skipping")
            else:
                rendered_setup = templating.render_command(
                    component.build.setup, resolved_vars=resolved_vars, env=env
                )
                containers.run(
                    image,
                    workspace,
                    command=["sh", "-c", rendered_setup],
                    workdir=f"{env['WORKSPACE']}/src/{component.source.path}",
                    bind_mounts=[(env["WORKSPACE"], env["WORKSPACE"])],
                    log=log,
                )
                state.write_marker(setup_marker, setup_current_hash)
                log(f"[{component_name}] setup complete")

        marker_path = state.component_marker_path(workspace, target.name, component_name)
        current_hash = state.component_hash(component, resolved_vars, entry.builddeps, merged_patches)
        have_artifacts = state.artifacts_exist(workspace, target.name, component_name, component.artifacts)

        if not force and have_artifacts and state.marker_matches(marker_path, current_hash):
            log(f"[{component_name}] unchanged, skipping build")
        else:
            containers.ensure_builddeps(image, component_name, entry.builddeps, workspace, log=log)

            for filename in component.build.files:
                file_src = manifests.component_file_path(component_name, filename)
                shutil.copy2(file_src, src_dir / filename)

            rendered_cmd = templating.render_command(
                component.build.command, resolved_vars=resolved_vars, env=env
            )
            containers.run(
                image,
                workspace,
                command=["sh", "-c", rendered_cmd],
                workdir=f"{env['WORKSPACE']}/src/{component.source.path}",
                bind_mounts=[(env["WORKSPACE"], env["WORKSPACE"])],
                log=log,
            )

            dest_dir = artifacts_root / component_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            for key, rel_path in component.artifacts.items():
                resolved_rel_path = templating.render_command(rel_path, resolved_vars=resolved_vars, env=env)
                src = src_dir / resolved_rel_path
                dst = dest_dir / key
                if not src.exists():
                    raise BuildError(
                        f"[{component_name}] declared artifact '{key}' not found at "
                        f"{src} after build — check this component's artifacts: paths"
                    )
                if dst.is_dir():
                    shutil.rmtree(dst)
                elif dst.exists():
                    dst.unlink()
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

            state.write_marker(marker_path, current_hash)
            log(f"[{component_name}] built, artifacts collected")

        artifacts_by_component[component_name] = state.artifact_paths(
            workspace, target.name, component_name, component.artifacts
        )
        built.append(component_name)

    log(f"target '{target.name}' build complete: {', '.join(built)}")
    return artifacts_by_component
