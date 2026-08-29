class EmblabError(Exception):
    """Base class for all emblab errors."""


class ManifestError(EmblabError):
    """A YAML manifest is missing a required field, references an unknown
    entity, or violates a schema rule (e.g. a component referencing a sibling
    component in its own defaults)."""


class TemplateError(EmblabError):
    """A ``${...}`` token could not be resolved."""


class CycleError(EmblabError):
    """A target's stack has a dependency cycle between components."""


class BuildError(EmblabError):
    """A component build (inside its container) failed."""
