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

import pytest

from emblab import build as build_mod
from emblab import manifests
from emblab import qemu as qemu_mod
from emblab import templating
from emblab.errors import TemplateError

TARGET_NAME = "qemu-arm64-secureboot"


def _precreate_source_and_artifacts(workspace, component, entry=None):
    """Mirrors build.py's own artifacts: path resolution (${vars.X}/${env.X}
    tokens) — entry.vars, when given, overrides component.build.vars the
    same way build.py's merged_vars does."""
    src_dir = Path(workspace) / "src" / component.source.path
    merged_vars = {**component.build.vars, **(entry.vars if entry else {})}
    env = {"JOBS": "4", "WORKSPACE": str(workspace), "ARCH": ""}
    for raw_rel_path in component.artifacts.values():
        rel_path = templating.resolve_value(raw_rel_path, merged_vars=merged_vars, env=env, artifacts={})
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
        _precreate_source_and_artifacts(tmp_path, component, entry)

    recorded = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
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
        "make -j4 CROSS_COMPILE=$CROSS_COMPILE PLAT=qemu DEBUG=1 -B "
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
        _precreate_source_and_artifacts(tmp_path, component, entry)

    recorded = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
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
        "make -j4 CROSS_COMPILE=$CROSS_COMPILE PLAT=qemu DEBUG=1 -B "
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
        _precreate_source_and_artifacts(tmp_path, component, entry)

    run_calls = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
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


def test_barebox_extra_conf_defaults_to_noop_merge():
    """No target sets vars.extra_conf -> the merge_config.sh step is a
    literal shell no-op (empty -n check), never actually invoked."""
    component = manifests.load_component("barebox")
    merged_vars = {**component.build.vars, "arch": "arm64"}
    resolved_vars = templating.resolve_vars(merged_vars, env={}, artifacts={})
    rendered = templating.render_command(
        component.build.command, resolved_vars=resolved_vars, env={"JOBS": "4"}
    )
    expected = (
        "make ARCH=arm64 CROSS_COMPILE=$CROSS_COMPILE efi_v8_defconfig &&"
        " if [ -n \"\" ]; then ./scripts/kconfig/merge_config.sh -m .config ; fi &&"
        " make ARCH=arm64 CROSS_COMPILE=$CROSS_COMPILE -j4"
    )
    assert rendered == expected


def test_barebox_extra_conf_set_by_target_merges_fragment():
    """A target's stack entry can point vars.extra_conf at another
    component's already-built artifact — e.g. a FIT image keystore
    fragment — and it lands inside the merge_config.sh invocation."""
    component = manifests.load_component("barebox")
    merged_vars = {
        **component.build.vars,
        "arch": "arm64",
        "extra_conf": "${fit-image.files}/keystore.cfg",
    }
    resolved_vars = templating.resolve_vars(
        merged_vars, env={}, artifacts={"fit-image": {"files": "/work/artifacts/fit-image"}}
    )
    rendered = templating.render_command(
        component.build.command, resolved_vars=resolved_vars, env={"JOBS": "4"}
    )
    assert (
        "./scripts/kconfig/merge_config.sh -m .config /work/artifacts/fit-image/keystore.cfg"
        in rendered
    )


