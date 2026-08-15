"""唯讀的 prospective formal simulation execution plan。

這個模組把 PFS-01～PFS-10 的 owner handoff 組成一份可執行、可稽核的
狀態摘要。它只讀受控 Windows 環境（或測試注入的 mapping），不自動挑選
activation trading day、不建立任何 formal artifact、不啟動 watcher／ML，
也不讀取或輸出 HMAC secret。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from data_module.prospective_activation_environment import (
    FORMAL_PATH_ENV_NAMES,
    CONTROLLED_HMAC_KEY_ENV_NAME,
    CONTROLLED_STORE_ID_ENV_NAME,
    build_prospective_activation_environment_preflight,
)
from data_module.prospective_formal_clock import canonical_json, file_sha256, payload_hash


PROSPECTIVE_EXECUTION_PLAN_SCHEMA_VERSION = "prospective-formal-execution-plan.v1"
_TAIPEI_CLOCK = "Asia/Taipei"


class ProspectiveExecutionPlanError(ValueError):
    """Execution plan input/output 不符合安全契約。"""


def build_prospective_execution_plan(
    *,
    now: datetime,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    registry: object | None = None,
) -> dict[str, object]:
    """建立目前 handoff 狀態與 owner 下一步。

    ``now`` 必須由呼叫端明確注入，避免 inspector 自己決定 formal clock。
    ``environment``／``registry`` 只供測試與受控 Windows reader 使用；本函式
    永遠只讀，不修改 process 或 registry。
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise ProspectiveExecutionPlanError("now must include timezone")
    preflight = build_prospective_activation_environment_preflight(
        environment=environment,
        platform_name=platform_name,
        registry=registry,
    )
    raw_blockers = preflight.get("blockers", [])
    if not isinstance(raw_blockers, Sequence) or isinstance(raw_blockers, (str, bytes)):
        raise ProspectiveExecutionPlanError("environment preflight blockers are invalid")
    blockers = [str(item) for item in raw_blockers]
    environment_ready = not blockers

    stages = [
        _stage(
            "controlled_environment",
            "ready_for_owner_activation" if environment_ready else "blocked",
            blockers,
            "三個 formal path、controlled store identity 與 HMAC secret store 必須先由 owner 在 Windows 受控環境配置。",
            [
                ".\\.venv\\Scripts\\python.exe scripts\\inspect_prospective_activation_environment.py",
            ],
        ),
        _stage(
            "clock_manifest",
            "owner_action_required",
            ["owner_must_supply_future_activation_trading_day"],
            "owner 提供仍在未來且經官方日曆證明的台灣交易日；repo 不自動挑日期、不回填過去日期。",
            [
                ".\\.venv\\Scripts\\python.exe scripts\\publish_prospective_formal_clock.py --fixture-only ...",
            ],
        ),
        _stage(
            "capture_readiness",
            "blocked_until_inputs_ready",
            ["clock_manifest_and_all_three_inputs_required"],
            "strict PFS-06 必須同時驗證 causal simulated ledger、Rule Champion history 與 PIT sidecar；若三項尚未存在，可先建立 deferred staging，但不會取得任何 formal credit。",
            [
                ".\\.venv\\Scripts\\python.exe scripts\\inspect_prospective_capture_readiness.py --fixture-only --defer-until-activation ...",
                ".\\.venv\\Scripts\\python.exe scripts\\inspect_prospective_capture_readiness.py --controlled-environment ...",
            ],
        ),
        _stage(
            "clock_activation",
            "blocked_until_readiness_ready",
            ["owner_activation_requires_ready_for_future_activation"],
            "strict activation 凍結 identity 與 path hashes；deferred activation 只凍結未來預約與 null paths；兩者都不等於 formal OOS permission，也不啟動重型 ML。",
            [
                ".\\.venv\\Scripts\\python.exe scripts\\activate_prospective_formal_clock.py --fixture-only --controlled-environment --defer-inputs ...",
                ".\\.venv\\Scripts\\python.exe scripts\\activate_prospective_formal_clock.py --fixture-only --controlled-environment ...",
            ],
        ),
        _stage(
            "daily_capture",
            "pending_activation",
            ["activation_manifest_required"],
            "啟動後每日依 PIT → Rule → T-1 transition → frozen inference → heartbeat 順序低 CPU 蒐證。",
            [
                ".\\.venv\\Scripts\\python.exe scripts\\record_prospective_daily_capture.py --fixture-only ...",
            ],
        ),
        _stage(
            "shadow_maturity",
            "pending_daily_evidence",
            ["at_least_20_natural_shadow_trading_days", "four_horizons_need_matured_outcomes"],
            "只計算啟動後自然經過的交易日；不得使用 research replay、Teacher target、補日或 synthetic outcome。",
            [
                ".\\.venv\\Scripts\\python.exe scripts\\inspect_prospective_shadow_maturity.py --fixture-only ...",
            ],
        ),
        _stage(
            "frozen_oos_and_calibration",
            "pending_maturity_and_evidence",
            ["maturity_report", "inference_level_calibration", "integer_bp_psi_report"],
            "frozen candidate OOS、calibration 與 PSI 必須使用已成熟、同一 identity 的 evidence；目前不改 current model。",
            [
                ".\\.venv\\Scripts\\python.exe scripts\\inspect_prospective_frozen_oos.py --fixture-only ...",
            ],
        ),
        _stage(
            "promotion_review",
            "blocked_fail_closed",
            ["owner_review", "calibration_quality", "class_coverage", "promotion_authority"],
            "即使前面資料完成，promotion 仍須通過 calibration、class 0/1 coverage、PSI、shadow maturity 與 owner authority。",
            [
                ".\\.venv\\Scripts\\python.exe scripts\\inspect_prospective_promotion_review.py --fixture-only ...",
            ],
        ),
    ]

    next_actions = [
        {
            "step": 1,
            "owner_action": "在 Windows 使用者環境／受控 secret store 確認 RULE_CHAMPION_CONTROLLED_STORE_ID 與 HMAC secret key；三個 formal input path 若尚未存在，可先走 deferred staging，strict readiness 前再補齊。",
            "required_environment_names": [
                *FORMAL_PATH_ENV_NAMES,
                CONTROLLED_STORE_ID_ENV_NAME,
                CONTROLLED_HMAC_KEY_ENV_NAME,
            ],
            "formal_path_requirement_before_activation": "optional_for_deferred_staging_required_for_strict_readiness",
            "secret_handling": "HMAC key 只設在受控環境；不要貼到對話、repo、命令列、status 或 log。",
            "repo_action": "inspect_only",
        },
        {
            "step": 2,
            "owner_action": "提供合法 PIT publication／license／source hash lineage 與 prospective rows；沒有授權來源時維持 blocked，不用 companies.csv、research output 或 2014 舊檔替代。",
            "repo_action": "owner_supplied_source_required",
        },
        {
            "step": 3,
            "owner_action": "選定未來台灣交易日並提供 clock、frozen candidate、calibration policy 與 symbols；日期由 owner 決定，repo 只驗證官方證據。",
            "repo_action": "publish_fixture_then_revalidate",
        },
        {
            "step": 4,
            "owner_action": "若三項輸入尚未 ready，先以 deferred readiness + --defer-inputs 預約未來 clock；第一個未來決策日後補齊三 path，再跑 strict readiness 與 activation。若三項已 ready，直接走 strict readiness → owner activation；不要啟動舊 watch-formal-inputs heavy rebuild。",
            "repo_action": "deferred_or_strict_readiness_then_activation",
        },
    ]

    body: dict[str, object] = {
        "schema_version": PROSPECTIVE_EXECUTION_PLAN_SCHEMA_VERSION,
        "status": "waiting_for_owner_inputs" if blockers else "ready_for_owner_activation_handoff",
        "mode": "prospective_formal_simulation",
        "generated_at": now.isoformat(),
        "decision_timezone": _TAIPEI_CLOCK,
        "environment_preflight": preflight,
        "current_blockers": sorted(set(blockers)),
        "stages": stages,
        "next_actions": next_actions,
        "safety": {
            "read_only": True,
            "activation_launch_allowed": False,
            "heavy_rebuild_launch_allowed": False,
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "promotion_eligible": False,
            "broker_order_allowed": False,
            "historical_backfill_claimed": False,
            "real_money": False,
            "broker_execution": False,
            "secret_values_emitted": False,
            "date_auto_selected": False,
        },
        "recommended_commands": [
            ".\\.venv\\Scripts\\python.exe scripts\\inspect_prospective_execution_plan.py --now <owner-supplied-ISO-timestamp>",
            ".\\.venv\\Scripts\\python.exe scripts\\inspect_runtime_process_custody.py --sample-seconds 1",
        ],
    }
    return {**body, "plan_hash": payload_hash(body)}


