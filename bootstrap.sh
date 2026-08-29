#!/usr/bin/env bash
# Fresh-machine setup: venv + pip install -e . + doctor check.
# Deliberately touches only PyPI (fast) — cloning firmware sources and
# pulling udocker images happen later, inside `emblab build`, not here.
set -euo pipefail

curr_dir="$(cd "$(dirname "${0}")" && pwd)"
cd "${curr_dir}"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -e ".[dev]"

mkdir -p workspace/src workspace/build workspace/artifacts \
         workspace/state/images workspace/state/components workspace/udocker

.venv/bin/python -m emblab.cli doctor || true

echo
echo "emblab ready. Activate with:"
echo "    source .venv/bin/activate"
echo "Then try:"
echo "    emblab list"
echo "    emblab show target qemu-arm64-uefi-barebox"