def test_build_plan_fit_target_resolves_kernel_and_ramdisk_and_copies_its(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    target_name = "qemu-arm64-fit"
    target = manifests.load_target(target_name)
    for entry in target.stack:
        component = manifests.load_component(entry.component)
        _precreate_source_and_artifacts(tmp_path, component, entry)

    recorded = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
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


def test_build_plan_edk2_barebox_target_resolves_bios_kernel_paths(tmp_path, monkeypatch):
    """qemu-arm64-edk2-barebox chain-loads our own compiled edk2 as -bios and
    barebox as -kernel (NOT bundled into the firmware volume — see
    edk2.yaml's description for why not)."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    target_name = "qemu-arm64-edk2-barebox"
    target = manifests.load_target(target_name)
    for entry in target.stack:
        component = manifests.load_component(entry.component)
        _precreate_source_and_artifacts(tmp_path, component, entry)

    def fake_ensure_source(workspace, component, patches, **kwargs):
        return Path(workspace) / "src" / component.source.path

    with patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", return_value=None):
        artifacts = build_mod.build(target_name, tmp_path)

    assert set(artifacts) == {"edk2", "barebox"}

    args = qemu_mod.resolve_args(target, tmp_path)
    artifacts_root = str(tmp_path / "artifacts" / target_name)
    bios_index = args.index("-bios") + 1
    kernel_index = args.index("-kernel") + 1
    assert args[bios_index] == f"{artifacts_root}/edk2/fd"
    assert args[kernel_index] == f"{artifacts_root}/barebox/images/barebox-dt-2nd.img"


def test_build_plan_edk2_fvbootdxe_barebox_bundles_via_patch_and_flag(tmp_path, monkeypatch):
    """qemu-arm64-edk2-fvbootdxe-barebox opts edk2's stack entry into the
    FvBootDxe patch (ADR-010) and sets FV_BOOT_APP_PATH to barebox's own
    output — verifies barebox builds before edk2 (dependency detected via
    the ${barebox.images} token in edk2's vars, same mechanism as any other
    cross-component reference), the patch reaches sources.ensure_source
    merged with edk2's own (empty) build.patches, and the rendered edk2
    build command contains the resolved -D FV_BOOT_APP_PATH flag. No
    -kernel needed — this target's qemu args are -bios only."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    target_name = "qemu-arm64-edk2-fvbootdxe-barebox"
    target = manifests.load_target(target_name)
    for entry in target.stack:
        component = manifests.load_component(entry.component)
        _precreate_source_and_artifacts(tmp_path, component, entry)

    build_order = []
    recorded_patches = {}
    recorded_cmds = {}

    def fake_ensure_source(workspace, component, patches, **kwargs):
        build_order.append(component.name)
        recorded_patches[component.name] = patches
        return Path(workspace) / "src" / component.source.path

    def fake_run(image, workspace, *, command, workdir, bind_mounts=(), extra_env=None, log=print):
        recorded_cmds[workdir.rsplit("/", 1)[-1]] = command[-1]

    with patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", side_effect=fake_run):
        artifacts = build_mod.build(target_name, tmp_path)

    assert set(artifacts) == {"barebox", "edk2"}
    assert build_order.index("barebox") < build_order.index("edk2")  # dependency order

    assert recorded_patches["edk2"] == ["0001-fvbootdxe-bundle-app.patch"]

    artifacts_root = str(tmp_path / "artifacts" / target_name)
    edk2_cmd = recorded_cmds["edk2"]
    assert (
        f"-D FV_BOOT_APP_PATH={artifacts_root}/barebox/images/barebox-dt-2nd.img" in edk2_cmd
    )

    args = qemu_mod.resolve_args(target, tmp_path)
    assert args[args.index("-bios") + 1] == f"{artifacts_root}/edk2/fd"
    assert "-kernel" not in args


def test_build_files_content_change_triggers_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "frag" / "files").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    fragment_path = manifests_dir / "components" / "frag" / "files" / "extra.cfg"
    fragment_path.write_text("CONFIG_FOO=y\n")
    (manifests_dir / "components" / "frag" / "frag.yaml").write_text(
        "build:\n  files:\n    - extra.cfg\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: out.txt\n"
    )

    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="frag-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="frag", vars={}, image="img", builddeps=[], patches=[])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("frag")
    _precreate_source_and_artifacts(tmp_path, component)

    run_calls = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
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


def test_artifacts_path_resolves_vars_and_env_tokens(tmp_path, monkeypatch):
    """A declared artifacts: path can use ${vars.X}/${env.X} tokens, resolved
    the same way build.command already is — needed for e.g. edk2.yaml's
    Build/${vars.platform}-${vars.edk2_build_arch}/... output path."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "comp").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "comp" / "comp.yaml").write_text(
        "build:\n  vars:\n    platform: ArmVirtQemu\n  command: echo hi\n"
        "artifacts:\n  out: Build/${vars.platform}-${env.ARCH}/out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="templated-artifact-target",
        description="",
        arch="riscv64",
        stack=[manifests.StackEntry(component="comp", vars={}, image="img", builddeps=[], patches=[])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("comp")
    src_dir = Path(tmp_path) / "src" / component.source.path
    (src_dir / "Build" / "ArmVirtQemu-riscv64").mkdir(parents=True)
    (src_dir / "Build" / "ArmVirtQemu-riscv64" / "out.txt").write_bytes(b"fake")

    def fake_ensure_source(workspace, component, patches, **kwargs):
        return src_dir

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", return_value=None):
        artifacts = build_mod.build("templated-artifact-target", tmp_path)

    assert Path(artifacts["comp"]["out"]).read_bytes() == b"fake"


def test_directory_artifact_copied_recursively(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "dirart").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "dirart" / "dirart.yaml").write_text(
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: outdir/\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="dirart-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="dirart", vars={}, image="img", builddeps=[], patches=[])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("dirart")
    src_dir = Path(tmp_path) / "src" / component.source.path
    (src_dir / "outdir" / "nested").mkdir(parents=True)
    (src_dir / "outdir" / "top-file").write_bytes(b"top")
    (src_dir / "outdir" / "nested" / "deep-file").write_bytes(b"deep")

    def fake_ensure_source(workspace, component, patches, **kwargs):
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
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="deps-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="deps", vars={}, image="img", builddeps=["foo-tool"], patches=[])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("deps")
    _precreate_source_and_artifacts(tmp_path, component)

    run_calls = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
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


def test_stack_entry_patches_are_target_specific_extras_on_top_of_components_own(tmp_path, monkeypatch):
    """ADR-010: a target's stack-entry patches are extra, on top of whatever
    the component always applies via build.patches — not a replacement."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "comp" / "files").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "comp" / "files" / "0001-base.patch").write_text("base\n")
    (manifests_dir / "components" / "comp" / "files" / "0002-target-extra.patch").write_text("extra\n")
    (manifests_dir / "components" / "comp" / "comp.yaml").write_text(
        "source:\n  git: x\n  ref: main\n"
        "build:\n  vars: {}\n  command: echo hi\n  patches:\n    - 0001-base.patch\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="extra-patch-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="comp", vars={}, image="img", builddeps=[], patches=["0002-target-extra.patch"])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("comp")
    _precreate_source_and_artifacts(tmp_path, component)

    received_patches = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
        received_patches.append(patches)
        return Path(workspace) / "src" / component.source.path

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", return_value=None):
        build_mod.build("extra-patch-target", tmp_path)

    assert received_patches == [["0001-base.patch", "0002-target-extra.patch"]]


