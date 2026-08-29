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
        if rel_path.endswith("/"):
            d = src_dir / rel_path
            d.mkdir(parents=True, exist_ok=True)
            (d / "dummy-file").write_bytes(b"fake")
        else:
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
        f"BL33={artifacts_root}/barebox/images/barebox-dt-2nd.img"
    )
    assert rendered == expected


def test_build_plan_secureboot_uboot_omits_arm_linux_kernel_as_bl33(tmp_path, monkeypatch):
    """qemu-arm64-secureboot-uboot overrides tf-a's bl33_flags to "" since
    u-boot is a real bootloader (its own BL33), unlike barebox's EFI-mode
    build which TF-A loads as a raw kernel/EFI payload via
    ARM_LINUX_KERNEL_AS_BL33=1 in the plain qemu-arm64-secureboot target."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    target_name = "qemu-arm64-secureboot-uboot"
    target = manifests.load_target(target_name)
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
        artifacts = build_mod.build(target_name, tmp_path)

    assert set(artifacts) == {"optee-os", "u-boot", "tf-a"}

    tfa_cmds = [cmd[-1] for _, cmd in recorded if "GENERATE_COT" in cmd[-1]]
    assert len(tfa_cmds) == 1
    rendered = tfa_cmds[0]

    assert "ARM_LINUX_KERNEL_AS_BL33" not in rendered

    artifacts_root = str(tmp_path / "artifacts" / target_name)
    expected = (
        "make -j4 CROSS_COMPILE=aarch64-linux-gnu- PLAT=qemu DEBUG=1 -B "
        "RESET_TO_BL31=1 LOG_LEVEL=30 "
        f"BL32={artifacts_root}/optee-os/tee-header "
        f"BL32_EXTRA1={artifacts_root}/optee-os/tee-pager "
        f"BL32_EXTRA2={artifacts_root}/optee-os/tee-pageable "
        "BL32_RAM_LOCATION=tdram SPD=opteed GENERATE_COT=1 all fip "
        # bl33_flags="" between two literal spaces in tf-a.yaml's command ->
        # a double space here, same latent (harmless for make) behavior
        # bl32_flags="" already has whenever a target leaves it unset.
        f" BL33={artifacts_root}/u-boot/bin"
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


def test_build_plan_fit_target_resolves_kernel_and_ramdisk_and_copies_its(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    target_name = "qemu-arm64-fit"
    target = manifests.load_target(target_name)
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
        artifacts = build_mod.build(target_name, tmp_path)

    assert set(artifacts) == {"linux-kernel", "uroot-ramdisk", "fit-image"}

    fit_cmds = [cmd[-1] for _, cmd in recorded if "mkimage" in cmd[-1]]
    assert len(fit_cmds) == 1
    rendered = fit_cmds[0]

    artifacts_root = str(tmp_path / "artifacts" / target_name)
    expected = (
        "set -e; "
        f"cp {artifacts_root}/linux-kernel/image Image; "
        f"cp {artifacts_root}/uroot-ramdisk/cpio initramfs.cpio; "
        "gzip -kf initramfs.cpio; "
        "mkimage -f fit-image.its fitImage"
    )
    assert rendered == expected

    # build.files (the .its template) must land in fit-image's workdir
    its_copy = tmp_path / "src" / "fit-image" / "fit-image.its"
    assert its_copy.exists()
    assert its_copy.read_text() == manifests.component_file_path("fit-image", "fit-image.its").read_text()


def test_build_files_content_change_triggers_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "frag" / "files").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    fragment_path = manifests_dir / "components" / "frag" / "files" / "extra.cfg"
    fragment_path.write_text("CONFIG_FOO=y\n")
    (manifests_dir / "components" / "frag" / "frag.yaml").write_text(
        "image: img\n"
        "build:\n  files:\n    - extra.cfg\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: out.txt\n"
    )

    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="frag-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="frag", vars={})],
        qemu=manifests.Qemu(binary="true", args=[]),
    )

    component = manifests.load_component("frag")
    _precreate_source_and_artifacts(tmp_path, component)

    run_calls = []

    def fake_ensure_source(workspace, component, **kwargs):
        return Path(workspace) / "src" / component.source.path

    def fake_run(image, workspace, *, command, workdir, bind_mounts=(), extra_env=None, log=print):
        run_calls.append(command)

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", side_effect=fake_run):
        build_mod.build("frag-target", tmp_path)
        first_count = len(run_calls)

        fragment_path.write_text("CONFIG_FOO=y\nCONFIG_BAR=y\n")

        build_mod.build("frag-target", tmp_path)
        second_count = len(run_calls)

    assert first_count == 1
    assert second_count == first_count + 1  # content changed -> rebuilt, not skipped


def test_directory_artifact_copied_recursively(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "dirart").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "dirart" / "dirart.yaml").write_text(
        "image: img\n"
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: outdir/\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="dirart-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="dirart", vars={})],
        qemu=manifests.Qemu(binary="true", args=[]),
    )

    component = manifests.load_component("dirart")
    src_dir = Path(tmp_path) / "src" / component.source.path
    (src_dir / "outdir" / "nested").mkdir(parents=True)
    (src_dir / "outdir" / "top-file").write_bytes(b"top")
    (src_dir / "outdir" / "nested" / "deep-file").write_bytes(b"deep")

    def fake_ensure_source(workspace, component, **kwargs):
        return src_dir

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", return_value=None):
        build_mod.build("dirart-target", tmp_path)

    out_dir = tmp_path / "artifacts" / "dirart-target" / "dirart" / "out"
    assert (out_dir / "top-file").read_bytes() == b"top"
    assert (out_dir / "nested" / "deep-file").read_bytes() == b"deep"


def test_builddeps_installed_once_then_skipped_on_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "deps").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "deps" / "deps.yaml").write_text(
        "image: img\n"
        "build:\n  vars: {}\n  command: echo hi\n  builddeps:\n    - foo-tool\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="deps-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="deps", vars={})],
        qemu=manifests.Qemu(binary="true", args=[]),
    )

    component = manifests.load_component("deps")
    _precreate_source_and_artifacts(tmp_path, component)

    run_calls = []

    def fake_ensure_source(workspace, component, **kwargs):
        return Path(workspace) / "src" / component.source.path

    def fake_run(image, workspace, *, command, workdir, bind_mounts=(), extra_env=None, log=print):
        run_calls.append(command)

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", side_effect=fake_run):
        build_mod.build("deps-target", tmp_path)
        apt_calls_first = [c for c in run_calls if "foo-tool" in c[-1]]

        build_mod.build("deps-target", tmp_path, force=True)
        apt_calls_second = [c for c in run_calls if "foo-tool" in c[-1]]

    assert len(apt_calls_first) == 1
    assert "apt-get install" in apt_calls_first[0][-1]
    # unchanged builddeps -> not reinstalled on the forced rebuild
    assert len(apt_calls_second) == len(apt_calls_first)


def test_stack_entry_image_override_is_used_for_build(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "comp").mkdir(parents=True)
    (manifests_dir / "images" / "img-a.yaml").write_text("base_image: a\nprovision: []\n")
    (manifests_dir / "images" / "img-b.yaml").write_text("base_image: b\nprovision: []\n")
    (manifests_dir / "components" / "comp" / "comp.yaml").write_text(
        "image: img-a\n"
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="override-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="comp", vars={}, image="img-b")],
        qemu=manifests.Qemu(binary="true", args=[]),
    )

    component = manifests.load_component("comp")
    _precreate_source_and_artifacts(tmp_path, component)

    ensured_images = []

    def fake_ensure_source(workspace, component, **kwargs):
        return Path(workspace) / "src" / component.source.path

    def fake_ensure_image(image, workspace, log=print):
        ensured_images.append(image.name)

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", side_effect=fake_ensure_image), \
         patch("emblab.build.containers.run", return_value=None):
        build_mod.build("override-target", tmp_path)

    assert ensured_images == ["img-b"]  # the target's override, not the component's own "img-a"


def test_target_arch_resolves_as_env_arch_template_token(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "comp").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "comp" / "comp.yaml").write_text(
        "image: img\n"
        "build:\n  vars: {}\n  command: echo ${env.ARCH}\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="arch-target",
        description="",
        arch="riscv64",
        stack=[manifests.StackEntry(component="comp", vars={})],
        qemu=manifests.Qemu(binary="true", args=[]),
    )

    component = manifests.load_component("comp")
    _precreate_source_and_artifacts(tmp_path, component)

    recorded = []

    def fake_ensure_source(workspace, component, **kwargs):
        return Path(workspace) / "src" / component.source.path

    def fake_run(image, workspace, *, command, workdir, bind_mounts=(), extra_env=None, log=print):
        recorded.append((command, extra_env))

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", side_effect=fake_run):
        build_mod.build("arch-target", tmp_path)

    (command, extra_env) = recorded[0]
    assert command == ["sh", "-c", "echo riscv64"]
    assert extra_env is None  # resolved at template-render time, never a real container env var


def test_component_not_referencing_env_arch_is_structurally_unaffected(tmp_path, monkeypatch):
    """Regression test: optee-os/tf-a's commands never reference ${env.ARCH}
    (they use their own PLATFORM=/PLAT= mechanisms). An earlier attempt at
    this feature injected ARCH as a real container env var for every build,
    which broke a real emblab build qemu-arm64-secureboot run — OP-TEE's own
    build reads ARCH from the environment and defaults it to "arm"
    internally, so a force-injected "arm64" made it look for
    lib/libutee/arch/arm64/sub.mk, which doesn't exist. Because ARCH is now
    a template token instead, a command that never writes ${env.ARCH} is
    rendered completely untouched — this isn't a driver-side special case,
    it's the same string substitution ${env.JOBS} always was."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "comp").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "comp" / "comp.yaml").write_text(
        "image: img\n"
        "build:\n  vars: {}\n  command: make PLATFORM=some-platform\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="no-arch-target",
        description="",
        arch="riscv64",
        stack=[manifests.StackEntry(component="comp", vars={})],
        qemu=manifests.Qemu(binary="true", args=[]),
    )

    component = manifests.load_component("comp")
    _precreate_source_and_artifacts(tmp_path, component)

    recorded = []

    def fake_ensure_source(workspace, component, **kwargs):
        return Path(workspace) / "src" / component.source.path

    def fake_run(image, workspace, *, command, workdir, bind_mounts=(), extra_env=None, log=print):
        recorded.append((command, extra_env))

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", side_effect=fake_run):
        build_mod.build("no-arch-target", tmp_path)

    (command, extra_env) = recorded[0]
    assert command == ["sh", "-c", "make PLATFORM=some-platform"]
    assert extra_env is None
