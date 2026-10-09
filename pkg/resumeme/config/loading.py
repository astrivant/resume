"""
Load a strict configuration with paths anchored to its own directory.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

import cattrs
import yaml
from attrs import asdict, evolve
from jsonschema import Draft202012Validator, FormatChecker

from resumeme.compiler.asts.links import safe_url
from resumeme.compiler.constants.backend import AST_PACKAGE, CONFIG_SCHEMA
from resumeme.config.models import (
    Capture,
    Codex,
    CodexSkills,
    CompanyTarget,
    Config,
    Education,
    EducationSelector,
    Experience,
    GitHub,
    GitHubContributions,
    JobSelector,
    LinkedIn,
    LinkedInResume,
    Logging,
    Output,
    Ownership,
    Pages,
    Projects,
    ProjectSelector,
    Readme,
    Style,
    StyleOverrides,
)
from resumeme.exceptions import ConfigurationError

__all__ = [
    "Capture",
    "Codex",
    "CodexSkills",
    "CompanyTarget",
    "Config",
    "Education",
    "EducationSelector",
    "Experience",
    "GitHub",
    "GitHubContributions",
    "JobSelector",
    "LinkedIn",
    "LinkedInResume",
    "Logging",
    "Output",
    "Ownership",
    "Pages",
    "ProjectSelector",
    "Projects",
    "Readme",
    "Style",
    "StyleOverrides",
    "load_config",
    "company_config",
    "project_path",
]

_STYLE_WIDTH_ALIASES = {
    "text_wrap_width": "later_page_body_width",
    "profile_column_text_wrap_width": "first_page_body_width",
}


def project_path(root: Path, value: str) -> Path:
    """
    Resolve a repository path and reject escapes, including existing symlinks.

    Args:
        root (Path): Configuration directory.
        value (str): Relative input or output path.

    Returns:
        Path: Absolute path beneath the root.

    Raises:
        ConfigurationError: The path is absolute, points at the root, or escapes it.
    """

    # Resolve symlinks before checking containment; lexical '..' checks alone would allow existing links to escape.
    target = (root / value).resolve()

    if Path(value).is_absolute() or target == root.resolve() or not target.is_relative_to(root.resolve()):
        raise ConfigurationError(f"Expected a path within the configuration directory: {value}")

    return target


def load_config(path: Path) -> Config:
    """
    Safely load YAML, reject unknown fields, and validate configured paths.

    Args:
        path (Path): User-maintained configuration file.

    Returns:
        Config: Schema-validated configuration with defaults applied.

    Raises:
        jsonschema.ValidationError: A value is invalid or a field is unknown.
        ConfigurationError: A configured date window, identity, theme, or project path is inconsistent.
    """

    return _parse_config(yaml.safe_load(path.read_text(encoding="utf-8")), path, validate_companies=True)


def _override_value(value: object, target_type: type[object]) -> object:
    """
    Preserve schema-validated partial values without coercing nulls, booleans, or nested collections.

    Args:
        value (object): Validated override value.
        target_type (type[object]): cattrs target type for the open partial mapping.

    Returns:
        object: Independent copy retaining YAML value types.
    """
    return deepcopy(value)


def _merge_config(base: object, override: object) -> object:
    """
    Merge mappings recursively while replacing sequences and scalar values exactly.

    Args:
        base (object): Inherited structured configuration values.
        override (object): Validated partial configuration, including meaningful nulls and empty lists.

    Returns:
        object: Independent merged tree; neither input is mutated.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        result = deepcopy(base)

        for key, value in override.items():
            result[key] = _merge_config(base.get(key), value)

        return result

    return deepcopy(override)


def _normalize_style(raw: object, *, path: str = "document.style") -> object:
    """
    Translate legacy width names at the YAML boundary, including sparse theme overrides.

    Args:
        raw (object): Schema-validated style mapping or inline theme.
        path (str): Public configuration location for conflict diagnostics.

    Returns:
        object: Independent mapping using explicit first-page and later-page width names.

    Raises:
        ConfigurationError: Both spellings of one setting occur in the same mapping.
    """
    if not isinstance(raw, Mapping):
        return raw

    normalized = deepcopy(dict(raw))

    # Normalize before merging company overrides so old names still replace inherited canonical values.
    for legacy, canonical in _STYLE_WIDTH_ALIASES.items():
        if legacy not in normalized:
            continue

        if canonical in normalized:
            raise ConfigurationError(f"Use only {path}.{canonical}; do not also set {path}.{legacy}.")

        normalized[canonical] = normalized.pop(legacy)

    themes = normalized.get("themes")

    if isinstance(themes, Mapping):
        normalized["themes"] = {name: _normalize_style(theme, path=f"{path}.themes.{name}") for name, theme in themes.items()}

    return normalized


