"""Idempotency markers: hash-file based, no build-cache system.

Three independent layers:
- image provisioning marker: skip re-provisioning a udocker container when
  its image manifest (base_image + provision commands) hasn't changed.
- component build marker: skip rebuilding a component for a given target
  when its resolved inputs (source ref, build command, resolved vars,
  upstream sibling artifact *content* — see upstream_artifacts_hash) haven't
  changed AND its declared artifacts already exist on disk.
- component setup marker (see ADR-011): tracks a component's optional
  build.setup step separately from its build step — force one without the
  other via `emblab build --setup-force` vs. `--force`.

Real, confirmed bug this module used to have: a component whose vars
reference a sibling's artifact only ever embeds that artifact's *path*
(e.g. coreboot's payload_conf: "${barebox.images}/barebox-arm64.fit") —
the path string is stable across rebuilds even when barebox's own defconfig
var changes and it rebuilds an entirely different file at that same path.
component_hash() used to hash only resolved_vars (the path text), so
coreboot's marker looked unchanged and a real `emblab build` silently kept
embedding a stale payload after an upstream-only var change. Fixed by
folding upstream_artifacts_hash() (real file/directory content, not paths)
into component_hash() too.
"""

import hashlib
import json
from pathlib import Path


def _hash(obj):
    blob = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _files_content_hash(component_name, filenames):
    from . import manifests  # local import: avoids a manifests<->state import cycle

    return {
        filename: _file_hash(manifests.component_file_path(component_name, filename))
        for filename in filenames
    }


def image_hash(image):
    return _hash({"base_image": image.base_image, "provision": image.provision})


def _path_content_hash(path):
    """Content hash of one collected artifact — a file, or (e.g. barebox's
    `images` artifact) a whole directory copied via copytree, walked and
    hashed file-by-file so a changed file inside it is still detected."""
    p = Path(path)
    if p.is_dir():
        return _hash([(str(f.relative_to(p)), _file_hash(f)) for f in sorted(p.rglob("*")) if f.is_file()])
    return _file_hash(p)


def upstream_artifacts_hash(artifacts_by_component):
    """Content hash of every artifact already collected from earlier
    components in this target's build (see build.py's `artifacts_by_component`)
    — folded into component_hash() so a component that only ever embeds an
    upstream sibling's artifact *path* (e.g. coreboot's payload_conf:
    "${barebox.images}/barebox-arm64.fit") still rebuilds when that
    upstream artifact's real content changes at the same path."""
    return _hash(
        {
            component_name: {key: _path_content_hash(path) for key, path in artifacts.items()}
            for component_name, artifacts in artifacts_by_component.items()
        }
    )


def patches_hash(component_name, patches):
    """Content hash of a component's declared build.patches, in order —
    shared by component_hash() (so an edited patch forces the build command
    to rerun) and sources.ensure_source() (so an edited patch forces a fresh
    clone + reapply, not a reapply on top of an already-patched tree)."""
    return _hash([(filename, _files_content_hash(component_name, [filename])[filename]) for filename in patches])


def component_hash(component, resolved_vars, builddeps, patches, upstream_artifacts):
    """`builddeps` comes from the target's stack entry, not the component —
    see ADR-009. `patches` is the full merged list (component.build.patches
    + the target's own stack-entry patches — see ADR-010); both are
    parameters here exactly like `resolved_vars` already is, never read off
    `component.build` directly, so a target-only change (different
    builddeps, or an extra target-specific patch) still invalidates the
    marker even though the component manifest itself didn't change.

    `upstream_artifacts` is build.py's `artifacts_by_component` so far (see
    upstream_artifacts_hash) — resolved_vars only ever carries an upstream
    sibling's artifact *path*, never its content, so without this a
    downstream component's marker can't see an upstream-only var change
    (e.g. barebox's defconfig) that rebuilds a different file at that same
    path. `{}` for the first component in a stack, same as build.py's own
    `artifacts_by_component` starts out."""
    return _hash(
        {
            "source": {"git": component.source.git, "ref": component.source.ref},
            "command": component.build.command,
            "vars": resolved_vars,
            "files": _files_content_hash(component.name, component.build.files),
            "builddeps": sorted(builddeps),
            "patches": patches_hash(component.name, patches),
            "upstream_artifacts": upstream_artifacts_hash(upstream_artifacts),
        }
    )


def setup_hash(component, resolved_vars):
    """Independent from component_hash() by design (see ADR-011) — a
    component's optional build.setup step (e.g. one-time signing-key
    generation) is tracked and force-rerun separately from its build step,
    via `emblab build --setup-force` vs. `--force`."""
    return _hash({"setup": component.build.setup, "vars": resolved_vars})


def setup_marker_path(workspace, target_name, component_name):
    return Path(workspace) / "state" / "components" / f"{target_name}__{component_name}.setup.hash"


def image_marker_path(workspace, image_name):
    return Path(workspace) / "state" / "images" / f"{image_name}.hash"


def builddeps_hash(builddeps):
    return _hash(sorted(builddeps))


def builddeps_marker_path(workspace, image_name, component_name):
    return Path(workspace) / "state" / "images" / f"{image_name}__{component_name}.builddeps.hash"


def component_marker_path(workspace, target_name, component_name):
    return Path(workspace) / "state" / "components" / f"{target_name}__{component_name}.hash"


def read_marker(path):
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip()


def write_marker(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def marker_matches(path, value):
    return read_marker(path) == value


def artifacts_exist(workspace, target_name, component_name, artifacts):
    base = Path(workspace) / "artifacts" / target_name / component_name
    return all((base / key).exists() for key in artifacts)


def artifact_paths(workspace, target_name, component_name, artifacts):
    base = Path(workspace) / "artifacts" / target_name / component_name
    return {key: str(base / key) for key in artifacts}
