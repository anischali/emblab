"""Fetch component source trees: shallow git clone/checkout at a pinned ref,
optionally initialize its git submodules (source.submodules: true — needed
by e.g. edk2's CryptoPkg, which vendors OpenSSL/mbedTLS as submodules), then
apply patches on top (Yocto-style: each component owns a
manifests/components/<name>/files/ directory holding its own patches,
applied in the order listed). The patches applied are whatever the caller
passes in — build.py passes component.build.patches (always applied)
concatenated with the target's stack-entry patches (target-optional extras,
e.g. edk2's FvBootDxe bundling — see ADR-010); cli.py's standalone `fetch`
command, with no target in play, passes just component.build.patches.

Phase 1 manifests pin `ref` to a branch name (e.g. "master") rather than an
exact SHA — `git clone --depth 1 --branch <ref>` only works for branches/tags,
not arbitrary commits. Pinning exact SHAs is a Phase 2 follow-up (see
CONTEXT.md); switching to a SHA later will need `git fetch <url> <sha> &&
git checkout FETCH_HEAD` instead of `--branch`, since most servers don't
advertise arbitrary commits for shallow-clone-by-branch.

A component with a floating `ref` (e.g. "master") moving upstream is by
design, not a bug (see the module-level `ensure_source` note above it) —
but it means a real re-clone can land in the middle of someone hand-editing
that source tree, silently discarding the edit. ADR-014 adds a Yocto
`devtool modify`/`reset`-style escape hatch for that: `mark_modified()`
drops a marker file in the source dir that makes `ensure_source` skip its
own freshness checks entirely (no `ls-remote`, no re-clone, no patch
reapply) for as long as it's present; `mark_finished()` removes it, handing
the tree back to normal ref/patches tracking on the *next* `ensure_source`
call — it does not itself re-clone. `emblab modify <component>` /
`emblab reset <component> [--reclone]` are the CLI entry points.
"""

import shutil
import subprocess
from pathlib import Path

from . import manifests, state
from .errors import EmblabError

PATCHES_MARKER_NAME = ".emblab-patches-hash"
MANUAL_EDIT_MARKER_NAME = ".emblab-manual-edit"


def source_dir(workspace, component):
    return Path(workspace) / "src" / component.source.path


def _current_head(path):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _resolve_remote_ref(url, ref):
    result = subprocess.run(
        ["git", "ls-remote", url, ref], capture_output=True, text=True, check=True
    )
    lines = result.stdout.strip().splitlines()
    return lines[0].split()[0] if lines else None


SUBMODULE_INIT_ATTEMPTS = 3


def _reclone(dest, component):
    shutil.rmtree(dest)
    subprocess.run(
        [
            "git", "clone", "--depth", "1",
            "--branch", component.source.ref,
            component.source.git, str(dest),
        ],
        check=True,
    )


def _run_submodule_update(cmd, dest, component, *, log):
    """`git submodule update --init --recursive --depth 1` with nested
    submodules-of-submodules (e.g. coreboot's arm-trusted-firmware -> its
    own mbed-tls -> mbed-tls's own "framework") is real, reproducibly
    flaky on this project — confirmed repeatedly against coreboot, a
    different nested submodule failing each time ("No such file or
    directory" for a FETCH_HEAD/shallow.lock path git should have just
    created under .git/modules/.../modules/...), never a
    network-reachability error. A failed attempt also leaves
    .git/modules/<submodule> corrupted enough that git itself cascades
    ("not a git repository", then "pathspec did not match" on the next
    attempt against the SAME tree) — confirmed for real: a bare retry of
    the identical command is not enough. Each retry (not the first
    attempt) re-clones the whole component from scratch first, onto a
    known-pristine tree, same as ensure_source's own ref-moved/
    patches-changed re-clone path."""
    last_error = None
    for attempt in range(1, SUBMODULE_INIT_ATTEMPTS + 1):
        if attempt > 1:
            log(f"[{component.name}] re-cloning before retry {attempt}/{SUBMODULE_INIT_ATTEMPTS}")
            _reclone(dest, component)
        try:
            subprocess.run(cmd, cwd=dest, check=True)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt < SUBMODULE_INIT_ATTEMPTS:
                log(
                    f"[{component.name}] git submodule update failed "
                    f"(attempt {attempt}/{SUBMODULE_INIT_ATTEMPTS}), retrying"
                )
    raise last_error


def _init_submodules(dest, component, *, log=print):
    submodules = component.source.submodules
    if not submodules:
        return
    base = ["git", "submodule", "update", "--init", "--recursive", "--depth", "1"]
    if submodules is True:
        log(f"[{component.name}] initializing git submodules")
        _run_submodule_update(base, dest, component, log=log)
    else:
        paths = list(submodules)
        log(f"[{component.name}] initializing git submodules ({', '.join(paths)})")
        _run_submodule_update([*base, "--", *paths], dest, component, log=log)


