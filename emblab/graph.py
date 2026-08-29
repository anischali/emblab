"""Dependency ordering for a target's component stack.

A target's stack is a list of {component, vars} entries. A stack entry
depends on another component when its `vars` contain a bare
``${<component>.<key>}`` token referencing that component's artifact.
`manifests.py` already validates (at load time) that every such reference
points at a real, non-self component within the same target's stack, so this
module only has to order and detect cycles among otherwise-valid edges.
"""

from .errors import CycleError
from .templating import component_refs


def dependency_edges(target):
    """Return {component_name: set(component_names it depends on)}."""
    names = {entry.component for entry in target.stack}
    edges = {name: set() for name in names}
    for entry in target.stack:
        deps = set()
        for value in entry.vars.values():
            deps |= component_refs(value, names)
        edges[entry.component] |= deps
    return edges


def topo_order(target):
    """Kahn's algorithm, ties broken by original stack order (stable, so a
    target with no cross-component wiring builds in the order the author
    wrote it in).
    """
    edges = dependency_edges(target)
    stack_order = [entry.component for entry in target.stack]

    dependents = {name: [] for name in edges}
    in_degree = {name: 0 for name in edges}
    for name, deps in edges.items():
        in_degree[name] = len(deps)
        for dep in deps:
            dependents[dep].append(name)

    ready = sorted((n for n in edges if in_degree[n] == 0), key=stack_order.index)
    ordered = []

    while ready:
        node = ready.pop(0)
        ordered.append(node)
        newly_ready = []
        for dependent in dependents[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                newly_ready.append(dependent)
        ready.extend(newly_ready)
        ready.sort(key=stack_order.index)

    if len(ordered) != len(edges):
        remaining = sorted(set(edges) - set(ordered))
        raise CycleError(
            f"dependency cycle in target '{target.name}' among components: "
            + " -> ".join(remaining)
        )

    return ordered
