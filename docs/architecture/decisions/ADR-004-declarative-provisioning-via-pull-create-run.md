# ADR-004: Declarative image provisioning via pull+create+run, not udocker's Dockerfile builder

## Status
Accepted

## Context
udocker ships an experimental Dockerfile-subset build feature. Its
reliability and feature coverage vary across udocker releases, which is a
poor foundation for a tool meant to work identically "in under 5 minutes"
on whatever udocker version a fresh machine happens to have installed.
Image provisioning still needs to be declarative — a list of commands in
YAML, not an imperative shell script per image.

## Decision
Each image manifest declares a `base_image` (pulled via `udocker pull`) and
a `provision` list of plain shell commands, run once against a named
persistent container via `udocker create` followed by `udocker run`. A
local hash-file idempotency marker (`workspace/state/images/<image>.hash`,
sha256 of `{base_image, provision}`) tracks whether the container has
already been provisioned with the *current* manifest content, so repeat
`emblab build` runs skip re-provisioning entirely. If the manifest changes,
the whole provision list is re-run against the existing container (apt-get
install is naturally idempotent) rather than diffing individual lines.

## Consequences
Only depends on udocker's oldest and most stable verbs (`pull`, `create`,
`run`), never its Dockerfile builder. Provisioning shell lines are directly
portable to a real Dockerfile later without rewriting anything, if the
project ever needs one. Slightly less efficient than layered image caching
— a manifest change re-runs the entire provision list rather than caching
per-line — which is an acceptable trade given provisioning lists change
rarely relative to component build commands.
