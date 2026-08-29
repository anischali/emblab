# CLAUDE.md

## Project practices:
- Read CONTEXT.md first, every session, before doing anything else
- Manifests are data; `emblab/` is a thin generic driver — logic belongs in the driver, never duplicated per manifest
- Never hardcode a cross-component path; use `${component.artifact}` tokens, resolved only at target level
- Keep components reusable across targets; never reference a sibling component inside a component manifest
- Components are agnostic of image, architecture, and builddeps — a target's stack entry sets `image:` (required) and may set `builddeps:`; a component may reference `${vars.arch}`-style vars but must not default them, so a target that forgets to set one gets a clear error instead of silently building for the wrong arch (see ADR-009)
- `build.patches` on a component is its baseline (always applied, every target); a stack entry's own `patches:` is for target-optional extras on top (e.g. one target wants a component built a different way, another doesn't) — see ADR-010
- Update CONTEXT.md's Proven/In progress/Next sections as part of the same change, not as an afterthought
- Prefer stdlib; PyYAML is the only mandatory runtime dependency — think twice before adding another
- Do not read or infer conventions from other projects under `~/sources` (or elsewhere) without being explicitly asked

## Conventions
- ADRs at `docs/architecture/decisions/ADR-NNN-slug.md`, structure: Status / Context / Decision / Consequences
- Manifest YAML lives under `manifests/{images,components,targets}/`, never inline in Python
- A component manifest lives at `manifests/components/<name>/<name>.yaml`, Yocto-style, with a sibling `files/` dir for that component's own patches and static files (see ADR-007) — images and targets stay flat (`manifests/images/<name>.yaml`, `manifests/targets/<name>.yaml`)
- `workspace/` is gitignored and disposable; nothing there is source of truth
- A build command that hasn't been verified against a real clone must say so in a YAML comment (see `barebox.yaml`)