def _normalize_config(raw: object) -> object:
    """
    Translate the human-facing hierarchical schema into the immutable runtime model.

    Args:
        raw (object): YAML data using the current grouped layout or the legacy flat layout.

    Returns:
        object: A flat, backwards-compatible mapping for the existing typed model.

    Raises:
        ConfigurationError: A grouped path and its legacy equivalent are both supplied.
    """
    if not isinstance(raw, Mapping):
        return raw

    normalized = deepcopy(dict(raw))

    def assign(name: str, value: object) -> None:
        """
        Assign one migrated field without allowing two sources of truth.

        Args:
            name (str): Flat runtime field receiving the grouped value.
            value (object): Value translated from the grouped configuration.

        Returns:
            None: The enclosing normalizer is updated in place.

        Raises:
            ConfigurationError: The legacy field is already present.
        """
        if name in normalized:
            raise ConfigurationError(f"Use only one configuration path for {name}; do not mix grouped and legacy keys.")
        normalized[name] = value

    grouped_profile = normalized.pop("profile", None)
    grouped_document = normalized.pop("document", None)
    grouped_publishing = normalized.pop("publishing", None)
    grouped_automation = normalized.pop("automation", None)

    if isinstance(grouped_profile, Mapping):
        if "linkedin" in grouped_profile:
            linkedin = grouped_profile["linkedin"]
            if isinstance(linkedin, Mapping) and "username" in linkedin:
                assign("linkedin", {"username": linkedin["username"]})
            else:
                assign("linkedin", linkedin)

        if "github" in grouped_profile:
            assign("github", grouped_profile["github"])

        sections = grouped_profile.get("sections")

        if isinstance(sections, Mapping):
            if "order" in sections:
                assign("section_order", sections["order"])

            for name in ("experience", "education"):
                if name in sections:
                    assign(name, sections[name])

            if "projects" in sections:
                projects = sections["projects"]
                if isinstance(projects, Mapping):
                    projects = dict(projects)
                    if "source_url_filter" in projects:
                        assign("project_filter", projects.pop("source_url_filter"))
                assign("projects", projects)

    if isinstance(grouped_document, Mapping):
        for name in ("output", "style", "template", "appendices"):
            if name in grouped_document:
                assign(name, grouped_document[name])

    publishing_linkedin: dict[str, object] = {}

    if isinstance(grouped_publishing, Mapping):
        if "linkedin" in grouped_publishing:
            linked = grouped_publishing["linkedin"]
            if isinstance(linked, Mapping):
                publishing_linkedin.update(linked)
            else:
                publishing_linkedin = {"resume": linked}

        for name in ("readme", "pages"):
            if name in grouped_publishing:
                assign(name, grouped_publishing[name])

    if isinstance(grouped_profile, Mapping) and isinstance(grouped_profile.get("linkedin"), Mapping):
        profile_linkedin = grouped_profile["linkedin"]
        for name in ("resume", "ownership"):
            if name in profile_linkedin:
                publishing_linkedin[name] = profile_linkedin[name]

    if publishing_linkedin:
        normalized.setdefault("linkedin", {})

        if not isinstance(normalized["linkedin"], Mapping):
            raise ConfigurationError("The grouped LinkedIn settings require a mapping at profile.linkedin.")

        merged_linkedin = dict(normalized["linkedin"])
        merged_linkedin.update(publishing_linkedin)
        normalized["linkedin"] = merged_linkedin

    if isinstance(grouped_automation, Mapping):
        for name in ("codex", "awareness"):
            if name in grouped_automation:
                assign(name, grouped_automation[name])

    if "style" in normalized:
        normalized["style"] = _normalize_style(normalized["style"])

    return normalized


def company_config(config: Config, target: CompanyTarget, *, root: Path | None = None) -> Config:
    """
    Resolve a job's partial configuration and validate its isolated output contract.

    Args:
        config (Config): Generic configuration inherited by the target.
        target (CompanyTarget): Employer/job identity and partial overrides.
        root (Path | None): Configuration directory for path checks; None uses the working directory.

    Returns:
        Config: Validated settings with independent nested values and fixed single-origin PDF/cache destinations.

    Raises:
        jsonschema.ValidationError: Overrides contain unknown fields or invalid values.
        ConfigurationError: Merged settings have incompatible dates, themes, or paths.
    """
    schema = json.loads(files(AST_PACKAGE).joinpath(CONFIG_SCHEMA).read_text(encoding="utf-8"))
    # Keep the grouped override schema authoritative for its partial profile/document/automation maps.
    # The compatibility properties below resolve legacy `$ref` targets without reapplying the complete
    # top-level `profile` schema, whose required LinkedIn identity is intentionally global.
    compatibility_properties = {
        name: value for name, value in schema["properties"].items() if name not in {"profile", "document", "publishing", "automation"}
    }
    overrides_schema = {
        "$ref": "#/properties/codex/properties/companies/items/properties/overrides",
        "properties": compatibility_properties,
    }
    Draft202012Validator(overrides_schema, format_checker=FormatChecker()).validate(target.overrides)
    normalized_overrides = _normalize_config(target.overrides)

    # Each variant shares the capture but owns its output paths; nested targets must not recurse into another matrix.
    isolated = evolve(
        config,
        codex=evolve(config.codex, companies=[]),
        output=evolve(config.output, tex=f".cache/single-origin/{target.key}/tex/resume.tex", pdf=f"single-origin/{target.key}/resume.pdf"),
    )

    # Omit absent attrs fields, including sparse selector keys; explicit nulls in the partial mapping remain meaningful.
    # Normalize attrs tuples into JSON arrays before applying the same schema used for YAML inputs.
    inherited = asdict(isolated, filter=lambda attribute, value: value is not None)
    merged = _merge_config(json.loads(json.dumps(inherited)), normalized_overrides)
    return _parse_config(merged, (root or Path.cwd()) / "resumeme.config.yaml", validate_companies=False)


