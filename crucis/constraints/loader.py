"""Load and resolve constraint profiles for objective and task scopes."""

from pathlib import Path

import yaml

from crucis.constraints.registry import SOFT_CONSTRAINT_FIELDS
from crucis.defaults import TEXT_ENCODING
from crucis.models import ConstraintSet, ParsedObjective, TaskConstraints

_TASKS_KEY = "tasks"
_GUIDANCE_KEY = "guidance"
_CUSTOM_CHECKS_KEY = "custom_checks"
_SCOPE_TESTS = "tests"
_PRIMARY_KEY = "primary"
_SECONDARY_KEY = "secondary"

_CONSTRAINT_FIELDS: frozenset[str] = frozenset(ConstraintSet.model_fields)


def _normalize_profile_data(data: dict) -> dict:
    """Split flat constraint fields into primary/secondary using the registry.

    If data already contains ``primary`` or ``secondary`` keys the old nested
    format is assumed and passed through unchanged.  Otherwise each field is
    classified as required (primary) or advisory (secondary) based on
    :data:`SOFT_CONSTRAINT_FIELDS`.

    Args:
        data: Profile-level or task-override constraint dict.

    Returns:
        Dict with ``primary`` and ``secondary`` sub-dicts plus any pass-through keys.
    """
    if _PRIMARY_KEY in data or _SECONDARY_KEY in data:
        return data

    primary: dict = {}
    secondary: dict = {}
    rest: dict = {}
    for key, value in data.items():
        if key in SOFT_CONSTRAINT_FIELDS:
            secondary[key] = value
        elif key in _CONSTRAINT_FIELDS:
            primary[key] = value
        else:
            rest[key] = value
    return {_PRIMARY_KEY: primary, _SECONDARY_KEY: secondary, **rest}


def load_profiles(profiles_path: Path) -> dict:
    """Load a profile YAML file into a flattened dictionary.

    Args:
        profiles_path: Path to the constraint profiles YAML file.

    Returns:
        Dictionary containing structured result data.
    """
    try:
        raw = profiles_path.read_text(encoding=TEXT_ENCODING)
    except FileNotFoundError:
        from crucis.intake.scaffold import _DEFAULT_PROFILES

        data = _DEFAULT_PROFILES
        profiles = dict(data.get("profiles", {}))
        profiles[_TASKS_KEY] = data.get(_TASKS_KEY, {})
        return profiles
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML in {profiles_path}: {exc}") from None
    if not data:
        raise ValueError("Profiles file is empty")

    profiles = dict(data.get("profiles", {}))
    profiles[_TASKS_KEY] = data.get(_TASKS_KEY, {})
    return profiles


def extract_custom_checks(
    objective: ParsedObjective,
    profiles: dict,
    task_name: str | None = None,
    scope: str = _SCOPE_TESTS,
) -> dict | None:
    """Extract the ``custom_checks`` section for the resolved profile.

    Uses the same profile-name resolution as :func:`resolve_constraints`.

    Args:
        objective: Parsed objective data for the current run.
        profiles: Loaded profiles dictionary (from :func:`load_profiles`).
        task_name: Task name within the objective.
        scope: Constraint scope — ``"tests"`` or ``"implementation"``.

    Returns:
        Dict with ``"primary"`` and/or ``"secondary"`` sub-dicts, or *None*
        when the profile has no ``custom_checks`` section.
    """
    profile_name = _select_profile_name(objective, task_name, scope)
    profile_data = profiles.get(profile_name)
    if profile_data is None:
        return None
    custom = profile_data.get(_CUSTOM_CHECKS_KEY)
    if not custom:
        return None
    return dict(custom)


def resolve_constraints(
    objective: ParsedObjective,
    profiles: dict,
    task_name: str | None = None,
    scope: str = _SCOPE_TESTS,
) -> TaskConstraints:
    """Resolve constraints from objective + profile config.

    Args:
        objective: Parsed objective data for the current run.
        profiles: Value for `profiles` used by `resolve_constraints`.
        task_name: Task name within the objective.
        scope: Constraint scope — ``"tests"`` or ``"implementation"``.

    Returns:
        Computed text result for this operation.
    """
    profile_name = _select_profile_name(objective, task_name, scope)
    profile_data = profiles.get(profile_name)
    if profile_data is None:
        available = sorted(k for k in profiles if k != _TASKS_KEY)
        raise ValueError(
            f"Unknown constraint profile: '{profile_name}'. "
            f"Available: {', '.join(available) or '(none)'}"
        )

    normalized = _normalize_profile_data(profile_data)
    base_constraints = TaskConstraints(
        primary=ConstraintSet(**normalized.get(_PRIMARY_KEY, {})),
        secondary=ConstraintSet(**normalized.get(_SECONDARY_KEY, {})),
        target_files=_resolve_target_files(objective, task_name),
        guidance=list(normalized.get(_GUIDANCE_KEY) or []),
    )

    resolved_task = task_name or objective.name
    task_overrides = profiles.get(_TASKS_KEY, {}).get(resolved_task)
    if not task_overrides:
        return base_constraints
    return _merge_task_overrides(base_constraints, _normalize_profile_data(task_overrides))


def _select_profile_name(
    objective: ParsedObjective,
    task_name: str | None,
    scope: str = _SCOPE_TESTS,
) -> str:
    """Select the profile name for the given scope.

    Args:
        objective: Parsed objective data for the current run.
        task_name: Task name within the objective.
        scope: Constraint scope — ``"tests"`` or ``"implementation"``.

    Returns:
        Profile name string to look up in profiles dict.
    """
    if scope == "implementation":
        obj_default = objective.implementation_constraint_profile
        task_field = "implementation_constraint_profile"
    else:
        obj_default = objective.tests_constraint_profile
        task_field = "tests_constraint_profile"

    if task_name is None:
        return obj_default

    for task in objective.tasks:
        if task.name == task_name:
            value = getattr(task, task_field, None)
            if value:
                return value
    return obj_default


def _resolve_target_files(
    objective: ParsedObjective,
    task_name: str | None,
) -> list[str]:
    """resolve target files.

    Args:
        objective: Parsed objective data for the current run.
        task_name: Task name within the objective.

    Returns:
        Computed text result for this operation.
    """
    if task_name is None:
        return list(objective.target_files)

    for task in objective.tasks:
        if task.name != task_name:
            continue
        if task.target_files:
            return list(task.target_files)
        return list(objective.target_files)
    return list(objective.target_files)


def _merge_task_overrides(constraints: TaskConstraints, overrides: dict) -> TaskConstraints:
    """merge task overrides.

    Args:
        constraints: Resolved constraints for the current task or objective.
        overrides: Value for `overrides` used by `_merge_task_overrides`.

    Returns:
        Computed text result for this operation.
    """
    primary_data = constraints.primary.model_dump()
    primary_data.update(overrides.get(_PRIMARY_KEY, {}))

    secondary_data = constraints.secondary.model_dump()
    secondary_data.update(overrides.get(_SECONDARY_KEY, {}))

    guidance = list(constraints.guidance)
    if _GUIDANCE_KEY in overrides:
        guidance = list(overrides.get(_GUIDANCE_KEY) or [])

    return TaskConstraints(
        primary=ConstraintSet(**primary_data),
        secondary=ConstraintSet(**secondary_data),
        target_files=list(constraints.target_files),
        guidance=guidance,
    )
