from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES, FeatureRoute
from qa.full_app_healthcheck.test_inventory import get_category


@dataclass(frozen=True)
class ServiceOracleMetadata:
    path: str
    feature_id: str
    oracle_category: str  # 'data/market', 'research/backtest', 'recommendation', 'portfolio/decision/runtime'
    evidence_role: str
    likely_owner: str
    risk_notes: str
    recommended_usage: str
    allowed_as_bridge_step: bool = False



@dataclass(frozen=True)
class ServiceOracleReport:
    items: tuple[ServiceOracleMetadata, ...]
    summary: str


# 針對 14 個特定 Service Oracle 測試的精確描述
ORACLE_DETAILS: dict[str, dict[str, str]] = {
    "tests/test_update_service_status.py": {
        "evidence_role": "data update and cache status evidence",
        "risk_notes": "Read-only checking, low risk. Involves TPEX daily price files check.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_decision_desk_dashboard_service.py": {
        "evidence_role": "decision desk dashboard service validation",
        "risk_notes": "Validates dashboard widgets and data aggregation; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_decision_desk_risk_prompt_service.py": {
        "evidence_role": "decision desk risk assessment model evidence",
        "risk_notes": "Validates risk prompt and warnings generation; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_decision_desk_service.py": {
        "evidence_role": "decision desk action rules and core logic validation",
        "risk_notes": "Validates decision desk action rule evaluation; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_decision_desk_ui_contract.py": {
        "evidence_role": "decision desk UI to model binding contract",
        "risk_notes": "Ensures view states bind to model outputs; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_research_lab_mode_taxonomy.py": {
        "evidence_role": "strategy mode classification taxonomy",
        "risk_notes": "Taxonomy consistency verification; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_research_result_presentation.py": {
        "evidence_role": "backtest result metric presentation formatting",
        "risk_notes": "Ensures charts and HTML/Markdown render safely; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_research_run_repository.py": {
        "evidence_role": "backtest run storage registry evidence",
        "risk_notes": "Validates storage adapters and metadata saving; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_research_run_service.py": {
        "evidence_role": "backtest run core engine logic validation",
        "risk_notes": "Runs lightweight simulations, moderate CPU usage.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_walkforward_service.py": {
        "evidence_role": "walkforward timeline regime and hysteresis model",
        "risk_notes": "Validates walk-forward window precomputation; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_smart_money_semantic_service.py": {
        "evidence_role": "smart money semantic DTO mapping and service verification",
        "risk_notes": "Evaluates transaction patterns, lightweight SQLite queries.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_broker_branch_decode.py": {
        "evidence_role": "broker branch transaction decoder rules",
        "risk_notes": "Validates decode logic for branch data; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_broker_flow_units.py": {
        "evidence_role": "broker flow metric and validation constraints",
        "risk_notes": "Validates units and bounds of broker flows; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    },
    "tests/test_research_run_comparison_service.py": {
        "evidence_role": "strategy cross-run parameter comparison contract",
        "risk_notes": "Validates strategy parameters comparison; low risk.",
        "recommended_usage": "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."
    }
}


def generate_service_oracle_report() -> ServiceOracleReport:
    """
    讀取 FEATURE_ROUTES 的 service_oracle_test_paths，
    對每個 service oracle test 產生 metadata，並包裝成 ServiceOracleReport。
    """
    items: list[ServiceOracleMetadata] = []

    # 為了使輸出排序穩定，我們先收集並排序路徑
    all_paths: list[tuple[str, str]] = []  # (path, feature_id)
    for route in FEATURE_ROUTES.values():
        for path in route.service_oracle_test_paths:
            all_paths.append((path, route.feature_id))

    # 按照 path 排序
    all_paths.sort(key=lambda x: x[0])

    for path, feature_id in all_paths:
        meta = get_service_oracle_metadata(path, feature_id)
        items.append(meta)

    summary = f"Total {len(items)} service oracle tests mapped to features."
    return ServiceOracleReport(items=tuple(items), summary=summary)


def get_service_oracle_metadata(path: str, feature_id: str | None = None) -> ServiceOracleMetadata:
    """
    獲取單個 service oracle test 的元資料。
    如果未傳入 feature_id，會主動從 FEATURE_ROUTES 中搜尋。
    """
    # 1. 尋找 feature_id
    if feature_id is None:
        for route in FEATURE_ROUTES.values():
            if path in route.service_oracle_test_paths:
                feature_id = route.feature_id
                break
        if feature_id is None:
            raise ValueError(f"Path '{path}' is not mapped to any feature in FEATURE_ROUTES.")

    # 2. 決定 oracle_category
    inv_category = get_category(path)
    if inv_category == "service-oracle-data-market":
        oracle_category = "data/market"
    elif inv_category == "service-oracle-research-backtest":
        oracle_category = "research/backtest"
    elif inv_category == "service-oracle-recommendation":
        oracle_category = "recommendation"
    elif inv_category == "service-oracle-portfolio-decision-runtime":
        oracle_category = "portfolio/decision/runtime"
    else:
        # Fallback for generic service oracle
        oracle_category = "unknown"

    # 3. 決定 likely_owner
    if oracle_category == "data/market":
        likely_owner = "data_audit"
    elif oracle_category == "research/backtest":
        likely_owner = "execution"
    elif oracle_category == "recommendation":
        likely_owner = "execution"
    elif oracle_category == "portfolio/decision/runtime":
        likely_owner = "execution"
    else:
        likely_owner = "testing_qa"

    # 4. 讀取特定細節，或使用預設值 fallback
    details = ORACLE_DETAILS.get(path)
    if details:
        evidence_role = details["evidence_role"]
        risk_notes = details["risk_notes"]
        recommended_usage = details["recommended_usage"]
    else:
        evidence_role = "Generic service oracle verification"
        risk_notes = "Unknown risk; default metadata assigned."
        recommended_usage = "Run as offline validation evidence in full mode; do not execute as step in direct runner bridge."

    return ServiceOracleMetadata(
        path=path,
        feature_id=feature_id,
        oracle_category=oracle_category,
        evidence_role=evidence_role,
        allowed_as_bridge_step=False,
        likely_owner=likely_owner,
        risk_notes=risk_notes,
        recommended_usage=recommended_usage,
    )


def render_service_oracle_metadata_markdown(report: ServiceOracleReport) -> str:
    """
    將 ServiceOracleReport 渲染為 Markdown 格式。
    特別標示 service oracle 是 evidence，不是 UI flow step。
    """
    lines = [
        "## Service Oracle Healthcheck Metadata",
        "",
        "> [!IMPORTANT]",
        "> **Service oracle 測試是證據（Evidence），不是 UI flow step！**",
        "> 所有 service oracle 測試皆不允許直接作為 runner bridge 步驟執行 (allowed_as_bridge_step 必須為 False)。",
        "",
        f"Summary: {report.summary}",
        "",
        "| Service Oracle Test | Feature ID | Category | Evidence Role | Allowed as Bridge Step | Owner | Risk Notes | Recommended Usage |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in report.items:
        allowed_str = "True" if item.allowed_as_bridge_step else "False"
        lines.append(
            f"| `{item.path}` | `{item.feature_id}` | `{item.oracle_category}` | {item.evidence_role} | `{allowed_str}` | `{item.likely_owner}` | {item.risk_notes} | {item.recommended_usage} |"
        )
    return "\n".join(lines).rstrip()