def _parse_config(raw: object, path: Path, *, validate_companies: bool) -> Config:
    """
    Validate complete base or merged configuration values using one schema and cross-field contract.

    Args:
        raw (object): Loaded YAML or merged structured configuration.
        path (Path): Config location anchoring relative paths.
        validate_companies (bool): Resolve each base target once; False validates an already isolated target.

    Returns:
        Config: Fully validated settings with defaults applied.

    Raises:
        jsonschema.ValidationError: A field or raw value violates the configuration schema.
        ConfigurationError: Settings conflict with each other or escape the configuration directory.
    """
    # Validate the public grouped layout before flattening it into the runtime model.
    schema = json.loads(files(AST_PACKAGE).joinpath(CONFIG_SCHEMA).read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(raw)
    raw = _normalize_config(raw)

    # Validate the normalized values again so legacy and grouped inputs share every runtime constraint.
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(raw)
    converter = cattrs.Converter(forbid_extra_keys=True)
    converter.register_structure_hook_func(lambda target_type: target_type is object, _override_value)
    config = converter.structure(raw, Config)

    if config.awareness.enabled and not config.awareness.allowed_actors:
        raise ConfigurationError("automation.awareness.enabled requires at least one allowed_actors login.")

    # Count bounds remain meaningful when values are supplied through partial company overrides too.
    sharding = config.capture.sharding

    if not sharding.minimum <= sharding.initial <= sharding.maximum:
        raise ConfigurationError("capture.sharding requires minimum <= initial <= maximum.")

    # A publish opt-in must have a corresponding proposal producer.
    if config.codex.skills.publish and not config.codex.skills.enabled:
        raise ConfigurationError("automation.codex.skills.publish requires automation.codex.skills.enabled.")

    # Validated ISO dates sort chronologically; reject reversed explicit bounds before any capture or rendering work.
    if config.experience.since and config.experience.as_of and config.experience.since > config.experience.as_of:
        raise ConfigurationError("profile.sections.experience.since must be on or before profile.sections.experience.as_of.")

    # Distinct URLs for the same LinkedIn job can differ only in tracking parameters; never let them overwrite one output.
    company_keys = [company.key for company in config.codex.companies]

    if len(company_keys) != len(set(company_keys)):
        raise ConfigurationError("automation.codex.companies must select distinct company/job pairs.")

    # Contribution ownership is explicit: never infer a GitHub account from the LinkedIn username or a repository owner.
    if config.github.contributions.enabled and config.github.username is None:
        raise ConfigurationError("Set profile.github.username before enabling profile.github.contributions.")

    # Reject selector typos even for validation-only commands; themes are user-defined, not a hard-coded registry.
    if config.style.theme is not None and config.style.theme not in config.style.themes:
        raise ConfigurationError(f"Unknown document.style.theme {config.style.theme!r}; define it under document.style.themes or use null.")

    # Validate paths and URL syntax without reading files or making requests during configuration loading.
    icons = [config.style.website_icon, *(theme.get("website_icon") for theme in config.style.themes.values())]

    for icon in icons:
        if icon is None:
            continue

        if urlsplit(icon).scheme in {"http", "https"}:
            try:
                valid = bool(safe_url(icon)) and urlsplit(icon).port in {None, 80, 443}
            except ValueError:
                valid = False

            if not valid:
                raise ConfigurationError("document.style.website_icon requires a public HTTP(S) image URL on a standard port.")
        else:
            project_path(path.resolve().parent, icon)

    # Inputs, templates, and outputs share one root but must never resolve to the same file or directory.
    paths = [config.output.profile, config.output.assets, config.output.tex, config.output.pdf, config.readme.output]
    paths.extend(f"single-origin/{key}/resume.pdf" for key in company_keys)

    if config.template:
        paths.append(config.template)

    resolved = [project_path(path.resolve().parent, value) for value in paths]

    if len(resolved) != len(set(resolved)):
        raise ConfigurationError("Input, output, and template paths must be distinct.")

    # Generated Markdown must not replace the configuration needed by the next publication.
    if project_path(path.resolve().parent, config.readme.output) == path.resolve():
        raise ConfigurationError("publishing.readme.output must not replace the configuration file.")

    # Fail invalid partials during ordinary config validation, before network acquisition or any target PDF can be replaced.
    if validate_companies:
        for target in config.codex.companies:
            company_config(config, target, root=path.resolve().parent)

    return config
