# CLAUDE.md

## Project practices:
- Read CONTEXT.md first, every session, before doing anything else
- Manifests are data; `emblab/` is a thin generic driver — logic belongs in the driver, never duplicated per manifest
- Never hardcode a cross-component path; use `${component.artifact}` tokens, resolved only at target level
- Keep components reusable across targets; never reference a sibling component inside a component manifest
- Update CONTEXT.md's Proven/In progress/Next sections as part of the same change, not as an afterthought
- Prefer stdlib; PyYAML is the only mandatory runtime dependency — think twice before adding another
- Do not read or infer conventions from other projects under `~/sources` (or elsewhere) without being explicitly asked

## Conventions
- ADRs at `docs/architecture/decisions/ADR-NNN-slug.md`, structure: Status / Context / Decision / Consequences
- Manifest YAML lives under `manifests/{images,components,targets}/`, never inline in Python
- `workspace/` is gitignored and disposable; nothing there is source of truth
- A build command that hasn't been verified against a real clone must say so in a YAML comment (see `barebox.yaml`)
