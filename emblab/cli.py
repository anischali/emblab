"""argparse dispatch only — no orchestration logic lives here, so every
subcommand's behavior is independently testable via build.py/qemu.py/etc.
without going through argparse.
"""

import argparse
import pprint
import shutil
import subprocess
import sys
from pathlib import Path

from . import build as build_mod
from . import containers, manifests, sources
from . import qemu as qemu_mod
from .errors import EmblabError

WORKSPACE = Path(__file__).resolve().parent.parent / "workspace"


def cmd_list(args):
    kinds = args.kind or ["images", "components", "targets"]
    for kind in kinds:
        print(f"{kind}:")
        for name in manifests.list_names(kind):
            print(f"  {name}")


def cmd_show(args):
    loaders = {
        "image": manifests.load_image,
        "component": manifests.load_component,
        "target": manifests.load_target,
    }
    pprint.pprint(loaders[args.kind](args.name))


def cmd_fetch(args):
    component = manifests.load_component(args.component)
    # No target in play here, so no target-specific extra patches (ADR-010)
    # — just the component's own always-applied build.patches.
    sources.ensure_source(WORKSPACE, component, component.build.patches)


def cmd_build(args):
    build_mod.build(
        args.target, WORKSPACE, force=args.force, setup_force=args.setup_force, only=args.only
    )


def cmd_run(args):
    if args.rebuild:
        build_mod.build(args.target, WORKSPACE, force=True)
    result = qemu_mod.run(args.target, WORKSPACE)
    sys.exit(result.returncode)


def cmd_shell(args):
    image = manifests.load_image(args.image)
    containers.shell(image, WORKSPACE)


def cmd_clean(args):
    if args.all:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        print("removed workspace/ entirely")
        return

    if args.target:
        target_artifacts = WORKSPACE / "artifacts" / args.target
        if target_artifacts.exists():
            shutil.rmtree(target_artifacts)
        for marker in (WORKSPACE / "state" / "components").glob(f"{args.target}__*.hash"):
            marker.unlink()
        print(f"cleaned artifacts + markers for target '{args.target}'")

    if args.images:
        state_dir = WORKSPACE / "state" / "images"
        if state_dir.exists():
            shutil.rmtree(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        print("cleared image provisioning markers (udocker containers themselves untouched)")


def cmd_doctor(args):
    checks = [
        ("git", ["git", "--version"]),
        ("udocker", ["udocker", "--version"]),
        ("qemu-system-aarch64", ["qemu-system-aarch64", "--version"]),
        ("qemu-system-riscv64", ["qemu-system-riscv64", "--version"]),
        ("qemu-system-arm", ["qemu-system-arm", "--version"]),
    ]
    ok = True
    for name, cmd in checks:
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            print(f"[ok] {name}")
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(f"[MISSING] {name}")
            ok = False

    usage = shutil.disk_usage(WORKSPACE)
    free_gb = usage.free / (1024 ** 3)
    print(f"[info] {free_gb:.1f} GiB free at {WORKSPACE}")
    if free_gb < 5:
        print("[warn] less than 5 GiB free — firmware builds need real disk space")

    if not ok:
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(prog="emblab", description="Declarative embedded bootstack lab")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list images/components/targets")
    p_list.add_argument("kind", nargs="*", choices=["images", "components", "targets"])
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="print a loaded manifest")
    p_show.add_argument("kind", choices=["image", "component", "target"])
    p_show.add_argument("name")
    p_show.set_defaults(func=cmd_show)

    p_fetch = sub.add_parser("fetch", help="clone/update one component's source")
    p_fetch.add_argument("component")
    p_fetch.set_defaults(func=cmd_fetch)

    p_build = sub.add_parser("build", help="build a target's full stack")
    p_build.add_argument("target")
    p_build.add_argument("--force", action="store_true", help="rebuild even if unchanged")
    p_build.add_argument(
        "--setup-force", action="store_true",
        help="rerun each component's setup step even if unchanged (independent of --force)",
    )
    p_build.add_argument("--only", default=None, help="build only up through this component")
    p_build.set_defaults(func=cmd_build)

    p_run = sub.add_parser("run", help="boot a target in QEMU")
    p_run.add_argument("target")
    p_run.add_argument("--rebuild", action="store_true", help="force a rebuild before running")
    p_run.set_defaults(func=cmd_run)

    p_shell = sub.add_parser("shell", help="interactive shell in a provisioned build image")
    p_shell.add_argument("image")
    p_shell.set_defaults(func=cmd_shell)

    p_clean = sub.add_parser("clean", help="remove build artifacts/state")
    p_clean.add_argument("target", nargs="?", default=None)
    p_clean.add_argument("--images", action="store_true", help="also clear image provisioning markers")
    p_clean.add_argument("--all", action="store_true", help="remove workspace/ entirely")
    p_clean.set_defaults(func=cmd_clean)

    p_doctor = sub.add_parser("doctor", help="check host prerequisites")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    try:
        args.func(args)
    except EmblabError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
