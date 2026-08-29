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


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_component_rejects_bare_component_token_in_build_vars(tmp_path, monkeypatch):
    manifests_dir = tmp_path / "manifests"
    _write(manifests_dir / "images" / "img.yaml", "base_image: x\nprovision: []\n")
    _write(
        manifests_dir / "components" / "bad.yaml",
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
        manifests_dir / "components" / "a.yaml",
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
            manifests_dir / "components" / f"{comp}.yaml",
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
