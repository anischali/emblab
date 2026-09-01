"""Load and validate the YAML manifests under manifests/{images,components,targets}/.

Components are pure: source + build command + declared artifacts, and never
reference another component — nor do they know which image/toolchain
container they build under or what extra packages that needs (see ADR-009).
Targets wire the graph: an ordered stack of {component, vars, image,
builddeps} entries, where a stack entry's vars may reference a sibling
component's artifact via ``${<component>.<key>}``. This module enforces
that split at load time so a broken manifest fails fast with a clear
message, rather than surfacing as a confusing build-time error.
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
    git: str  # None for a sourceless (purely local packaging) component
    ref: str  # None for a sourceless component
    path: str  # always set — the workdir segment under workspace/src/
    submodules: object = False  # False, True (all, recursive), or a list of specific submodule paths


@dataclasses.dataclass
class Build:
    command: str
    setup: str  # optional one-time setup step, run/skipped/forced independently of command (see ADR-011); "" = none
    vars: dict
    files: list  # filenames, each backed by manifests/components/<component>/files/<filename>
    patches: list  # filenames (same files/ dir), git-applied in order onto a fresh clone
    # optional defconfig/extra_conf(_file)-only step, run unconditionally
    # (not marker-tracked) by `emblab shell --component` before dropping
    # into the shell, so the source tree's .config matches what a real
    # build would produce; "" = none. Never run by build() itself — that
    # config setup is already inlined at the front of `command`.
    config_command: str = ""


@dataclasses.dataclass
class Component:
    name: str
    description: str
    source: Source
    build: Build
    artifacts: dict
    # No image or builddeps here — components are agnostic of which image/
    # toolchain container they build under and what extra packages that
    # needs; a target's stack entry owns both (see ADR-009).


@dataclasses.dataclass
class StackEntry:
    component: str
    vars: dict
    image: str  # required — which image container this component builds under, for this target
    builddeps: list  # apt package names installed into that (image, component) container, for this target
    patches: list  # extra filenames (component's own files/ dir), applied after build.patches, for this target only


@dataclasses.dataclass
class Qemu:
    binary: str
    args: list
    image: str  # which image container to exec the qemu binary in (see ADR-012)


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


def _parse_submodules(value, path):
    # False/True: unchanged (no submodules / all of them, recursive). A list
    # is a set of specific submodule paths to init instead of all of them —
    # for a component whose repo carries submodules unrelated to what emblab
    # actually builds (e.g. coreboot's many vendor-specific 3rdparty/ trees).
    if isinstance(value, bool):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ManifestError(
        f"{_display(path)}: 'source.submodules' must be true, false, or a list of submodule paths"
    )


def _check_var_type(value, *, where):
    """A var's value must be a plain string, a list of plain strings (e.g.
    `extra_conf`'s individual Kconfig lines, joined with newlines at resolve
    time), or a plain bool (normalized to the same empty-string/non-empty
    convention every conditionally-populated var already uses — see
    templating.resolve_value) — anything else can't be rendered into a
    build.command."""
    if isinstance(value, bool):
        return
    if isinstance(value, str):
        return
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return
    raise ManifestError(
        f"{where}: var value must be a string, a list of strings, or a "
        f"bool, got {type(value).__name__}"
    )


def _check_no_bare_component_tokens(value, *, where):
    """Raise if `value` contains a ${X.Y} token whose X isn't 'vars' or 'env'
    — i.e. a bare component-artifact reference, which is only legal inside a
    *target's* stack vars, never inside a component's own build.vars
    defaults (components must stay reusable/self-contained). A list value
    (e.g. a default `extra_conf: []`) is checked item by item.
    """
    if isinstance(value, list):
        for item in value:
            _check_no_bare_component_tokens(item, where=where)
        return
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


def component_dir(name):
    return MANIFESTS_DIR / "components" / name


def component_path(name):
    return component_dir(name) / f"{name}.yaml"


def files_dir(name):
    return component_dir(name) / "files"


def component_file_path(component_name, filename):
    return files_dir(component_name) / filename


def target_path(name):
    return MANIFESTS_DIR / "targets" / f"{name}.yaml"


def list_names(kind):
    directory = MANIFESTS_DIR / kind
    if not directory.exists():
        return []
    if kind == "components":
        # Yocto-style: manifests/components/<name>/<name>.yaml, alongside a
        # files/ dir for that component's own patches and static files.
        return sorted(p.parent.name for p in directory.glob("*/*.yaml") if p.stem == p.parent.name)
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

    # `source:` is optional — absent means a sourceless component (a purely
    # local packaging/assembly step, e.g. fit-image, with no upstream repo).
    # `path` is always resolved (defaults to the component name either way)
    # so component.source.path keeps working unchanged everywhere else.
    source_data = data.get("source")
    if source_data is None:
        source = Source(git=None, ref=None, path=data.get("path", name))
    else:
        source = Source(
            git=_require(source_data, "git", path),
            ref=_require(source_data, "ref", path),
            path=source_data.get("path", name),
            submodules=_parse_submodules(source_data.get("submodules", False), path),
        )

    build_data = _require(data, "build", path)
    build_vars = dict(build_data.get("vars", {}))
    for var_name, var_value in build_vars.items():
        _check_var_type(var_value, where=f"{_display(path)}: build.vars.{var_name}")
        _check_no_bare_component_tokens(
            var_value, where=f"{_display(path)}: build.vars.{var_name}"
        )

    build_files = list(build_data.get("files", []))
    for filename in build_files:
        file_path = component_file_path(name, filename)
        if not file_path.exists():
            raise ManifestError(
                f"{_display(path)}: build.files entry '{filename}' has no "
                f"file at manifests/components/{name}/files/{filename}"
            )

    build_patches = list(build_data.get("patches", []))
    for filename in build_patches:
        patch_path = component_file_path(name, filename)
        if not patch_path.exists():
            raise ManifestError(
                f"{_display(path)}: build.patches entry '{filename}' has no "
                f"file at manifests/components/{name}/files/{filename}"
            )
    if build_patches and source_data is None:
        raise ManifestError(
            f"{_display(path)}: build.patches is set but this component has "
            "no source: — patches apply to a cloned source tree, which a "
            "sourceless (purely local packaging) component doesn't have"
        )

    build = Build(
        command=_require(build_data, "command", path),
        setup=build_data.get("setup", ""),
        config_command=build_data.get("config_command", ""),
        vars=build_vars,
        files=build_files,
        patches=build_patches,
    )

    if "image" in data:
        raise ManifestError(
            f"{_display(path)}: component manifests don't declare 'image' — "
            "components are agnostic of which image/toolchain container "
            "they build under; a target's stack entry sets it (see ADR-009)"
        )
    if "builddeps" in build_data:
        raise ManifestError(
            f"{_display(path)}: build.builddeps isn't a component-level "
            "field — a target's stack entry sets builddeps (see ADR-009), "
            "since what a component needs installed can depend on which "
            "image the target chose"
        )

    return Component(
        name=name,
        description=data.get("description", ""),
        source=source,
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
                f"{component_name}/{component_name}.yaml)"
            )

        image_name = _require(raw_entry, "image", path)
        if not image_path(image_name).exists():
            raise ManifestError(
                f"{_display(path)}: stack[{i}] ('{component_name}') sets "
                f"image to '{image_name}', which has no manifest at "
                f"manifests/images/{image_name}.yaml"
            )

        entry_patches = list(raw_entry.get("patches", []))
        for filename in entry_patches:
            patch_path = component_file_path(component_name, filename)
            if not patch_path.exists():
                raise ManifestError(
                    f"{_display(path)}: stack[{i}] ('{component_name}') "
                    f"patches entry '{filename}' has no file at "
                    f"manifests/components/{component_name}/files/{filename}"
                )

        stack_vars = dict(raw_entry.get("vars") or {})
        for var_name, var_value in stack_vars.items():
            _check_var_type(
                var_value,
                where=f"{_display(path)}: stack[{i}] ('{component_name}') vars.{var_name}",
            )

        stack.append(
            StackEntry(
                component=component_name,
                vars=stack_vars,
                image=image_name,
                builddeps=list(raw_entry.get("builddeps", [])),
                patches=entry_patches,
            )
        )

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
            items = var_value if isinstance(var_value, list) else [var_value]
            for item in items:
                for token in TOKEN_RE.findall(item if isinstance(item, str) else ""):
                    head = token.split(".", 1)[0]
                    if head in RESERVED_PREFIXES or head in refs:
                        continue
                    raise ManifestError(
                        f"{_display(path)}: stack entry '{entry.component}' "
                        f"vars.{var_name} references '{head}', which is not a "
                        "component in this target's stack"
                    )

    qemu_data = _require(data, "qemu", path)
    qemu_image_name = _require(qemu_data, "image", path)
    if not image_path(qemu_image_name).exists():
        raise ManifestError(
            f"{_display(path)}: qemu.image is '{qemu_image_name}', which has "
            f"no manifest at manifests/images/{qemu_image_name}.yaml"
        )
    qemu = Qemu(
        binary=_require(qemu_data, "binary", path),
        args=list(_require(qemu_data, "args", path)),
        image=qemu_image_name,
    )

    return Target(
        name=name,
        description=data.get("description", ""),
        arch=data.get("arch", ""),
        stack=stack,
        qemu=qemu,
    )
