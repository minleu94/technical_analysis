from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from qa.full_app_healthcheck.candidate_bridge_policy import evaluate_candidate_bridge_policy
from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES, FeatureRoute
from qa.full_app_healthcheck.service_oracle_metadata import get_service_oracle_metadata
from qa.full_app_healthcheck.test_inventory import (
    get_all_test_files,
    get_category,
    get_candidate_bridge_files,
)


@dataclass(frozen=True)
class FeatureCoverageDetail:
    feature_id: str
    display_name: str
    has_ui_bridge: bool
    has_service_oracle: bool
    direct_bridge_suites: tuple[str, ...]
    service_oracles: tuple[str, ...]
    service_oracle_evidence_roles: tuple[str, ...]
    candidate_tests: tuple[str, ...]
    known_gaps: tuple[str, ...]
    status: str  # 'fully-ui-covered', 'oracle-only', 'gap'
    likely_owner: str


@dataclass(frozen=True)
class CoverageBurndownReport:
    features: tuple[FeatureCoverageDetail, ...]
    unmapped_service_oracles: tuple[str, ...]
    unmapped_candidate_tests: tuple[str, ...]
    total_features: int
    ui_covered_count: int
    oracle_only_count: int
    gap_count: int
    known_gap_count: int
    burndown_percentage: float
    candidate_work_items: tuple[str, ...]
    summary: str


def generate_coverage_burndown_report(
    feature_routes: dict[str, FeatureRoute] | None = None
) -> CoverageBurndownReport:
    """
    生成 Coverage Burn-down 報告。
    對照 feature routes / bridge policy / service oracle metadata。
    """
    routes = feature_routes if feature_routes is not None else FEATURE_ROUTES
    features: list[FeatureCoverageDetail] = []

    ui_covered_count = 0
    oracle_only_count = 0
    gap_count = 0
    known_gap_count = 0

    for route in routes.values():
        has_ui_bridge = len(route.direct_bridge_suite_ids) > 0
        has_service_oracle = len(route.service_oracle_test_paths) > 0
        known_gap_count += len(route.known_gaps)

        # 決定狀態：已可由 UI bridge 覆蓋，或是僅有 oracle, 或兩者都無
        if has_ui_bridge:
            status = 'fully-ui-covered'
            ui_covered_count += 1
        elif has_service_oracle:
            status = 'oracle-only'
            oracle_only_count += 1
        else:
            status = 'gap'
            gap_count += 1

        if route.feature_id == "update_view":
            likely_owner = "data_audit"
        else:
            likely_owner = "execution"

        service_oracle_evidence_roles = tuple(
            get_service_oracle_metadata(path, route.feature_id).evidence_role
            for path in route.service_oracle_test_paths
        )

        detail = FeatureCoverageDetail(
            feature_id=route.feature_id,
            display_name=route.display_name,
            has_ui_bridge=has_ui_bridge,
            has_service_oracle=has_service_oracle,
            direct_bridge_suites=route.direct_bridge_suite_ids,
            service_oracles=route.service_oracle_test_paths,
            service_oracle_evidence_roles=service_oracle_evidence_roles,
            candidate_tests=route.candidate_test_paths,
            known_gaps=route.known_gaps,
            status=status,
            likely_owner=likely_owner,
        )
        features.append(detail)

    # 2. 尋找未對映的測試
    mapped_oracles = set()
    for route in routes.values():
        mapped_oracles.update(route.service_oracle_test_paths)

    all_tests = get_all_test_files()
    unmapped_oracles_list: list[str] = []

    for path in sorted(all_tests):
        category = get_category(path)
        if category and category.startswith("service-oracle-"):
            if path not in mapped_oracles:
                unmapped_oracles_list.append(path)

    policy_report = evaluate_candidate_bridge_policy()
    unmapped_candidates_list = [
        item.path for item in policy_report.items
        if item.decision == "needs-feature-route"
    ]

    candidate_work_items = sorted(list(get_candidate_bridge_files()))

    total_features = len(features)
    if total_features > 0:
        burndown_percentage = ((ui_covered_count + oracle_only_count * 0.5) / total_features) * 100.0
    else:
        burndown_percentage = 0.0

    summary = (
        f"Analyzed {total_features} features: {ui_covered_count} UI covered, "
        f"{oracle_only_count} oracle only, {gap_count} gaps. "
        f"Burndown progress: {burndown_percentage:.1f}%. "
        f"Found {len(unmapped_oracles_list)} unmapped oracles, "
        f"{len(unmapped_candidates_list)} unmapped candidates, "
        f"{known_gap_count} known feature gaps."
    )

    return CoverageBurndownReport(
        features=tuple(features),
        unmapped_service_oracles=tuple(unmapped_oracles_list),
        unmapped_candidate_tests=tuple(unmapped_candidates_list),
        total_features=total_features,
        ui_covered_count=ui_covered_count,
        oracle_only_count=oracle_only_count,
        gap_count=gap_count,
        known_gap_count=known_gap_count,
        burndown_percentage=burndown_percentage,
        candidate_work_items=tuple(candidate_work_items),
        summary=summary,
    )


