# ADR-008: source.submodules for components that need git submodules

## Status
Accepted

## Context
Adding EDK2 support surfaced a real gap: `sources.py`'s clone is
`git clone --depth 1 --branch <ref>`, with no submodule handling at all.
EDK2's `CryptoPkg` vendors OpenSSL and mbedTLS as git submodules
(`CryptoPkg/Library/{OpensslLib/openssl,MbedTlsLib/mbedtls}`), and
`ArmVirtPkg/ArmVirtQemu.dsc` pulls in `CryptoPkg` components — a build
without those submodules initialized fails outright. No component before
edk2 needed this.

## Decision
`source.submodules: true` (optional, default `false`) on a component
manifest. When set, `sources.ensure_source()` runs
`git submodule update --init --recursive --depth 1` immediately after a
fresh clone, before `build.patches` are applied (source.py's own module
docstring documents the full clone → submodules → patches order). Like
patch application (ADR-007), this only ever runs right after a real clone —
never against an already-checked-out tree — for the same reason: a
checkout that's already up to date (ref unchanged, patches unchanged) is
assumed to already have its submodules in the right state from the
previous clone, so re-running submodule init on every build would be
wasted work for large submodules with no upside.

## Consequences
Purely additive — every existing component has no `source.submodules` key
and behaves exactly as before (the field defaults to `False`).

Known gap, accepted rather than solved now: toggling `submodules` in an
already-cloned component's manifest (with `ref` unchanged) isn't detected
the way an edited `build.patches` list already is (ADR-007's
`.emblab-patches-hash` marker) — the existing checkout would simply be
reused without submodules ever getting initialized. Flipping
`source.submodules` after the fact is expected to be rare enough (it's a
one-time fact about a repo's layout, not something that changes build to
build the way patches or vars do) that a `rm -rf workspace/src/<path>` by
hand is an acceptable manual fix; revisit with a real marker (mirroring
patches_hash) only if this turns out to matter in practice.
