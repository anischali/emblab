from pathlib import Path

import pytest

from emblab import manifests
from emblab.errors import ManifestError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def fixture_manifests_dir(monkeypatch):
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", FIXTURES)


def test_load_image():
    image = manifests.load_image("fake-image")
    assert image.base_image == "fake/base:latest"
    assert image.provision == ["echo hello"]
    assert image.env == {"FOO": "bar"}


def test_load_component():
    component = manifests.load_component("fake-a")
    assert component.source.git == "https://example.invalid/a.git"
    assert component.source.ref == "main"
    assert component.image == "fake-image"
    assert component.build.vars == {"greeting": "hello"}
    assert component.artifacts == {"out": "out.txt"}


def test_load_target_orders_matches_yaml_and_validates():
    target = manifests.load_target("fake-target")
    assert [entry.component for entry in target.stack] == ["fake-a", "fake-b"]
    assert target.qemu.binary == "true"
    assert target.qemu.args == ["-x", "${fake-a.out}"]


def test_load_target_stack_entry_without_image_override_is_none():
    target = manifests.load_target("fake-target")
    assert all(entry.image is None for entry in target.stack)


def test_load_target_stack_entry_image_override_is_parsed():
    target = manifests.load_target("fake-target-image-override")
    assert target.stack[0].image == "fake-image-2"


