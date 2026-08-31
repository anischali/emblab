"""Unit tests for sources.ensure_source's git command sequencing (clone,
submodule init, patch application) — all git calls are mocked, no real
network/filesystem git operations happen.
"""

import shutil
import subprocess
from pathlib import Path

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


def test_init_submodules_retries_in_place_before_ever_reclone(tmp_path):
    """Real, confirmed transient flakiness (edk2's brotli -> oniguruma: a
    plain TLS connect error fetching one leaf submodule, every other
    submodule already fine) resolves on a bare retry of the identical
    command — no re-clone needed, so the first retry must not throw away
    everything a partially-successful submodule update already fetched."""
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
    assert kinds.count("clone") == 1, "a transient failure must retry in place, not re-clone"
    assert kinds.count("submodule") == 2
    # clone, submodule (fails), submodule (bare retry, succeeds) — no re-clone in between
    assert kinds == ["clone", "submodule", "submodule"]


def test_init_submodules_reclones_only_as_the_final_retry(tmp_path):
    """Real `.git/modules/<submodule>` corruption (confirmed against
    coreboot: a different nested submodule fails each time, and a failed
    attempt leaves state corrupted enough that a bare retry fails
    differently again) needs a fresh re-clone eventually — but only once
    the cheap in-place retry has already been tried and failed too."""
    component = _component(submodules=True)
    calls = []
    submodule_attempts = 0

    def fake_run(args, **kwargs):
        nonlocal submodule_attempts
        calls.append(args)
        if args[:2] == ["git", "submodule"]:
            submodule_attempts += 1
            if submodule_attempts < 3:
                raise subprocess.CalledProcessError(1, args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run), \
         patch("emblab.sources.shutil.rmtree"):
        sources.ensure_source(tmp_path, component, component.build.patches)

    kinds = [
        "clone" if c[1] == "clone" else "submodule" if c[:2] == ["git", "submodule"] else "other"
        for c in calls
    ]
    # clone, submodule (fails), submodule (bare retry, fails), reclone, submodule (succeeds)
    assert kinds == ["clone", "submodule", "submodule", "clone", "submodule"]


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


def test_ensure_source_updates_in_place_when_ref_moved(tmp_path):
    """A floating ref moving upstream on an already-cloned component must
    fetch+reset+clean the existing tree in place, not delete it and clone
    from zero — the whole point for a component with submodules
    (coreboot/edk2), where a from-scratch clone re-downloads every
    submodule even when most of their pinned commits haven't changed."""
    component = _component(submodules=True)
    dest = _existing_clone(tmp_path, component)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["git", "rev-parse"]:
            return type("Result", (), {"returncode": 0, "stdout": "oldsha\n"})()
        if args[:2] == ["git", "ls-remote"]:
            return type("Result", (), {"returncode": 0, "stdout": "newsha\trefs/heads/main\n"})()
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run), \
         patch("emblab.sources.shutil.rmtree") as rmtree:
        result = sources.ensure_source(tmp_path, component, component.build.patches)

    assert result == dest
    rmtree.assert_not_called()
    assert not any(c[1] == "clone" for c in calls), "must not delete-and-reclone when the in-place update succeeds"
    assert ["git", "fetch", "--depth", "1", "origin", component.source.ref] in calls
    assert ["git", "reset", "--hard", "FETCH_HEAD"] in calls
    assert ["git", "clean", "-fd"] in calls
    assert calls.index(["git", "reset", "--hard", "FETCH_HEAD"]) < calls.index(
        next(c for c in calls if c[:2] == ["git", "submodule"])
    ), "submodules must be re-synced onto the new commit, not the stale one"


def test_ensure_source_falls_back_to_full_reclone_when_in_place_update_fails(tmp_path):
    """If the in-place fetch/reset/clean/submodule-update sequence itself
    fails (e.g. a real git error, not just a transient submodule blip
    already handled by _run_submodule_update's own retries), ensure_source
    must still fall back to the old, guaranteed-to-work delete-and-clone
    path rather than leaving a half-updated tree behind."""
    component = _component()
    dest = _existing_clone(tmp_path, component)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["git", "rev-parse"]:
            return type("Result", (), {"returncode": 0, "stdout": "oldsha\n"})()
        if args[:2] == ["git", "ls-remote"]:
            return type("Result", (), {"returncode": 0, "stdout": "newsha\trefs/heads/main\n"})()
        if args[:2] == ["git", "fetch"]:
            raise subprocess.CalledProcessError(1, args)
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run), \
         patch("emblab.sources.shutil.rmtree") as rmtree:
        result = sources.ensure_source(tmp_path, component, component.build.patches)

    assert result == dest
    rmtree.assert_called_once_with(dest)
    assert any(c[1] == "clone" for c in calls), "must fall back to a full re-clone after the in-place attempt fails"


def test_ensure_source_recovers_when_dest_already_gone_after_failed_in_place_update(tmp_path):
    """Real, confirmed crash (hit against an actual edk2 checkout): the
    in-place update's own last-resort re-clone (inside
    _run_submodule_update's escalation) can delete `dest` and then have
    its own `git clone` step also fail — leaving `dest` genuinely missing
    from disk, not just "update failed". ensure_source's fallback must not
    then crash trying to rmtree an already-missing directory."""
    component = _component()
    dest = _existing_clone(tmp_path, component)

    def fake_update_in_place(dest_arg, component_arg, patches_arg, *, log):
        shutil.rmtree(dest_arg)  # simulate the nested _reclone's own rmtree
        return False

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["git", "rev-parse"]:
            return type("Result", (), {"returncode": 0, "stdout": "oldsha\n"})()
        if args[:2] == ["git", "ls-remote"]:
            return type("Result", (), {"returncode": 0, "stdout": "newsha\trefs/heads/main\n"})()
        if args[1] == "clone":
            Path(args[-1]).mkdir(parents=True)
            (Path(args[-1]) / ".git").mkdir()
        return type("Result", (), {"returncode": 0, "stdout": ""})()

    with patch("emblab.sources.subprocess.run", side_effect=fake_run), \
         patch("emblab.sources._try_update_in_place", side_effect=fake_update_in_place):
        result = sources.ensure_source(tmp_path, component, component.build.patches)

    assert result == dest
    assert (dest / ".git").exists()  # a fresh clone completed, no crash


def test_mark_finished_is_a_noop_when_nothing_was_marked(tmp_path):
    component = _component()
    _existing_clone(tmp_path, component)

    sources.mark_finished(tmp_path, component)  # must not raise
