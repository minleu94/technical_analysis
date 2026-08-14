"""Shared fail-closed reader for controlled Windows environment values.

The long-lived ML maintainer and standalone readiness checks can be started
with different inherited environment blocks.  This module keeps their Windows
registry handoff semantics identical while only changing the current process
environment.  It never persists, prints, or returns values in an artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
import os
from typing import Any

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows runtime
    winreg = None  # type: ignore[assignment]


CONTROLLED_RUNTIME_ENVIRONMENT_NAMES = (
    "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
    "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
    "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
    "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY",
    "RULE_CHAMPION_CONTROLLED_STORE_ID",
)


def windows_effective_environment_value(
    name: str,
    *,
    platform_name: str | None = None,
    registry: Any | None = None,
) -> str | None:
    """Return a non-empty user/system registry value without logging it."""

    if (platform_name or os.name) != "nt":
        return None
    registry_module = winreg if registry is None else registry
    if registry_module is None:
        return None
    roots = (
        (registry_module.HKEY_CURRENT_USER, r"Environment"),
        (
            registry_module.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    )
    for hive, subkey in roots:
        try:
            with registry_module.OpenKey(hive, subkey) as key:
                value, value_type = registry_module.QueryValueEx(key, name)
        except OSError:
            continue
        if not isinstance(value, str):
            continue
        if value_type == getattr(registry_module, "REG_EXPAND_SZ", object()):
            try:
                value = registry_module.ExpandEnvironmentStrings(value)
            except OSError:
                continue
        value = value.strip()
        if value:
            return value
    return None


def refresh_controlled_runtime_environment(
    *,
    environment: MutableMapping[str, str],
    initial_environment: Mapping[str, str | None],
    adopted_environment: MutableMapping[str, str],
    names: Sequence[str] = CONTROLLED_RUNTIME_ENVIRONMENT_NAMES,
    platform_name: str | None = None,
    registry: Any | None = None,
) -> tuple[str, ...]:
    """Adopt changed registry values into one process and report names only.

    ``initial_environment`` and ``adopted_environment`` are supplied by the
    caller so a long-lived watcher can retain its custody state while a short
    readiness process can use the same rules without sharing state.  A value
    that was adopted by this function is removed if its registry source is
    removed; unrelated process-supplied values remain untouched.
    """

    if (platform_name or os.name) != "nt":
        return ()
    changed: list[str] = []
    for name in names:
        registry_value = windows_effective_environment_value(
            name,
            platform_name=platform_name,
            registry=registry,
        )
        current_value = environment.get(name)
        adopted_value = adopted_environment.get(name)
        if registry_value is None:
            if adopted_value is not None:
                if current_value == adopted_value:
                    environment.pop(name, None)
                    changed.append(name)
                adopted_environment.pop(name, None)
            continue

        initial_value = initial_environment.get(name)
        should_adopt = (
            current_value is None
            or (adopted_value is not None and current_value == adopted_value)
            or registry_value != initial_value
        )
        if not should_adopt:
            continue
        if current_value != registry_value:
            environment[name] = registry_value
        if adopted_value != registry_value:
            changed.append(name)
        adopted_environment[name] = registry_value
    return tuple(changed)
