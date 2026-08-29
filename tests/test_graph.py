import pytest

from emblab import graph
from emblab.errors import CycleError
from emblab.manifests import Qemu, StackEntry, Target


def _target(stack_specs):
    stack = [StackEntry(component=name, vars=v) for name, v in stack_specs]
    return Target(name="t", description="", arch="fake", stack=stack, qemu=Qemu(binary="true", args=[]))


def test_topo_order_no_deps_keeps_stack_order():
    target = _target([("a", {}), ("b", {}), ("c", {})])
    assert graph.topo_order(target) == ["a", "b", "c"]


def test_topo_order_respects_dependency_regardless_of_stack_position():
    target = _target([
        ("b", {"x": "${a.out}"}),
        ("a", {}),
    ])
    assert graph.topo_order(target) == ["a", "b"]


def test_topo_order_multiple_dependencies():
    target = _target([
        ("a", {}),
        ("b", {}),
        ("c", {"x": "${a.out}", "y": "${b.out}"}),
    ])
    assert graph.topo_order(target) == ["a", "b", "c"]


def test_topo_order_detects_cycle():
    target = _target([
        ("a", {"x": "${b.out}"}),
        ("b", {"x": "${a.out}"}),
    ])
    with pytest.raises(CycleError):
        graph.topo_order(target)


def test_dependency_edges_ignores_vars_and_env_tokens():
    target = _target([("a", {"x": "${vars.y} ${env.JOBS}"})])
    assert graph.dependency_edges(target) == {"a": set()}
