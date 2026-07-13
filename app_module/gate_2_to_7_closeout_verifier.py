"""Evidence-backed Gate 2-7 engineering package closeout verifier."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class CloseoutRequirement:
    package_id: str
    artifact_path: str
    commit_subject: str


DEFAULT_REQUIREMENTS = (
    CloseoutRequirement("evidence_v3", "app_module/evidence_metric_applicability.py", "feat(evidence): classify metric applicability by event family"),
    CloseoutRequirement("evidence_v3", "app_module/event_price_resolver.py", "fix(evidence): resolve causal event-price trading date"),
    CloseoutRequirement("evidence_v3", "app_module/outcome_maturity_service.py", "feat(evidence): expose expected outcome maturity dates"),
    CloseoutRequirement("evidence_v3", "app_module/v3_effectiveness_metrics.py", "feat(v3): add decision-ready effectiveness metrics"),
    CloseoutRequirement("evidence_v3", "app_module/v3_pruning_decision_service.py", "feat(v3): build structured pruning decision package"),
    CloseoutRequirement("p0_sources", "data_module/p0_source_contract_registry.py", "feat(data): add versioned P0 source contract registry"),
    CloseoutRequirement("p0_sources", "data_module/p0_corporate_restriction_shadow_adapters.py", "feat(data): add corporate-action and restriction shadow adapters"),
    CloseoutRequirement("p0_sources", "data_module/p0_institutional_flow_shadow_adapter.py", "feat(data): add institutional-flow shadow adapters"),
    CloseoutRequirement("p0_sources", "data_module/p0_credit_transaction_shadow_adapter.py", "feat(data): add credit-transaction shadow adapters"),
    CloseoutRequirement("p0_sources", "data_module/p0_tdcc_distribution_shadow_adapter.py", "feat(data): add TDCC distribution shadow adapter"),
    CloseoutRequirement("p0_sources", "data_module/p0_pit_fundamental_announcement_adapters.py", "feat(data): add PIT revenue and financial announcement adapters"),
    CloseoutRequirement("p0_sources", "data_module/p0_source_acceptance_verifier.py", "feat(data): add source acceptance verifier"),
    CloseoutRequirement("paper_portfolio", "app_module/paper_portfolio_snapshot_repository.py", "feat(paper): add append-only snapshot repository"),
    CloseoutRequirement("paper_portfolio", "app_module/paper_portfolio_daily_runner.py", "feat(paper): add daily mark-to-market runner"),
    CloseoutRequirement("paper_portfolio", "app_module/paper_portfolio_rebalance_evaluator.py", "feat(paper): add governed rebalance evaluator"),
    CloseoutRequirement("paper_portfolio", "app_module/paper_equal_weight_benchmark_ledger.py", "feat(paper): add equal-weight benchmark ledger"),
    CloseoutRequirement("paper_portfolio", "app_module/paper_portfolio_weekly_report.py", "feat(paper): add weekly cost-adjusted report"),
    CloseoutRequirement("position_health", "app_module/position_thesis_contract.py", "feat(health): add thesis and invalidation contract"),
    CloseoutRequirement("position_health", "app_module/position_health_state_machine.py", "feat(health): add governed position state machine"),
    CloseoutRequirement("position_health", "app_module/position_health_transition_repository.py", "feat(health): add append-only transition repository"),
    CloseoutRequirement("position_health", "app_module/exit_effectiveness_read_model.py", "feat(health): add exit effectiveness read model"),
    CloseoutRequirement("ml_shadow", "ml_module/dataset_manifest.py", "feat(ml): add frozen dataset manifest and registry"),
    CloseoutRequirement("ml_shadow", "ml_module/available_date_boundary.py", "feat(ml): enforce feature-label available-date boundary"),
    CloseoutRequirement("ml_shadow", "ml_module/purged_walk_forward.py", "feat(ml): add purged walk-forward splitter"),
    CloseoutRequirement("ml_shadow", "ml_module/boosted_challengers.py", "feat(ml): add boosted ranking and downside challengers"),
    CloseoutRequirement("ml_shadow", "ml_module/probability_calibration.py", "feat(ml): add probability calibration"),
    CloseoutRequirement("ml_shadow", "ml_module/model_prediction_registries.py", "feat(ml): add model and shadow prediction registries"),
    CloseoutRequirement("ml_shadow", "ml_module/drift_champion_comparison.py", "feat(ml): add drift and champion comparison"),
    CloseoutRequirement("ml_shadow", "ml_module/promotion_review_package.py", "feat(ml): add rollback and promotion-review package"),
    CloseoutRequirement("ml_shadow", "ml_module/shadow_boundary_guard.py", "test(ml): enforce shadow-only dependency boundary"),
    CloseoutRequirement("control_center", "app_module/engineering_gate_registry.py", "feat(governance): add human and time gate registry"),
    CloseoutRequirement("control_center", "app_module/ml_revalidation_runbook_service.py", "feat(governance): add ML revalidation runbook service"),
    CloseoutRequirement("control_center", "app_module/gate_2_to_7_closeout_verifier.py", "feat(governance): add Gate 2-7 closeout verifier"),
    CloseoutRequirement("control_center", "app_module/engineering_closure_dashboard_service.py", "feat(workbench): add read-only engineering closure dashboard"),
    CloseoutRequirement("control_center", "docs/00_core/PRODUCT_ROADMAP_POST_REFACTOR.md", "docs(roadmap): close Gate 2-7 engineering program"),
)


@dataclass(frozen=True)
class Gate2To7CloseoutReport:
    engineering_package_status: str
    external_validation_status: str
    requirement_count: int
    satisfied_count: int
    blockers: tuple[str, ...]
    external_gate_statuses: tuple[str, ...]
    formal_product_closeout: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "engineering_package_status": self.engineering_package_status,
            "external_validation_status": self.external_validation_status,
            "requirement_count": self.requirement_count,
            "satisfied_count": self.satisfied_count,
            "blockers": list(self.blockers),
            "external_gate_statuses": list(self.external_gate_statuses),
            "formal_product_closeout": self.formal_product_closeout,
        }


class Gate2To7CloseoutVerifier:
    def __init__(
        self, root: str | Path, *, requirements: tuple[CloseoutRequirement, ...] = DEFAULT_REQUIREMENTS
    ) -> None:
        self.root = Path(root)
        self.requirements = requirements

    def verify(
        self,
        *,
        commit_subjects: Iterable[str],
        external_gate_statuses: Iterable[str],
    ) -> Gate2To7CloseoutReport:
        commits = set(commit_subjects)
        blockers: list[str] = []
        satisfied = 0
        for requirement in self.requirements:
            artifact_ok = (self.root / requirement.artifact_path).is_file()
            commit_ok = requirement.commit_subject in commits
            if not artifact_ok:
                blockers.append(
                    f"missing_artifact:{requirement.package_id}:{requirement.artifact_path}"
                )
            if not commit_ok:
                blockers.append(
                    f"missing_commit:{requirement.package_id}:{requirement.commit_subject}"
                )
            if artifact_ok and commit_ok:
                satisfied += 1
        statuses = tuple(external_gate_statuses)
        if any(status in {"rejected", "blocked"} for status in statuses):
            external = "rejected_or_blocked"
        elif statuses and all(status == "complete" for status in statuses):
            external = "complete"
        else:
            external = "pending"
        return Gate2To7CloseoutReport(
            engineering_package_status="complete" if not blockers else "incomplete",
            external_validation_status=external,
            requirement_count=len(self.requirements),
            satisfied_count=satisfied,
            blockers=tuple(blockers),
            external_gate_statuses=statuses,
        )
