"""Read-only preflight for the owner-controlled prospective activation environment.

This module is the handoff between the completed PFS contracts and a future
owner activation.  It reads the existing Windows user/system environment via
the shared controlled-environment reader, never prints the HMAC secret, never
sets a variable, and never launches a watcher or ML process.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from data_module.prospective_formal_clock import canonical_json, file_sha256, payload_hash
from runtime.controlled_environment import (
    windows_effective_environment_value,
)


PROSPECTIVE_ACTIVATION_ENVIRONMENT_SCHEMA_VERSION = (
    "prospective-formal-activation-environment-preflight.v1"
)
FORMAL_PATH_ENV_NAMES = (
    "BALDR_ML_FORMAL_PORTFOLIO_LEDGER_PATH",
    "BALDR_ML_FORMAL_RULE_CHAMPION_HISTORY_PATH",
    "BALDR_ML_PIT_SECTOR_MEMBERSHIP_PATH",
)
CONTROLLED_STORE_ID_ENV_NAME = "RULE_CHAMPION_CONTROLLED_STORE_ID"
CONTROLLED_HMAC_KEY_ENV_NAME = "RULE_CHAMPION_CONTROLLED_STORE_HMAC_KEY"


class ProspectiveActivationEnvironmentError(ValueError):
    """Activation environment preflight contract error."""


def build_prospective_activation_environment_preflight(
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    registry: object | None = None,
) -> dict[str, object]:
    """建立安全的 environment preflight，不執行任何 side effect。"""

    effective_environment = os.environ if environment is None else environment
    platform = platform_name or os.name
    blockers: list[str] = []
    paths: dict[str, dict[str, object]] = {}
    for name in FORMAL_PATH_ENV_NAMES:
        value, source = _effective_value(
            name,
            environment=effective_environment,
            platform_name=platform,
            registry=registry,
        )
        if value is None:
            paths[name] = {
                "configured": False,
                "source": source,
                "path": None,
                "exists": False,
                "file_hash": None,
            }
            blockers.append(f"{name}:missing")
            continue
        path = Path(value).expanduser()
        resolved = path.resolve()
        exists = resolved.is_file()
        file_hash = file_sha256(resolved) if exists else None
        paths[name] = {
            "configured": True,
            "source": source,
            "path": str(resolved),
            "exists": exists,
            "file_hash": file_hash,
        }
        if not path.is_absolute():
            blockers.append(f"{name}:path_not_absolute")
        if not exists:
            blockers.append(f"{name}:file_missing")

    store_value, store_source = _effective_value(
        CONTROLLED_STORE_ID_ENV_NAME,
        environment=effective_environment,
        platform_name=platform,
        registry=registry,
    )
    hmac_value, hmac_source = _effective_value(
        CONTROLLED_HMAC_KEY_ENV_NAME,
        environment=effective_environment,
        platform_name=platform,
        registry=registry,
    )
    store_configured = store_value is not None
    hmac_configured = hmac_value is not None
    if not store_configured:
        blockers.append(f"{CONTROLLED_STORE_ID_ENV_NAME}:missing")
    if not hmac_configured:
        blockers.append(f"{CONTROLLED_HMAC_KEY_ENV_NAME}:missing")
    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_ACTIVATION_ENVIRONMENT_SCHEMA_VERSION,
        "status": "ready_for_owner_activation" if not blockers else "waiting_for_controlled_environment",
        "platform": platform,
        "formal_paths": paths,
        "controlled_store": {
            "name": CONTROLLED_STORE_ID_ENV_NAME,
            "configured": store_configured,
            "source": store_source,
            "identity_hash": payload_hash({"value": store_value}) if store_value else None,
        },
        "hmac_secret_store": {
            "name": CONTROLLED_HMAC_KEY_ENV_NAME,
            "configured": hmac_configured,
            "source": hmac_source,
            "secret_emitted": False,
        },
        "blockers": sorted(set(blockers)),
        "activation_launch_allowed": False,
        "heavy_rebuild_launch_allowed": False,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
        "promotion_eligible": False,
        "broker_order_allowed": False,
        "secret_values_emitted": False,
    }
    return {**body, "preflight_hash": payload_hash(body)}


def write_immutable_activation_environment_preflight(
    output_path: Path,
    report: Mapping[str, object],
) -> str:
    """以 canonical JSON create-only 保存 preflight。"""

    _validate_hash_shape(report)
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveActivationEnvironmentError("preflight output parent must exist")
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(report)).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveActivationEnvironmentError("preflight output already exists") from error
    return file_sha256(output)


def _effective_value(
    name: str,
    *,
    environment: Mapping[str, str],
    platform_name: str,
    registry: object | None,
) -> tuple[str | None, str]:
    registry_value = windows_effective_environment_value(
        name,
        platform_name=platform_name,
        registry=registry,
    )
    if registry_value is not None:
        return registry_value, "windows_user_or_system_registry"
    value = environment.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip(), "process_environment"
    return None, "unset"


def _validate_hash_shape(report: Mapping[str, object]) -> None:
    if report.get("schema_version") != PROSPECTIVE_ACTIVATION_ENVIRONMENT_SCHEMA_VERSION:
        raise ProspectiveActivationEnvironmentError("preflight schema_version is invalid")
    supplied = report.get("preflight_hash")
    if not isinstance(supplied, str) or len(supplied) != 71 or not supplied.startswith("sha256:"):
        raise ProspectiveActivationEnvironmentError("preflight_hash is invalid")
    body = dict(report)
    body.pop("preflight_hash", None)
    if payload_hash(body) != supplied:
        raise ProspectiveActivationEnvironmentError("preflight hash mismatch")