def _apply_patches(dest, component, patches, *, log=print):
    for filename in patches:
        patch_path = manifests.component_file_path(component.name, filename)
        log(f"[{component.name}] applying patch {filename}")
        subprocess.run(["git", "apply", str(patch_path)], cwd=dest, check=True)


def ensure_source(workspace, component, patches, *, log=print, force=False):
    """Clone `component`'s source if missing, re-fetch if the pinned ref has
    moved upstream, or re-fetch if `patches` changed — a patch is only ever
    applied once, right after a fresh clone, onto a known-pristine tree
    (never reapplied onto an already-patched, possibly-mid-build checkout).
    Returns the local source directory path.

    If the source dir carries a manual-edit marker (see `mark_modified`),
    all of the above is skipped unconditionally — no `ls-remote`, no
    re-clone, no patch reapply — and the tree is returned exactly as it
    sits on disk. This is checked before `force`, so `force=True` cannot
    steamroll a component someone is mid-edit on; `cmd_reset`'s `--reclone`
    only works because it removes the marker itself before calling in here.

    `force=True` re-clones unconditionally even if neither the ref nor
    `patches` changed — used by `emblab reset --reclone` to restore a
    component to a pristine, driver-tracked checkout on demand.

    `patches` is the full, ordered list to apply — the caller's
    responsibility to assemble (see module docstring); this function does
    not read component.build.patches itself.

    A sourceless component (component.source.git is None — a purely local
    packaging/assembly step like fit-image, with no upstream repo) just
    gets an empty workdir; there is nothing to clone or patch.
    """
    dest = source_dir(workspace, component)

    if component.source.git is None:
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    current_patches_hash = state.patches_hash(component.name, patches)
    patches_marker = dest / PATCHES_MARKER_NAME
    manual_marker = dest / MANUAL_EDIT_MARKER_NAME

    if dest.exists() and (dest / ".git").exists():
        if manual_marker.exists():
            log(
                f"[{component.name}] source under manual edit at {dest}, "
                f"skipping fetch (run 'emblab reset {component.name}' when done)"
            )
            return dest

        head = _current_head(dest)
        remote_sha = _resolve_remote_ref(component.source.git, component.source.ref)
        ref_moved = remote_sha is not None and head != remote_sha
        patches_changed = not state.marker_matches(patches_marker, current_patches_hash)
        if not force and not ref_moved and not patches_changed:
            log(f"[{component.name}] source up to date at {dest}")
            return dest
        if force:
            log(f"[{component.name}] re-clone forced")
        elif ref_moved:
            log(f"[{component.name}] ref '{component.source.ref}' moved upstream, re-cloning")
        else:
            log(f"[{component.name}] patches changed, re-cloning to reapply cleanly")
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git", "clone", "--depth", "1",
            "--branch", component.source.ref,
            component.source.git, str(dest),
        ],
        check=True,
    )
    log(f"[{component.name}] cloned {component.source.git}@{component.source.ref} -> {dest}")

    _init_submodules(dest, component, log=log)
    _apply_patches(dest, component, patches, log=log)
    state.write_marker(patches_marker, current_patches_hash)

    return dest


def mark_modified(workspace, component, *, log=print):
    """Freeze `component`'s source tree against `ensure_source` — Yocto
    `devtool modify`-style. The tree must already be cloned (there's
    nothing to mark otherwise); drops MANUAL_EDIT_MARKER_NAME into it, which
    `ensure_source` checks first and unconditionally short-circuits on, so
    hand edits under `workspace/src/<path>` survive builds, upstream ref
    moves, and even `emblab reset --reclone` on some *other* component,
    until `mark_finished` is called for this one."""
    dest = source_dir(workspace, component)
    if not (dest.exists() and (dest / ".git").exists()):
        raise EmblabError(
            f"'{component.name}' has no cloned source at {dest} yet — "
            f"run 'emblab fetch {component.name}' first"
        )
    (dest / MANUAL_EDIT_MARKER_NAME).touch()
    log(
        f"[{component.name}] marked under manual edit at {dest} — "
        f"emblab will not fetch or patch this source until 'emblab reset {component.name}'"
    )


def mark_finished(workspace, component, *, log=print):
    """Yocto `devtool reset`-style: remove `mark_modified`'s marker, handing
    `component`'s source back to normal ref/patches tracking. Doesn't itself
    re-clone — the tree is left exactly as the manual edit left it, and the
    next `ensure_source` call (e.g. the component's next build) re-clones
    only if the pinned ref moved or patches changed while it was marked,
    same as any other component. Pass `force=True` to the caller's own
    follow-up `ensure_source` call (see `cmd_reset --reclone`) to restore a
    pristine checkout immediately instead of waiting for that."""
    dest = source_dir(workspace, component)
    marker = dest / MANUAL_EDIT_MARKER_NAME
    if marker.exists():
        marker.unlink()
        log(f"[{component.name}] manual edit finished at {dest} — normal fetch tracking resumes")
    else:
        log(f"[{component.name}] source at {dest} was not marked for manual edit, nothing to do")