def write_immutable_execution_plan(output_path: Path, plan: Mapping[str, object]) -> str:
    """以 canonical JSON create-only 保存 plan；預設 CLI 不會寫檔。"""

    _validate_plan_hash(plan)
    output = output_path.expanduser().resolve()
    if not output.parent.exists():
        raise ProspectiveExecutionPlanError("plan output parent directory must exist")
    try:
        with output.open("xb") as stream:
            stream.write(canonical_json(dict(plan)).encode("utf-8"))
            stream.flush()
            import os

            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ProspectiveExecutionPlanError("plan output already exists") from error
    return file_sha256(output)


def _stage(
    name: str,
    status: str,
    blockers: list[str],
    purpose: str,
    commands: list[str],
) -> dict[str, object]:
    return {
        "stage": name,
        "status": status,
        "blockers": sorted(set(blockers)),
        "purpose": purpose,
        "commands": commands,
    }


def _validate_plan_hash(plan: Mapping[str, object]) -> None:
    if plan.get("schema_version") != PROSPECTIVE_EXECUTION_PLAN_SCHEMA_VERSION:
        raise ProspectiveExecutionPlanError("plan schema_version is invalid")
    supplied = plan.get("plan_hash")
    if not isinstance(supplied, str) or len(supplied) != 71 or not supplied.startswith("sha256:"):
        raise ProspectiveExecutionPlanError("plan_hash is invalid")
    body: dict[str, Any] = dict(plan)
    body.pop("plan_hash", None)
    if payload_hash(body) != supplied:
        raise ProspectiveExecutionPlanError("plan hash mismatch")
