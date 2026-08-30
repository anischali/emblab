"""Unit tests for sources.ensure_source's git command sequencing (clone,
submodule init, patch application) — all git calls are mocked, no real
network/filesystem git operations happen.
"""

import subprocess

import pytest
from unittest.mock import patch

from emblab import manifests, sources
from emblab.errors import EmblabError


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


def test_ensure_source_initializes_only_named_submodules_when_list_declared(tmp_path):
    component = _component(submodules=["3rdparty/arm-trusted-firmware"])
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        sources.ensure_source(tmp_path, component, component.build.patches)

    submodule_calls = [c for c in calls if c[:2] == ["git", "submodule"]]
    assert submodule_calls == [
        ["git", "submodule", "update", "--init", "--recursive", "--depth", "1",
         "--", "3rdparty/arm-trusted-firmware"]
    ]


def test_ensure_source_skips_submodules_by_default(tmp_path):
    component = _component(submodules=False)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        sources.ensure_source(tmp_path, component, component.build.patches)

    assert not any(c[:2] == ["git", "submodule"] for c in calls)


def test_init_submodules_retries_with_a_fresh_reclone_on_failure(tmp_path):
    """Real, reproducible flakiness in `git submodule update --init
    --recursive` (confirmed against coreboot: a different nested submodule
    fails each time, and a failed attempt leaves .git/modules/<submodule>
    corrupted enough that a bare retry of the same command fails
    differently again) means a retry needs a fresh re-clone first, not
    just the same command run again."""
    component = _component(submodules=True)
    calls = []
    submodule_attempts = 0

    def fake_run(args, **kwargs):
        nonlocal submodule_attempts
        calls.append(args)
        if args[:2] == ["git", "submodule"]:
            submodule_attempts += 1
            if submodule_attempts == 1:
                raise subprocess.CalledProcessError(1, args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run), \
         patch("emblab.sources.shutil.rmtree"):
        sources.ensure_source(tmp_path, component, component.build.patches)

    kinds = [
        "clone" if c[1] == "clone" else "submodule" if c[:2] == ["git", "submodule"] else "other"
        for c in calls
    ]
    assert kinds.count("clone") == 2, "a failed attempt must re-clone before retrying"
    assert kinds.count("submodule") == 2
    # clone, submodule (fails), reclone, submodule (retry, succeeds) — in that order
    assert kinds == ["clone", "submodule", "clone", "submodule"]


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


def _existing_clone(workspace, component):
    """Fake a pre-existing clone on disk (no real git involved) — enough to
    satisfy ensure_source's `dest.exists() and (dest / ".git").exists()`
    on-disk check for the manual-edit marker tests below."""
    dest = sources.source_dir(workspace, component)
    (dest / ".git").mkdir(parents=True)
    return dest


def test_mark_modified_requires_an_existing_clone(tmp_path):
    component = _component()
    with pytest.raises(EmblabError):
        sources.mark_modified(tmp_path, component)


def test_mark_modified_drops_marker_in_source_dir(tmp_path):
    component = _component()
    dest = _existing_clone(tmp_path, component)

    sources.mark_modified(tmp_path, component)

    assert (dest / sources.MANUAL_EDIT_MARKER_NAME).exists()


def test_ensure_source_skips_all_git_calls_when_marked_for_manual_edit(tmp_path):
    component = _component()
    dest = _existing_clone(tmp_path, component)
    sources.mark_modified(tmp_path, component)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        result = sources.ensure_source(tmp_path, component, component.build.patches)

    assert result == dest
    assert calls == []  # no ls-remote, no clone, no patch reapply


def test_ensure_source_manual_marker_wins_even_with_force(tmp_path):
    """A marked component must survive even `force=True` — only
    `mark_finished` (removing the marker first) can hand it back to
    driver-tracked fetching. See cmd_reset's --reclone."""
    component = _component()
    dest = _existing_clone(tmp_path, component)
    sources.mark_modified(tmp_path, component)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        result = sources.ensure_source(tmp_path, component, component.build.patches, force=True)

    assert result == dest
    assert calls == []


def test_mark_finished_removes_marker_and_resumes_normal_tracking(tmp_path):
    from emblab import state

    component = _component()
    dest = _existing_clone(tmp_path, component)
    # pre-seed the patches marker so this test isolates ref-check behavior,
    # not the (already covered elsewhere) patches-changed re-clone path.
    state.write_marker(dest / sources.PATCHES_MARKER_NAME, state.patches_hash(component.name, component.build.patches))
    sources.mark_modified(tmp_path, component)

    sources.mark_finished(tmp_path, component)

    assert not (dest / sources.MANUAL_EDIT_MARKER_NAME).exists()

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["git", "rev-parse"]:
            return type("Result", (), {"returncode": 0, "stdout": "deadbeef\n"})()
        if args[:2] == ["git", "ls-remote"]:
            return type("Result", (), {"returncode": 0, "stdout": "deadbeef\trefs/heads/main\n"})()
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run):
        result = sources.ensure_source(tmp_path, component, component.build.patches)

    assert result == dest
    # ref unchanged, patches unchanged -> no re-clone, but the freshness
    # check itself ran again (unlike the marked case above).
    assert ["git", "ls-remote", component.source.git, component.source.ref] in calls
    assert not any(c[1] == "clone" for c in calls)


def test_mark_finished_is_a_noop_when_nothing_was_marked(tmp_path):
    component = _component()
    _existing_clone(tmp_path, component)

    sources.mark_finished(tmp_path, component)  # must not raise
