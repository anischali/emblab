"""Token resolution for emblab manifests.

Three namespaces, resolved by splitting a ``${...}`` token on the first ``.``:

- ``vars.NAME``    -> looked up in a merged vars dict (component defaults,
                      overridden by a target stack entry's vars).
- ``env.NAME``     -> looked up in a small emblab-injected environment
                      (``env.JOBS``, ``env.WORKSPACE``).
- ``<component>.<artifact-key>`` (no ``vars.``/``env.`` prefix) -> the
                      absolute host path of another component's already-built
                      artifact. Only legal inside a *target's* stack vars.
"""

import os
import re

from .errors import TemplateError

TOKEN_RE = re.compile(r"\$\{([a-zA-Z0-9_.-]+)\}")

RESERVED_PREFIXES = ("vars", "env")


def component_refs(value, known_components):
    """Return the set of component names referenced by bare
    ``<component>.<key>`` tokens inside `value` (a string; non-strings yield
    an empty set). `known_components` restricts matches to real names so an
    unrelated dotted token isn't mistaken for a component reference.
    """
    refs = set()
    if not isinstance(value, str):
        return refs
    for token in TOKEN_RE.findall(value):
        head = token.split(".", 1)[0]
        if head in RESERVED_PREFIXES:
            continue
        if head in known_components:
            refs.add(head)
    return refs


def default_env(workspace_dir, arch=""):
    """The small, fixed set of ``env.*`` values available to every manifest.

    ``ARCH`` is the *target's* ``arch:`` field, resolved purely as a
    ``${env.ARCH}`` template token — not a real container env var. That
    matters: a real env var is visible to every process in a component's
    container whether or not that component's own command asked for it,
    which broke OP-TEE's build (its make rules read ARCH from the
    environment and default it to "arm" internally; force-setting "arm64"
    there was wrong even though OP-TEE's command never mentions ARCH at
    all). A template token only ever reaches the one command that
    literally writes ``${env.ARCH}`` — see ADR-006.
    """
    return {
        "JOBS": str(os.cpu_count() or 1),
        "WORKSPACE": str(workspace_dir),
        "ARCH": arch,
    }


def resolve_value(value, *, merged_vars, env, artifacts):
    """Substitute every ``${...}`` token in a single string value."""
    if not isinstance(value, str):
        return value

    def _sub(match):
        token = match.group(1)
        if token.startswith("vars."):
            name = token[len("vars."):]
            if name not in merged_vars:
                raise TemplateError(f"unknown token '${{{token}}}': no such var")
            return str(merged_vars[name])
        if token.startswith("env."):
            name = token[len("env."):]
            if name not in env:
                raise TemplateError(f"unknown token '${{{token}}}': no such env value")
            return str(env[name])

        component, _, key = token.partition(".")
        if not key:
            raise TemplateError(
                f"malformed token '${{{token}}}': expected <component>.<artifact-key>"
            )
        if component not in artifacts:
            raise TemplateError(
                f"token '${{{token}}}' references component '{component}', "
                "which is not in this target's stack or has not been built yet"
            )
        if key not in artifacts[component]:
            raise TemplateError(
                f"token '${{{token}}}' references unknown artifact '{key}' "
                f"of component '{component}'"
            )
        return artifacts[component][key]

    return TOKEN_RE.sub(_sub, value)


def resolve_vars(raw_vars, *, env, artifacts):
    """Resolve a full vars dict. Values may reference env.* and
    <component>.<key> tokens, but never vars.* (no self-reference between
    vars — keeps resolution a single deterministic pass; passing an empty
    vars context below is what enforces that: any vars.* token found raises).
    """
    resolved = {}
    for name, value in raw_vars.items():
        resolved[name] = resolve_value(value, merged_vars={}, env=env, artifacts=artifacts)
    return resolved


def render_command(command, *, resolved_vars, env):
    """Render a build.command template, or any other single component-owned
    string that should only ever see vars.*/env.* tokens — e.g. an
    artifacts: path built from ${vars.X}. Component-artifact tokens must
    already have been folded into resolved_vars by resolve_vars(); a bare
    <component>.<key> token here is always an error (artifacts={}), since a
    component's own strings must never reference another component.
    """
    return resolve_value(command, merged_vars=resolved_vars, env=env, artifacts={})
