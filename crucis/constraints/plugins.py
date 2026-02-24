"""Custom constraint check plugin registry.

Users register project-specific checks via ``register_custom_check``.
Registered checks are executed by ``run_custom_checks`` when matching
config keys appear in a profile's ``custom_checks`` section.
"""

from __future__ import annotations

from typing import Any, Callable

PluginChecker = Callable[[str, Any, list[str], dict], None]

_PLUGIN_REGISTRY: dict[str, PluginChecker] = {}


def register_custom_check(name: str, fn: PluginChecker) -> None:
    """Register a custom constraint check function.

    Args:
        name: Unique name matching the key in the profile YAML ``custom_checks`` section.
        fn: Checker with signature ``(src, config, violations, metrics) -> None``.
    """
    if name in _PLUGIN_REGISTRY:
        raise ValueError(f"Custom check '{name}' is already registered")
    _PLUGIN_REGISTRY[name] = fn


def unregister_custom_check(name: str) -> None:
    """Remove a custom constraint check from the registry.

    Args:
        name: Name of the check to remove.  No-op if not registered.
    """
    _PLUGIN_REGISTRY.pop(name, None)


def clear_custom_checks() -> None:
    """Remove all registered custom checks."""
    _PLUGIN_REGISTRY.clear()


def run_custom_checks(
    source_code: str,
    custom_checks_config: dict[str, Any],
    violations: list[str],
    metrics: dict,
) -> None:
    """Run registered custom checks whose names appear in *custom_checks_config*.

    Args:
        source_code: Python source code to analyse.
        custom_checks_config: Mapping of check name to config value from YAML.
        violations: Violations list to append to (mutated).
        metrics: Metrics dict to update (mutated).
    """
    for name, config_value in custom_checks_config.items():
        fn = _PLUGIN_REGISTRY.get(name)
        if fn is None:
            continue
        fn(source_code, config_value, violations, metrics)


def get_registered_checks() -> dict[str, PluginChecker]:
    """Return a shallow copy of the current plugin registry.

    Returns:
        Dictionary mapping check names to checker functions.
    """
    return dict(_PLUGIN_REGISTRY)
