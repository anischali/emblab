"""udocker wrapper: pull+create+run only (see ADR-004 — never rely on
udocker's Dockerfile-subset `build` command, whose reliability varies by
version). All state (pulled images, created containers) lives under
`workspace/udocker` via UDOCKER_DIR, so the whole lab is disposable with
`emblab clean --all` and never touches the user's global ~/.udocker.
"""

import os
import subprocess
from pathlib import Path

from . import state

REPO_ROOT = Path(__file__).resolve().parent.parent
# Shared helper scripts (fitkeys-ctl, tsa-stamp, ...) usable by name
# from any component's build.command and from `emblab shell` — bind-mounted
# onto /usr/local/bin (ahead of /usr/bin on Debian's default PATH, and
# already on every base image's PATH) rather than copied per-component, so
# adding a script here makes it available everywhere with no manifest
# changes and no per-component files: entry.
HELPERS_DIR = REPO_ROOT / "helpers"
HELPERS_MOUNT = "/usr/local/bin"


def _udocker_env(workspace):
    env = dict(os.environ)
    env["UDOCKER_DIR"] = str(Path(workspace) / "udocker")
    return env


def _udocker(args, workspace, **kwargs):
    return subprocess.run(["udocker", *args], env=_udocker_env(workspace), **kwargs)


def container_name(image):
    return f"emblab-{image.name}"


def _container_exists(image, workspace):
    result = _udocker(["inspect", container_name(image)], workspace, capture_output=True, text=True)
    return result.returncode == 0


def ensure_image(image, workspace, *, log=print):
    """Pull the base image and provision it once; re-provision (idempotent
    shell commands, e.g. apt-get install) only if the image manifest changed
    since the marker was written."""
    marker_path = state.image_marker_path(workspace, image.name)
    current_hash = state.image_hash(image)
    exists = _container_exists(image, workspace)

    if exists and state.marker_matches(marker_path, current_hash):
        log(f"[{image.name}] already provisioned, skipping")
        return

    if not exists:
        log(f"[{image.name}] pulling {image.base_image}")
        _udocker(["pull", image.base_image], workspace, check=True)
        log(f"[{image.name}] creating container {container_name(image)}")
        _udocker(["create", f"--name={container_name(image)}", image.base_image], workspace, check=True)

    for cmd in image.provision:
        log(f"[{image.name}] provisioning: {cmd}")
        run(image, workspace, command=["sh", "-c", cmd], workdir="/", log=log)

    state.write_marker(marker_path, current_hash)
    log(f"[{image.name}] provisioned")


def ensure_builddeps(image, component_name, builddeps, workspace, *, log=print):
    """Install a target's declared extra apt packages for this (image,
    component) pairing (see ADR-009 — builddeps is a stack-entry field, not
    a component one) into the image container, once per (image, component)
    pair — skipped on later builds unless the list changes. Kept separate
    from ensure_image's own provisioning marker because several components
    can share one image container while each needing a different extra
    package set; installs accumulate in the shared container rather than
    replacing each other."""
    if not builddeps:
        return

    marker_path = state.builddeps_marker_path(workspace, image.name, component_name)
    current_hash = state.builddeps_hash(builddeps)
    if state.marker_matches(marker_path, current_hash):
        log(f"[{image.name}] {component_name}: builddeps already installed, skipping")
        return

    deps = " ".join(builddeps)
    log(f"[{image.name}] {component_name}: installing builddeps: {deps}")
    run(
        image,
        workspace,
        command=["sh", "-c", f"apt-get update && apt-get install -y --no-install-recommends {deps}"],
        workdir="/",
        log=log,
    )
    state.write_marker(marker_path, current_hash)


def run(image, workspace, *, command, workdir, bind_mounts=(), extra_env=None, check=True, log=print):
    """Run `command` inside the provisioned container for `image`.

    Note: udocker's `--bindhome` is a bare boolean flag (no `=value` form —
    `--bindhome=false` is a syntax error); omitting it means "don't bind
    home", which is what we want. Volume mounts are `--volume=`, not `-v=`
    (udocker has no `-v` shorthand).

    `check=False` is for callers like qemu.py that need the raw
    CompletedProcess (e.g. to propagate QEMU's own exit code) rather than an
    exception on a non-zero return — the normal build path always wants
    `check=True` (the default) so a failed build command stops the pipeline.
    """
    args = ["run"]
    args.append(f"--volume={HELPERS_DIR}:{HELPERS_MOUNT}")
    for host_path, container_path in bind_mounts:
        args.append(f"--volume={host_path}:{container_path}")
    for key, value in {**image.env, **(extra_env or {})}.items():
        args.append(f"--env={key}={value}")
    args.append(f"--workdir={workdir}")
    args.append(container_name(image))
    args.extend(command)
    log(f"[{image.name}] run: {' '.join(command)}")
    return _udocker(args, workspace, check=check)


def shell(image, workspace):
    """Interactive shell inside the provisioned container, for debugging a
    build by hand. Same helpers/ bind mount as run() — fitkeys-ctl,
    tsa-stamp, etc. are on PATH here too."""
    args = ["run", f"--volume={HELPERS_DIR}:{HELPERS_MOUNT}", "--workdir=/", container_name(image), "sh"]
    subprocess.run(["udocker", *args], env=_udocker_env(workspace))
