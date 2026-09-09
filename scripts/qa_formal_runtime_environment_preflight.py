"""Validate one-time Formal/Paper runtime environment pins.

This is a read-only process-boundary check.  It does not discover a latest
candidate, change a persistent environment, write scheduler state, or write
any source/output database.  ``FORMAL_DAILY_RUNTIME_CONFIG_ROOT`` is resolved
to the exact Taipei natural-date filename by ``load_optional_formal_runtime_config``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_runtime_config import (  # noqa: E402
    FORMAL_RUNTIME_CONFIG_ENV,
    RUNTIME_CONFIG_ROOT_ENV,
    FormalRuntimeConfigError,
    load_formal_runtime_config,
    load_optional_formal_runtime_config,
    load_runtime_environment_binding,
)


ROLES = (
    "rule_source_wrapper",
    "pit_preopen_wrapper",
    "pit_sidecar_wrapper",
    "formal_input_wrapper",
    "paper_eod_wrapper",
)


def _required_path(name: str) -> Path:
    value = os.environ.get(name)
    if not isinstance(value, str) or not value.strip():
        raise FormalRuntimeConfigError(f"{name}_missing")
    return Path(value.strip()).expanduser().resolve()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FormalRuntimeConfigError(f"{field}_must_be_object")
    return value


def run_preflight(*, load_binding: bool = True) -> dict[str, object]:
    """Return a secret-free readback of the current environment contract.

    The normal CLI loads the installed binding.  The deployment writer uses
    ``load_binding=False`` after setting the target map in its own process so
    an existing binding cannot overwrite the candidate being preflighted
    before the create-only handoff.
    """

    binding_path = load_runtime_environment_binding() if load_binding else None
    root = _required_path(RUNTIME_CONFIG_ROOT_ENV)
    explicit = _required_path(FORMAL_RUNTIME_CONFIG_ENV)
    if not root.is_dir():
        raise FormalRuntimeConfigError(f"runtime_config_root_missing:{root}")
    if not explicit.is_file():
        raise FormalRuntimeConfigError(f"runtime_config_explicit_path_missing:{explicit}")
    try:
        explicit.relative_to(root)
    except ValueError as error:
        raise FormalRuntimeConfigError(
            "runtime_config_explicit_path_outside_root"
        ) from error

    observed = datetime.now(timezone.utc)
    projections: dict[str, dict[str, object]] = {}
    for role in ROLES:
        if load_binding:
            projection = load_optional_formal_runtime_config(
                role=role,
                observed=observed,
            )
        else:
            projection = load_formal_runtime_config(
                explicit,
                role=role,
                observed=observed,
            )
        if projection is None:
            raise FormalRuntimeConfigError(f"{role}_runtime_config_not_bound")
        role_contract = _mapping(projection.get("role_contract"), "role_contract")
        checked = role_contract.get("environment_values_checked")
        if not isinstance(checked, list) or any(
            not isinstance(item, str) for item in checked
        ):
            raise FormalRuntimeConfigError(
                f"{role}_environment_values_checked_invalid"
            )
        projections[role] = {
            "activation_status": projection.get("activation_status"),
            "activation_trading_day": projection.get("activation_trading_day"),
            "candidate_only": projection.get("candidate_only"),
            "formal_oos_allowed": projection.get("formal_oos_allowed"),
            "path": projection.get("path"),
            "file_hash": projection.get("file_hash"),
            "environment_values_checked": [str(item) for item in checked],
        }

    selected_runtime = _required_path(FORMAL_RUNTIME_CONFIG_ENV)
    try:
        selected_runtime.relative_to(root)
    except ValueError as error:
        raise FormalRuntimeConfigError(
            "runtime_config_selected_path_outside_root"
        ) from error
    return {
        "schema_version": "formal-runtime-environment-preflight.v1",
        "observed_at": observed.isoformat(timespec="microseconds"),
        "runtime_config_root": str(root),
        "runtime_config_before_or_selected_path": str(selected_runtime),
        "binding_path": str(binding_path) if binding_path is not None else None,
        "roles": projections,
        "all_five_roles_verified": len(projections) == len(ROLES)
        and all(
            value["candidate_only"] is True
            and value["formal_oos_allowed"] is False
            for value in projections.values()
        ),
        "source_pins_present": all(
            bool(os.environ.get(name, "").strip())
            for name in (
                "FORMAL_DAILY_ROLLING_CALENDAR_BUNDLE",
                "FORMAL_DAILY_PORTFOLIO_CLOCK_MANIFEST",
            )
        ),
        "persistent_environment_written": False,
        "scheduler_written": False,
        "market_database_written": False,
        "candidate_only": True,
    }


def main() -> int:
    try:
        payload = run_preflight()
    except Exception as error:  # noqa: BLE001 - CLI status boundary
        payload = {
            "schema_version": "formal-runtime-environment-preflight.v1",
            "status": "blocked",
            "blockers": [
                f"formal_runtime_environment_preflight_failed:{type(error).__name__}:{str(error).splitlines()[0][:240]}"
            ],
            "persistent_environment_written": False,
            "scheduler_written": False,
            "market_database_written": False,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2
    payload["status"] = "verified"
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())


__all__ = ["ROLES", "run_preflight", "main"]
