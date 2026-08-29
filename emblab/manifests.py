"""Load and validate the YAML manifests under manifests/{images,components,targets}/.

Components are pure: source + build command + declared artifacts, and never
reference another component. Targets wire the graph: an ordered stack of
{component, vars} entries, where a stack entry's vars may reference a
sibling component's artifact via ``${<component>.<key>}``. This module
enforces that split at load time so a broken manifest fails fast with a
clear message, rather than surfacing as a confusing build-time error.
"""

import dataclasses
from pathlib import Path

import yaml

from .errors import ManifestError
from .templating import TOKEN_RE, RESERVED_PREFIXES, component_refs

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFESTS_DIR = REPO_ROOT / "manifests"


@dataclasses.dataclass
class Image:
    name: str
    description: str
    base_image: str
    provision: list
    env: dict


@dataclasses.dataclass
class Source:
    git: str
    ref: str
    path: str


@dataclasses.dataclass
class Build:
    command: str
    vars: dict


@dataclasses.dataclass
class Component:
    name: str
    description: str
    source: Source
    image: str
    build: Build
    artifacts: dict


@dataclasses.dataclass
class StackEntry:
    component: str
    vars: dict


@dataclasses.dataclass
class Qemu:
    binary: str
    args: list


@dataclasses.dataclass
class Target:
    name: str
    description: str
    arch: str
    stack: list  # list[StackEntry]
    qemu: Qemu


def _display(path):
    """Path for error messages: relative to the repo root when possible
    (readable), falling back to the raw path (e.g. when MANIFESTS_DIR has
    been pointed outside the repo, as tests do)."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _read_yaml(path):
    if not path.exists():
        raise ManifestError(f"manifest not found: {_display(path)}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ManifestError(f"{_display(path)}: expected a YAML mapping at the top level")
    return data


def _require(data, key, path):
    if key not in data:
        raise ManifestError(f"{_display(path)}: missing required field '{key}'")
    return data[key]


def _check_no_bare_component_tokens(value, *, where):
    """Raise if `value` contains a ${X.Y} token whose X isn't 'vars' or 'env'
    — i.e. a bare component-artifact reference, which is only legal inside a
    *target's* stack vars, never inside a component's own build.vars
    defaults (components must stay reusable/self-contained).
    """
    if not isinstance(value, str):
        return
    for token in TOKEN_RE.findall(value):
        head = token.split(".", 1)[0]
        if head not in RESERVED_PREFIXES:
            raise ManifestError(
                f"{where}: token '${{{token}}}' looks like a cross-component "
                "reference, which is not allowed in a component's own "
                "build.vars — components must stay reusable across targets; "
                "wire this in the *target* manifest's stack vars instead"
            )


def image_path(name):
    return MANIFESTS_DIR / "images" / f"{name}.yaml"


def component_path(name):
    return MANIFESTS_DIR / "components" / f"{name}.yaml"


def target_path(name):
    return MANIFESTS_DIR / "targets" / f"{name}.yaml"


def list_names(kind):
    directory = MANIFESTS_DIR / kind
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))


def load_image(name):
    path = image_path(name)
    data = _read_yaml(path)
    return Image(
        name=name,
        description=data.get("description", ""),
        base_image=_require(data, "base_image", path),
        provision=list(_require(data, "provision", path)),
        env=dict(data.get("env", {})),
    )


def load_component(name):
    path = component_path(name)
    data = _read_yaml(path)

    source_data = _require(data, "source", path)
    source = Source(
        git=_require(source_data, "git", path),
        ref=_require(source_data, "ref", path),
        path=source_data.get("path", name),
    )

    build_data = _require(data, "build", path)
    build_vars = dict(build_data.get("vars", {}))
    for var_name, var_value in build_vars.items():
        _check_no_bare_component_tokens(
            var_value, where=f"{_display(path)}: build.vars.{var_name}"
        )
    build = Build(command=_require(build_data, "command", path), vars=build_vars)

    image_name = _require(data, "image", path)
    if not image_path(image_name).exists():
        raise ManifestError(
            f"{_display(path)}: image '{image_name}' has no "
            f"manifest at manifests/images/{image_name}.yaml"
        )

    return Component(
        name=name,
        description=data.get("description", ""),
        source=source,
        image=image_name,
        build=build,
        artifacts=dict(data.get("artifacts", {})),
    )


def load_target(name):
    path = target_path(name)
    data = _read_yaml(path)

    raw_stack = _require(data, "stack", path)
    if not raw_stack:
        raise ManifestError(f"{_display(path)}: stack must have at least one entry")

    stack = []
    seen_components = set()
    for i, raw_entry in enumerate(raw_stack):
        component_name = _require(raw_entry, "component", path)
        if component_name in seen_components:
            raise ManifestError(
                f"{_display(path)}: component '{component_name}' "
                "appears more than once in stack — each component may only "
                "appear once per target"
            )
        seen_components.add(component_name)
        if not component_path(component_name).exists():
            raise ManifestError(
                f"{_display(path)}: stack[{i}] references unknown "
                f"component '{component_name}' (no manifests/components/"
                f"{component_name}.yaml)"
            )
        stack.append(StackEntry(component=component_name, vars=dict(raw_entry.get("vars") or {})))

    # Every ${X.Y} reference in a stack entry's vars must point at another
    # component that is actually part of this same target's stack, and must
    # not be a self-reference (which would be a trivial cycle / typo).
    for entry in stack:
        for var_name, var_value in entry.vars.items():
            refs = component_refs(var_value, seen_components)
            if entry.component in refs:
                raise ManifestError(
                    f"{_display(path)}: stack entry '{entry.component}' "
                    f"vars.{var_name} references its own component — "
                    "a component cannot depend on itself"
                )
            for token in TOKEN_RE.findall(var_value if isinstance(var_value, str) else ""):
                head = token.split(".", 1)[0]
                if head in RESERVED_PREFIXES or head in refs:
                    continue
                raise ManifestError(
                    f"{_display(path)}: stack entry '{entry.component}' "
                    f"vars.{var_name} references '{head}', which is not a "
                    "component in this target's stack"
                )

    qemu_data = _require(data, "qemu", path)
    qemu = Qemu(
        binary=_require(qemu_data, "binary", path),
        args=list(_require(qemu_data, "args", path)),
    )

    return Target(
        name=name,
        description=data.get("description", ""),
        arch=data.get("arch", ""),
        stack=stack,
        qemu=qemu,
    )
