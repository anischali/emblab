"""Full build-plan dry run: mocks containers.run/ensure_image and
sources.ensure_source so no network/udocker call ever happens, then asserts
the rendered `tf-a` command exactly matches the flag structure transcribed
from barebox-arm64-poc/build.sh (see manifests/components/tf-a.yaml) — this
is the regression check that the schema faithfully reproduces the real,
working command, not an approximation of it.
"""

import os
from pathlib import Path
from unittest.mock import patch

from emblab import build as build_mod
from emblab import manifests

TARGET_NAME = "qemu-arm64-secureboot"


def _precreate_source_and_artifacts(workspace, component):
    src_dir = Path(workspace) / "src" / component.source.path
    for rel_path in component.artifacts.values():
        f = src_dir / rel_path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"fake")
    return src_dir


def test_build_plan_renders_verbatim_tfa_command(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    target = manifests.load_target(TARGET_NAME)
    for entry in target.stack:
        component = manifests.load_component(entry.component)
        _precreate_source_and_artifacts(tmp_path, component)

    recorded = []

    def fake_ensure_source(workspace, component, **kwargs):
        return Path(workspace) / "src" / component.source.path

    def fake_run(image, workspace, *, command, workdir, bind_mounts=(), extra_env=None, log=print):
        recorded.append((image.name, command))

    with patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", side_effect=fake_run):
        artifacts = build_mod.build(TARGET_NAME, tmp_path)

    assert set(artifacts) == {"optee-os", "barebox", "tf-a"}

    tfa_cmds = [cmd[-1] for _, cmd in recorded if "ARM_LINUX_KERNEL_AS_BL33" in cmd[-1]]
    assert len(tfa_cmds) == 1
    rendered = tfa_cmds[0]

    artifacts_root = str(tmp_path / "artifacts" / TARGET_NAME)
    expected = (
        "make -j4 CROSS_COMPILE=aarch64-linux-gnu- PLAT=qemu DEBUG=1 -B "
        "RESET_TO_BL31=1 LOG_LEVEL=30 "
        f"BL32={artifacts_root}/optee-os/tee-header "
        f"BL32_EXTRA1={artifacts_root}/optee-os/tee-pager "
        f"BL32_EXTRA2={artifacts_root}/optee-os/tee-pageable "
        "BL32_RAM_LOCATION=tdram SPD=opteed GENERATE_COT=1 all fip "
        "ARM_LINUX_KERNEL_AS_BL33=1 "
        f"BL33={artifacts_root}/barebox/barebox-dt-2nd"
    )
    assert rendered == expected


def test_build_plan_skips_unchanged_component_on_second_run(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    target_name = "qemu-arm64-uefi-barebox"
    target = manifests.load_target(target_name)
    for entry in target.stack:
        component = manifests.load_component(entry.component)
        _precreate_source_and_artifacts(tmp_path, component)

    run_calls = []

    def fake_ensure_source(workspace, component, **kwargs):
        return Path(workspace) / "src" / component.source.path

    def fake_run(image, workspace, *, command, workdir, bind_mounts=(), extra_env=None, log=print):
        run_calls.append(command)

    with patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", side_effect=fake_run):
        build_mod.build(target_name, tmp_path)
        first_run_count = len(run_calls)
        build_mod.build(target_name, tmp_path)
        second_run_count = len(run_calls)

    assert first_run_count > 0
    assert second_run_count == first_run_count  # nothing rebuilt on the second, unchanged run
