from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from data_module.prospective_activation_environment import (
    CONTROLLED_HMAC_KEY_ENV_NAME,
    CONTROLLED_STORE_ID_ENV_NAME,
    FORMAL_PATH_ENV_NAMES,
)
from data_module.prospective_execution_plan import (
    ProspectiveExecutionPlanError,
    build_prospective_execution_plan,
    write_immutable_execution_plan,
)


def test_plan_is_fail_closed_and_contains_owner_actions() -> None:
    plan = build_prospective_execution_plan(
        now=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
        environment={},
        platform_name="posix",
    )
    assert plan["status"] == "waiting_for_owner_inputs"
    assert plan["current_blockers"]
    safety = cast(dict[str, object], plan["safety"])
    assert safety["read_only"] is True
    assert safety["formal_oos_allowed"] is False
    assert safety["heavy_rebuild_launch_allowed"] is False
    assert safety["secret_values_emitted"] is False
    assert len(cast(list[object], plan["stages"])) == 8
    assert len(cast(list[object], plan["next_actions"])) == 4


def test_plan_does_not_emit_hmac_secret(tmp_path: Path) -> None:
    paths = {name: tmp_path / f"{index}.json" for index, name in enumerate(FORMAL_PATH_ENV_NAMES)}
    for path in paths.values():
        path.write_text("fixture", encoding="utf-8")
    secret = "super-secret-value"
    environment = {name: str(path) for name, path in paths.items()}
    environment[CONTROLLED_STORE_ID_ENV_NAME] = "store:test"
    environment[CONTROLLED_HMAC_KEY_ENV_NAME] = secret
    plan = build_prospective_execution_plan(
        now=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
        environment=environment,
        platform_name="posix",
    )
    serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)
    assert secret not in serialized
    assert plan["status"] == "ready_for_owner_activation_handoff"
    assert plan["current_blockers"] == []


def test_plan_requires_timezone_aware_now() -> None:
    with pytest.raises(ProspectiveExecutionPlanError, match="timezone"):
        build_prospective_execution_plan(now=datetime(2026, 8, 15, 1, 0))


def test_plan_output_is_create_only(tmp_path: Path) -> None:
    plan = build_prospective_execution_plan(
        now=datetime(2026, 8, 15, 1, 0, tzinfo=timezone.utc),
        environment={},
        platform_name="posix",
    )
    output = tmp_path / "plan.json"
    assert write_immutable_execution_plan(output, plan).startswith("sha256:")
    with pytest.raises(ProspectiveExecutionPlanError, match="already exists"):
        write_immutable_execution_plan(output, plan)