def test_load_target_stack_entry_unknown_image_override_raises_clear_error(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    for name in ("fake-a",):
        _write(
            manifests_dir / "components" / name / f"{name}.yaml",
            (FIXTURES / "components" / name / f"{name}.yaml").read_text(),
        )
    _write(manifests_dir / "images" / "fake-image.yaml", (FIXTURES / "images" / "fake-image.yaml").read_text())
    _write(
        manifests_dir / "targets" / "bad-override.yaml",
        "arch: fake\n"
        "stack:\n"
        "  - component: fake-a\n"
        "    image: no-such-image\n"
        "    vars: {}\n"
        "qemu:\n  binary: \"true\"\n  args: []\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    with pytest.raises(ManifestError, match="no-such-image"):
        manifests.load_target("bad-override")


def test_load_component_builddeps_defaults_to_empty_list():
    component = manifests.load_component("fake-a")
    assert component.build.builddeps == []


def test_load_component_builddeps_is_parsed(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "deps" / "deps.yaml",
        "image: img\n"
        "build:\n  vars: {}\n  command: echo hi\n  builddeps:\n    - foo\n    - bar\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    component = manifests.load_component("deps")
    assert component.build.builddeps == ["foo", "bar"]


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_component_rejects_bare_component_token_in_build_vars(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "bad" / "bad.yaml",
        "source:\n  git: x\n  ref: main\n"
        "image: img\n"
        "build:\n  vars:\n    x: ${other.artifact}\n  command: echo hi\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    with pytest.raises(ManifestError, match="cross-component reference"):
        manifests.load_component("bad")


def test_target_rejects_unknown_component_in_stack(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(
        manifests_dir / "targets" / "bad.yaml",
        "stack:\n  - component: nope\n    vars: {}\n"
        "qemu:\n  binary: true\n  args: []\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    with pytest.raises(ManifestError, match="unknown component"):
        manifests.load_target("bad")


def test_target_rejects_self_reference(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "a" / "a.yaml",
        "source:\n  git: x\n  ref: main\n"
        "image: img\n"
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: out.txt\n",
    )
    _write(
        manifests_dir / "targets" / "bad.yaml",
        "stack:\n  - component: a\n    vars:\n      x: ${a.out}\n"
        "qemu:\n  binary: true\n  args: []\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    with pytest.raises(ManifestError, match="cannot depend on itself"):
        manifests.load_target("bad")


def test_target_rejects_reference_to_component_outside_stack(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    for comp in ("a", "b"):
        _write(
            manifests_dir / "components" / comp / f"{comp}.yaml",
            "source:\n  git: x\n  ref: main\n"
            "image: img\n"
            "build:\n  vars: {}\n  command: echo hi\n"
            "artifacts:\n  out: out.txt\n",
        )
    _write(
        manifests_dir / "targets" / "bad.yaml",
        # target's stack only contains 'a', but references sibling 'b' which
        # is never listed in this target's own stack
        "stack:\n  - component: a\n    vars:\n      x: ${b.out}\n"
        "qemu:\n  binary: true\n  args: []\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    with pytest.raises(ManifestError, match="not a component in this target's stack"):
        manifests.load_target("bad")


def test_missing_manifest_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", tmp_path / "manifests")
    with pytest.raises(ManifestError, match="not found"):
        manifests.load_image("nope")


def test_sourceless_component_has_none_git_ref_and_derived_path(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "packager" / "packager.yaml",
        "image: img\n"
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts:\n  out: out.txt\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    component = manifests.load_component("packager")
    assert component.source.git is None
    assert component.source.ref is None
    assert component.source.path == "packager"


def test_build_files_missing_on_disk_raises_clear_error(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "frag" / "frag.yaml",
        "image: img\n"
        "build:\n  files:\n    - missing.cfg\n  vars: {}\n  command: echo hi\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    with pytest.raises(ManifestError, match="missing.cfg"):
        manifests.load_component("frag")


def test_build_files_present_on_disk_loads_fine(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(manifests_dir / "components" / "frag" / "files" / "extra.cfg", "CONFIG_FOO=y\n")
    _write(
        manifests_dir / "components" / "frag" / "frag.yaml",
        "image: img\n"
        "build:\n  files:\n    - extra.cfg\n  vars: {}\n  command: echo hi\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    component = manifests.load_component("frag")
    assert component.build.files == ["extra.cfg"]


def test_component_dir_layout_matches_yocto_style(tmp_path, monkeypatch):
    """manifests/components/<name>/<name>.yaml, with a sibling files/ dir for
    that component's own patches and static files — not a flat
    manifests/components/<name>.yaml plus a separate top-level files tree."""
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "layout-check" / "layout-check.yaml",
        "image: img\nbuild:\n  vars: {}\n  command: echo hi\nartifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    assert manifests.component_path("layout-check") == manifests_dir / "components" / "layout-check" / "layout-check.yaml"
    assert manifests.files_dir("layout-check") == manifests_dir / "components" / "layout-check" / "files"
    assert manifests.list_names("components") == ["layout-check"]


def test_build_patches_missing_on_disk_raises_clear_error(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "patched" / "patched.yaml",
        "source:\n  git: x\n  ref: main\n"
        "image: img\n"
        "build:\n  patches:\n    - 0001-missing.patch\n  vars: {}\n  command: echo hi\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    with pytest.raises(ManifestError, match="0001-missing.patch"):
        manifests.load_component("patched")


def test_build_patches_present_on_disk_loads_in_order(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(manifests_dir / "components" / "patched" / "files" / "0001-a.patch", "a\n")
    _write(manifests_dir / "components" / "patched" / "files" / "0002-b.patch", "b\n")
    _write(
        manifests_dir / "components" / "patched" / "patched.yaml",
        "source:\n  git: x\n  ref: main\n"
        "image: img\n"
        "build:\n  patches:\n    - 0001-a.patch\n    - 0002-b.patch\n  vars: {}\n  command: echo hi\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    component = manifests.load_component("patched")
    assert component.build.patches == ["0001-a.patch", "0002-b.patch"]


def test_source_submodules_defaults_to_false(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "comp" / "comp.yaml",
        "source:\n  git: x\n  ref: main\n"
        "image: img\n"
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    component = manifests.load_component("comp")
    assert component.source.submodules is False


def test_source_submodules_true_is_parsed(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "comp" / "comp.yaml",
        "source:\n  git: x\n  ref: main\n  submodules: true\n"
        "image: img\n"
        "build:\n  vars: {}\n  command: echo hi\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    component = manifests.load_component("comp")
    assert component.source.submodules is True


def test_sourceless_component_with_patches_raises_clear_error(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(manifests_dir / "components" / "packager" / "files" / "0001-a.patch", "a\n")
    _write(
        manifests_dir / "components" / "packager" / "packager.yaml",
        "image: img\n"  # no source: -> sourceless
        "build:\n  patches:\n    - 0001-a.patch\n  vars: {}\n  command: echo hi\n"
        "artifacts: {}\n",
    )
    monkeypatch.setattr(manifests, "MANIFESTS_DIR", manifests_dir)
    with pytest.raises(ManifestError, match="no source"):
        manifests.load_component("packager")