def render_coverage_burndown_markdown(report: CoverageBurndownReport) -> str:
    """
    將 CoverageBurndownReport 渲染為 Markdown 格式的報告。
    """
    lines = [
        "## Full App Healthcheck Coverage Burn-down Report",
        "",
        "> [!NOTE]",
        "> 本報告列出 Full App Healthcheck 的功能覆蓋進度與測試缺口 (Gaps)。",
        "> 目的在於推動測試從 `oracle-only` 逐步升級為 `ui-covered`，並清除現存缺口。",
        "",
        "### Progress Summary",
        f"- **Burndown Progress**: {report.burndown_percentage:.1f}%",
        f"- **Total Features**: {report.total_features}",
        f"- **UI Covered Features**: {report.ui_covered_count}",
        f"- **Oracle Only Features**: {report.oracle_only_count}",
        f"- **Gap Features**: {report.gap_count}",
        f"- **Known Manual / UX Gaps**: {report.known_gap_count}",
        "",
        "### 1. Feature Coverage Details",
        "",
        "| Feature | Display Name | Status | UI Bridges | Service Oracle Evidence | Candidate Tests | Known Gaps | Owner |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for f in report.features:
        ui_bridges = ", ".join(f"`{s}`" for s in f.direct_bridge_suites) or "none"
        oracle_items = [
            f"`{Path(path).name}`: {role}"
            for path, role in zip(f.service_oracles, f.service_oracle_evidence_roles, strict=True)
        ]
        oracles = "<br>".join(oracle_items) or "none"
        candidates = ", ".join(f"`{Path(p).name}`" for p in f.candidate_tests) or "none"
        known_gaps = "<br>".join(f.known_gaps) or "none"
        lines.append(
            f"| `{f.feature_id}` | {f.display_name} | `{f.status}` | {ui_bridges} | {oracles} | {candidates} | {known_gaps} | `{f.likely_owner}` |"
        )

    lines.append("")
    lines.append("### 2. Coverage Gaps & Unmapped Components")
    lines.append("")
    lines.append("#### 尚缺 Feature Route Mapping 的候選 UI 測試 (Gaps)")
    if report.unmapped_candidate_tests:
        for path in report.unmapped_candidate_tests:
            lines.append(f"- [ ] `{path}` (Needs Feature Route mapping to be promoted)")
    else:
        lines.append("- (None)")

    lines.append("")
    lines.append("#### 未被 Feature Route 包含的 Service Oracle 測試")
    if report.unmapped_service_oracles:
        for path in report.unmapped_service_oracles:
            lines.append(f"- [ ] `{path}` (Service oracle not associated with any high-level feature)")
    else:
        lines.append("- (None)")

    lines.append("")
    lines.append("### 3. Future Candidate Work Items (Candidate Bridge Tests)")
    if report.candidate_work_items:
        for path in report.candidate_work_items:
            lines.append(f"- [ ] `{path}`")
    else:
        lines.append("- (None)")

    return "\n".join(lines).rstrip()
