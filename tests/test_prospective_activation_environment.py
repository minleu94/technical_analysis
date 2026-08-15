from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from data_module.prospective_activation_environment import (
    FORMAL_PATH_ENV_NAMES,
    CONTROLLED_HMAC_KEY_ENV_NAME,
    CONTROLLED_STORE_ID_ENV_NAME,
    ProspectiveActivationEnvironmentError,
    build_prospective_activation_environment_preflight,
    write_immutable_activation_environment_preflight,
)


def _environment(paths: dict[str, Path], *, hmac: str | None = None) -> dict[str, str]:
    values = {name: str(paths[name]) for name in FORMAL_PATH_ENV_NAMES}
    values[CONTROLLED_STORE_ID_ENV_NAME] = "controlled-store:test"
    if hmac is not None:
        values[CONTROLLED_HMAC_KEY_ENV_NAME] = hmac
    return values


def test_missing_environment_is_waiting_and_fail_closed() -> None:
    report = build_prospective_activation_environment_preflight(
        environment={},
        platform_name="posix",
    )
    assert report["status"] == "waiting_for_controlled_environment"
    assert report["activation_launch_allowed"] is False
    assert report["heavy_rebuild_launch_allowed"] is False
    assert report["formal_oos_allowed"] is False
    assert report["secret_values_emitted"] is False
    assert len(cast(list[object], report["blockers"])) == 5


def test_complete_environment_is_ready_only_for_owner_activation(tmp_path: Path) -> None:
    paths = {name: tmp_path / f"{index}.json" for index, name in enumerate(FORMAL_PATH_ENV_NAMES)}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")
    secret = "x" * 64
    report = build_prospective_activation_environment_preflight(
        environment=_environment(paths, hmac=secret),
        platform_name="posix",
    )
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert report["status"] == "ready_for_owner_activation"
    assert report["blockers"] == []
    assert report["activation_launch_allowed"] is False
    assert report["formal_oos_allowed"] is False
    assert secret not in serialized
    store = report["controlled_store"]
    assert isinstance(store, dict)
    assert store["configured"] is True
    hmac_store = report["hmac_secret_store"]
    assert isinstance(hmac_store, dict)
    assert hmac_store["configured"] is True
    assert hmac_store["secret_emitted"] is False


def test_relative_or_missing_path_is_blocked(tmp_path: Path) -> None:
    paths = {name: tmp_path / f"{index}.json" for index, name in enumerate(FORMAL_PATH_ENV_NAMES)}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")
    values = _environment(paths, hmac="x" * 32)
    values[FORMAL_PATH_ENV_NAMES[0]] = "relative-manifest.json"
    report = build_prospective_activation_environment_preflight(
        environment=values,
        platform_name="posix",
    )
    blockers = cast(list[object], report["blockers"])
    assert f"{FORMAL_PATH_ENV_NAMES[0]}:path_not_absolute" in blockers
    assert f"{FORMAL_PATH_ENV_NAMES[0]}:file_missing" in blockers


def test_preflight_report_is_create_only(tmp_path: Path) -> None:
    report = build_prospective_activation_environment_preflight(
        environment={},
        platform_name="posix",
    )
    output = tmp_path / "preflight.json"
    assert write_immutable_activation_environment_preflight(output, report).startswith("sha256:")
    with pytest.raises(ProspectiveActivationEnvironmentError, match="already exists"):
        write_immutable_activation_environment_preflight(output, report)
