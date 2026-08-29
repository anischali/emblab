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
        build=manifests.Build(command="echo hi", setup="", vars={}, files=[], patches=patches or []),
        artifacts={},
    )


def test_ensure_source_initializes_submodules_when_declared(tmp_path):
    component = _component(submodules=True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        sources.ensure_source(tmp_path, component, component.build.patches)

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
        sources.ensure_source(tmp_path, component, component.build.patches)

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
        sources.ensure_source(tmp_path, component, component.build.patches)

    submodule_index = calls.index(["git", "submodule", "update", "--init", "--recursive", "--depth", "1"])
    apply_index = calls.index(["git", "apply", str(patch_path)])
    assert submodule_index < apply_index


def test_ensure_source_applies_caller_supplied_patches_in_order(tmp_path, monkeypatch):
    """ensure_source applies exactly the `patches` list the caller passes —
    build.py assembles this from component.build.patches (always applied)
    plus the target's own stack-entry patches (target-optional extras, e.g.
    edk2's FvBootDxe bundling — see ADR-010); this test doesn't care where
    the list came from, just that ensure_source applies it faithfully and
    in order."""
    files_dir = tmp_path / "manifests-files"
    files_dir.mkdir()
    (files_dir / "0001-base.patch").write_text("base\n")
    (files_dir / "0002-target-extra.patch").write_text("extra\n")
    monkeypatch.setattr(manifests, "component_file_path", lambda name, filename: files_dir / filename)

    component = _component(patches=["0001-base.patch"])  # the component's own baseline
    target_patches = ["0001-base.patch", "0002-target-extra.patch"]  # what build.py would assemble

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        sources.ensure_source(tmp_path, component, target_patches)

    apply_calls = [c for c in calls if c[:2] == ["git", "apply"]]
    assert apply_calls == [
        ["git", "apply", str(files_dir / "0001-base.patch")],
        ["git", "apply", str(files_dir / "0002-target-extra.patch")],
    ]
