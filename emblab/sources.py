"""Fetch component source trees: shallow git clone/checkout at a pinned ref.

Phase 1 manifests pin `ref` to a branch name (e.g. "master") rather than an
exact SHA — `git clone --depth 1 --branch <ref>` only works for branches/tags,
not arbitrary commits. Pinning exact SHAs is a Phase 2 follow-up (see
CONTEXT.md); switching to a SHA later will need `git fetch <url> <sha> &&
git checkout FETCH_HEAD` instead of `--branch`, since most servers don't
advertise arbitrary commits for shallow-clone-by-branch.
"""

import shutil
import subprocess
from pathlib import Path


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


def ensure_source(workspace, component, *, log=print):
    """Clone `component`'s source if missing, or re-fetch if the pinned ref
    has moved upstream. Returns the local source directory path."""
    dest = source_dir(workspace, component)

    if dest.exists() and (dest / ".git").exists():
        head = _current_head(dest)
        remote_sha = _resolve_remote_ref(component.source.git, component.source.ref)
        if remote_sha is None or head == remote_sha:
            log(f"[{component.name}] source up to date at {dest}")
            return dest
        log(f"[{component.name}] ref '{component.source.ref}' moved upstream, re-cloning")
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
    return dest