def test_stack_entry_image_is_used_for_build(tmp_path, monkeypatch):
    """A component has no image of its own (ADR-009) — the stack entry's
    image is the only source, and two entries can pick different images
    for the same shared component."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "comp").mkdir(parents=True)
    (manifests_dir / "images" / "img-a.yaml").write_text("base_image: a\nprovision: []\n")
    (manifests_dir / "images" / "img-b.yaml").write_text("base_image: b\nprovision: []\n")
    (manifests_dir / "components" / "comp" / "comp.yaml").write_text(
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="picks-image-target",
        description="",
        arch="fake",
        stack=[manifests.StackEntry(component="comp", vars={}, image="img-b", builddeps=[], patches=[])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("comp")
    _precreate_source_and_artifacts(tmp_path, component)

    ensured_images = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
        return Path(workspace) / "src" / component.source.path

    def fake_ensure_image(image, workspace, log=print):
        ensured_images.append(image.name)

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", side_effect=fake_ensure_image), \
         patch("emblab.build.containers.run", return_value=None):
        build_mod.build("picks-image-target", tmp_path)

    assert ensured_images == ["img-b"]


def test_target_arch_resolves_as_env_arch_template_token(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "comp").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "comp" / "comp.yaml").write_text(
        "build:\n  vars: {}\n  command: echo ${env.ARCH}\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="arch-target",
        description="",
        arch="riscv64",
        stack=[manifests.StackEntry(component="comp", vars={}, image="img", builddeps=[], patches=[])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("comp")
    _precreate_source_and_artifacts(tmp_path, component)

    recorded = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
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
        "build:\n  vars: {}\n  command: make PLATFORM=some-platform\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="no-arch-target",
        description="",
        arch="riscv64",
        stack=[manifests.StackEntry(component="comp", vars={}, image="img", builddeps=[], patches=[])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("comp")
    _precreate_source_and_artifacts(tmp_path, component)

    recorded = []

    def fake_ensure_source(workspace, component, patches, **kwargs):
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


def test_component_arch_var_with_no_default_requires_target_to_set_it(tmp_path, monkeypatch):
    """ADR-009: arch-flavored vars (arch/goarch/edk2_arch/...) are a target
    concern, not a component one — a component references ${vars.arch} but
    declares no default for it, so a target that forgets to set it hits a
    clear TemplateError at build time rather than silently building for the
    wrong (or an empty) architecture."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    manifests_dir = tmp_path / "manifests"
    (manifests_dir / "images").mkdir(parents=True)
    (manifests_dir / "components" / "comp").mkdir(parents=True)
    (manifests_dir / "images" / "img.yaml").write_text("base_image: x\nprovision: []\n")
    (manifests_dir / "components" / "comp" / "comp.yaml").write_text(
        "build:\n  vars: {}\n  command: echo ${vars.arch}\n"
        "artifacts:\n  out: out.txt\n"
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)

    target = manifests.Target(
        name="forgot-arch-target",
        description="",
        arch="riscv64",
        stack=[manifests.StackEntry(component="comp", vars={}, image="img", builddeps=[], patches=[])],
        qemu=manifests.Qemu(binary="true", args=[], image="img"),
    )

    component = manifests.load_component("comp")
    _precreate_source_and_artifacts(tmp_path, component)

    def fake_ensure_source(workspace, component, patches, **kwargs):
        return Path(workspace) / "src" / component.source.path

    with patch("emblab.build.manifests.load_target", return_value=target), \
         patch("emblab.build.sources.ensure_source", side_effect=fake_ensure_source), \
         patch("emblab.build.containers.ensure_image", return_value=None), \
         patch("emblab.build.containers.run", return_value=None), \
         pytest.raises(TemplateError, match="vars.arch"):
        build_mod.build("forgot-arch-target", tmp_path)
