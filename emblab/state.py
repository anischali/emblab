"""Idempotency markers: hash-file based, no build-cache system.

Two independent layers:
- image provisioning marker: skip re-provisioning a udocker container when
  its image manifest (base_image + provision commands) hasn't changed.
- component build marker: skip rebuilding a component for a given target
  when its resolved inputs (source ref, command, resolved vars) haven't
  changed AND its declared artifacts already exist on disk.
"""

import hashlib
import json
from pathlib import Path


def _hash(obj):
    blob = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def image_hash(image):
    return _hash({"base_image": image.base_image, "provision": image.provision})


def component_hash(component, resolved_vars):
    return _hash(
        {
            "source": {"git": component.source.git, "ref": component.source.ref},
            "command": component.build.command,
            "vars": resolved_vars,
        }
    )


def image_marker_path(workspace, image_name):
    return Path(workspace) / "state" / "images" / f"{image_name}.hash"


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
