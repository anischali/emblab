# ADR-013: `emblab shell` devshell — target/component scoping, non-root, bash completion

## Status
Accepted

## Context
`emblab shell <image>` only ever gave a bare `sh` prompt in `/`, with no
`workspace/` bind-mount at all — a component's cloned source under
`workspace/src/<path>` wasn't even visible inside it — and no bash or
completion, since it launched plain POSIX `sh`. Debugging a real
component's build by hand meant either working entirely outside the
driver (bypassing image provisioning/builddeps) or hand-typing every
`udocker` flag yourself. It also ran as root by default, which is
unwanted for casual interactive use even though ADR-012 already
established that real account creation (`useradd`/`groupadd`) fails under
udocker's unprivileged execution.

## Decision
- New `build.shell_context(target_name, workspace, component_name=None)`:
  resolves a target's stack entry the same way `build()` does per
  component (ADR-009 — a component has no image of its own), runs the
  same `ensure_image`/`ensure_builddeps`/`ensure_source` calls `build()`
  makes for that component (so the shell matches a real build environment
  exactly, without actually running `build.setup`/`build.command`), and
  returns `(image, src_dir)`. Defaults `component_name` to the target's
  *last* stack entry when omitted — the component you're most likely
  mid-iteration on. An unknown `component_name` raises `BuildError`
  rather than silently falling back to something.
- `emblab shell NAME [--component X]`: `NAME` is tried as a target first
  (`manifests.target_path(NAME).exists()`); if it is one, `--component`
  selects which stack entry (default: last), and the shell drops into
  that component's real source dir with `workspace/` bind-mounted the
  same way `build()`'s own container runs already are. If `NAME` isn't a
  target, it falls back to the previous behavior — a raw image name;
  `--component` is rejected in that case, since there's nothing to scope
  it to.
- `containers.shell()`: non-root via udocker's own documented
  `--hostauth --user=<host user>` (confirmed against a real provisioned
  container — `whoami`/`id` resolve to the host user, no
  `useradd`/`groupadd` needed; this sidesteps ADR-012's
  unprivileged-execution finding entirely by borrowing the host's own
  passwd/group entry instead of creating one); `bash`, not `sh`; and an
  explicit `--rcfile helpers/emblab-shell.bashrc` (bind-mounted the same
  way `fitkeys-ctl`/`tsa-stamp` already are onto `/usr/local/bin`), needed
  because the borrowed host user has no real `$HOME` inside the
  container, so Debian's own bash-completion-sourcing block — which lives
  in `~/.bashrc` (from `/etc/skel/.bashrc`), not the system-wide
  `/etc/bash.bashrc` — never runs otherwise. Confirmed against a real
  container: without the rcfile, `shopt progcomp` was already on (bash's
  own default) but no completion function was ever actually registered
  (`complete -p git` empty); with it, the dynamic loader is registered
  (`complete -p -D` shows `_completion_loader`) and a forced load
  (`_completion_loader git`) does register `git`'s real completion
  function.
- `bash-completion` added to every image's `provision:`
  (`gnu-aarch64`/`gnu-riscv64`/`go`/`qemu-runner`) — the package the
  rcfile depends on being present.

## Consequences
`emblab shell <image>` for a bare image name still works, just now via
bash + non-root + completion too, not only the new target/component path.

Non-root by default changes what an interactive `emblab shell` session
can do compared to before (no ad hoc `apt-get install` mid-session, no
writing outside the bind-mounted `workspace/` or other world-writable
paths) — an intentional trade for a safer default. Nothing in the actual
`build.command`/`build.setup` execution path changed: `containers.run()`
(used by `build()`) is untouched by this ADR and still runs as root, same
as before.

The rcfile depends on `helpers/` staying bind-mounted onto
`/usr/local/bin` for every `shell()` call, same as `run()` already
requires for `fitkeys-ctl`/`tsa-stamp` — if that mount point ever moves,
`emblab-shell.bashrc`'s hardcoded path needs to move with it.

This changed `image_hash` for all four images (new `bash-completion` in
`provision:`), so already-provisioned real containers re-provision
(apt-get is idempotent) the next time anything calls `ensure_image` on
them — a one-time re-run, not a behavior change.
