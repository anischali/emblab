"""Unit tests for sources.ensure_source's git command sequencing (clone,
submodule init, patch application) — all git calls are mocked, no real
network/filesystem git operations happen.
"""

from unittest.mock import patch

from emblab import manifests, sources


def _component(*, submodules=False, patches=None):
    return manifests.Component(
        name="comp",
        description="",
        source=manifests.Source(git="https://example.invalid/comp.git", ref="main", path="comp", submodules=submodules),
        image="img",
        build=manifests.Build(command="echo hi", vars={}, files=[], builddeps=[], patches=patches or []),
        artifacts={},
    )


def test_ensure_source_initializes_submodules_when_declared(tmp_path):
    component = _component(submodules=True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        sources.ensure_source(tmp_path, component)

    submodule_calls = [c for c in calls if c[:2] == ["git", "submodule"]]
    assert submodule_calls == [["git", "submodule", "update", "--init", "--recursive", "--depth", "1"]]

    clone_index = calls.index(next(c for c in calls if c[1] == "clone"))
    submodule_index = calls.index(submodule_calls[0])
    assert clone_index < submodule_index  # submodules only initialized after a real clone


def test_ensure_source_skips_submodules_by_default(tmp_path):
    component = _component(submodules=False)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        sources.ensure_source(tmp_path, component)

    assert not any(c[:2] == ["git", "submodule"] for c in calls)


def test_ensure_source_initializes_submodules_before_applying_patches(tmp_path, monkeypatch):
    files_dir = tmp_path / "manifests-files"
    files_dir.mkdir()
    patch_path = files_dir / "0001-fix.patch"
    patch_path.write_text("dummy\n")
    monkeypatch.setattr(manifests, "component_file_path", lambda name, filename: files_dir / filename)

    component = _component(submodules=True, patches=["0001-fix.patch"])
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        sources.ensure_source(tmp_path, component)

    submodule_index = calls.index(["git", "submodule", "update", "--init", "--recursive", "--depth", "1"])
    apply_index = calls.index(["git", "apply", str(patch_path)])
    assert submodule_index < apply_index
