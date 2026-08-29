import pytest

from emblab import templating
from emblab.errors import TemplateError


def test_resolve_value_all_namespaces():
    result = templating.resolve_value(
        "cmd --jobs=${env.JOBS} --name=${vars.name} --dep=${dep.artifact}",
        merged_vars={"name": "widget"},
        env={"JOBS": "4"},
        artifacts={"dep": {"artifact": "/abs/path/out.bin"}},
    )
    assert result == "cmd --jobs=4 --name=widget --dep=/abs/path/out.bin"


def test_resolve_value_unknown_var_raises():
    with pytest.raises(TemplateError):
        templating.resolve_value("${vars.missing}", merged_vars={}, env={}, artifacts={})


def test_resolve_value_unknown_env_raises():
    with pytest.raises(TemplateError):
        templating.resolve_value("${env.missing}", merged_vars={}, env={}, artifacts={})


def test_resolve_value_unbuilt_component_raises():
    with pytest.raises(TemplateError):
        templating.resolve_value("${dep.artifact}", merged_vars={}, env={}, artifacts={})


def test_resolve_value_unknown_artifact_key_raises():
    with pytest.raises(TemplateError):
        templating.resolve_value(
            "${dep.missing}", merged_vars={}, env={}, artifacts={"dep": {"artifact": "/x"}}
        )


def test_resolve_value_malformed_token_raises():
    with pytest.raises(TemplateError):
        templating.resolve_value("${nodothere}", merged_vars={}, env={}, artifacts={})


def test_resolve_vars_disallows_vars_self_reference():
    with pytest.raises(TemplateError):
        templating.resolve_vars({"a": "${vars.b}", "b": "x"}, env={}, artifacts={})


def test_resolve_vars_resolves_component_and_env_tokens():
    resolved = templating.resolve_vars(
        {"flag": "IN=${dep.out} JOBS=${env.JOBS}"},
        env={"JOBS": "8"},
        artifacts={"dep": {"out": "/abs/out"}},
    )
    assert resolved == {"flag": "IN=/abs/out JOBS=8"}


def test_component_refs_filters_reserved_and_unknown_names():
    refs = templating.component_refs(
        "${vars.x} ${env.JOBS} ${dep.artifact} ${stranger.thing}",
        known_components={"dep"},
    )
    assert refs == {"dep"}


def test_default_env_has_jobs_and_workspace(tmp_path):
    env = templating.default_env(tmp_path)
    assert "JOBS" in env
    assert env["WORKSPACE"] == str(tmp_path)


def test_render_command_uses_vars_and_env_only():
    rendered = templating.render_command(
        "build --jobs=${env.JOBS} --flag=${vars.flag}",
        resolved_vars={"flag": "/abs/out"},
        env={"JOBS": "8"},
    )
    assert rendered == "build --jobs=8 --flag=/abs/out"
