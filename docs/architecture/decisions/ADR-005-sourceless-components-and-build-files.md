# ADR-005: Sourceless components and declarative build.files

## Status
Accepted

## Context
Two real needs surfaced once composing a FIT image (kernel + ramdisk,
packaged together) was attempted: first, packaging steps like `mkimage`
don't have an upstream git repository at all — they assemble other
components' outputs — but every component in the original schema required
a `source: {git, ref}`. Second, almost every Kconfig-based component
(barebox, U-Boot, Linux) is built from a base defconfig plus optional
`.cfg` fragments merged via `scripts/kconfig/merge_config.sh`, and FIT
packaging needs a small `.its` template file — neither had a declarative
home; both would otherwise have to be hand-written into a component's
`build.command` as inline shell heredocs, defeating the "manifests are
data" principle from ADR-001.

## Decision
`source:` becomes optional on a component manifest — absent means a
sourceless, purely local packaging component (`Component.source` still
resolves to a `Source` object with `git`/`ref` as `None`, so
`component.source.path` keeps working unchanged everywhere; only
`sources.ensure_source()` gains a one-line branch that just creates an
empty workdir instead of cloning).

Separately, a new optional `build.files: [filenames]` list lets a
component declare small, versioned, repo-committed static assets (Kconfig
fragments, `.its` templates, anything else a build command needs to find
by filename in its working directory) backed by
`manifests/files/<component>/<filename>`. `build.py` copies each declared
file into the component's workdir before every build attempt; the build
command references it by its literal filename — no new templating token
is introduced. Fragment/subset *selection* (which of a component's
declared files actually get merged) reuses the existing `vars`
override mechanism (a `vars.fragments` string a target can override), not
a new schema concept. `state.component_hash()` includes each declared
file's content hash so editing a fragment invalidates the "unchanged,
skip" idempotency marker without needing an unrelated git-ref bump.

## Consequences
Both additions are purely additive — an existing component with `source:`
present and no `build.files` behaves identically to before. The token
grammar and templating layer are untouched (ADR-001's "expressive enough
for every real command" claim holds without extension); u-root's
multi-file embed list and a component's fragment selection both work by
having one `vars` string contain multiple `${...}` tokens or
space-separated names, expanded by a small shell loop inside the build
command itself, rather than by any new Python-side list-handling. The
trade-off is that `build.files` copies are a flat, single-directory drop
(no per-file destination remapping) — sufficient for every real case
found (fragments and one `.its` template), extendable later if a build
ever needs files nested into subdirectories of the workdir.
