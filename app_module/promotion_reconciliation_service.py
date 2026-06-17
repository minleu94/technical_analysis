"""Registry-based promotion 與 JSON/SQLite reconciliation。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app_module.research_run_repository import ResearchRunRepository
from app_module.strategy_version_service import StrategyVersionService
from app_module.strategy_lifecycle_service import (
    LifecycleAction,
    StrategyLifecycleService,
)


class PromotionPreflightError(Exception):
    """Registry run 未通過 promotion 前置檢查。"""


@dataclass(frozen=True)
class PromotionReconciliationIssue:
    issue_type: str
    run_id: str
    version_id: str
    details: str


class PromotionReconciliationService:
    """以 Research Run Registry 作為 promotion 單一來源。"""

    def __init__(
        self,
        *,
        research_repository: ResearchRunRepository,
        strategy_version_service: StrategyVersionService,
        lifecycle_service: StrategyLifecycleService | None = None,
    ):
        self.research_repository = research_repository
        self.strategy_version_service = strategy_version_service
        self.lifecycle_service = lifecycle_service or StrategyLifecycleService()

    def promote_registry_run(
        self,
        run_id: str,
        *,
        profile_id: str | None = None,
        notes: str | None = None,
    ) -> str:
        raw = self.research_repository.get_raw_metadata_row(run_id)
        metadata = self.research_repository.get_metadata(run_id)
        if raw is None or metadata is None:
            raise PromotionPreflightError(f"找不到 registry run: {run_id}")

        lifecycle_decision = self._validate_preflight(raw, metadata)

        version_id = self.strategy_version_service.create_version(
            strategy_id=metadata.strategy_id,
            strategy_version=None,
            params=dict(metadata.normalized_params),
            config={
                "source": "research_run_registry",
                "run_type": metadata.run_type,
                "parameter_contract_version": metadata.parameter_contract_version,
                "data_fingerprint": metadata.data_fingerprint,
                "execution_price": metadata.execution_price,
                "sizing_mode": metadata.sizing_mode,
            },
            backtest_summary=dict(metadata.metrics),
            regime=list(metadata.regime_breakdown.keys()),
            source_run_id=metadata.run_id,
            profile_id=profile_id,
            validation_status="pending",
            validation_metrics={
                "promotion_gate": "registry_month6_lifecycle",
                "lifecycle_action": lifecycle_decision.action.value,
                "lifecycle_reasons": lifecycle_decision.reasons,
                "data_fingerprint": metadata.data_fingerprint,
                "benchmark_results": metadata.benchmark_results,
            },
            notes=notes,
        )

        try:
            marked = self.research_repository.mark_promoted(run_id, version_id)
            if not marked:
                raise RuntimeError(f"registry run 回填失敗: {run_id}")
        except Exception:
            deleted = self.strategy_version_service.delete_version_file(version_id)
            if not deleted:
                self.research_repository.mark_promotion_reconciliation_required(
                    run_id, version_id
                )
            raise

        return version_id

    def scan_reconciliation_issues(self) -> list[PromotionReconciliationIssue]:
        issues: list[PromotionReconciliationIssue] = []
        versions = self.strategy_version_service.list_versions()
        version_by_id: dict[str, dict[str, Any]] = {}
        for version in versions:
            version_id = version.get("version_id")
            if version_id:
                version_by_id[str(version_id)] = version

        for version_id, version in version_by_id.items():
            source_run_id = str(version.get("source_run_id") or "")
            if not source_run_id:
                continue
            metadata = self.research_repository.get_metadata(source_run_id)
            if metadata is None or metadata.promoted_version_id != version_id:
                issues.append(
                    PromotionReconciliationIssue(
                        issue_type="json_missing_registry_backfill",
                        run_id=source_run_id,
                        version_id=version_id,
                        details="StrategyVersion JSON 有 source_run_id，但 Registry 未同步回填相同 version_id。",
                    )
                )

        for metadata in self.research_repository.list_metadata(include_archived=True):
            promoted_version_id = metadata.promoted_version_id
            if not promoted_version_id:
                continue
            version_id = str(promoted_version_id)
            registry_version = version_by_id.get(version_id)
            if registry_version is None:
                issues.append(
                    PromotionReconciliationIssue(
                        issue_type="registry_missing_json",
                        run_id=metadata.run_id,
                        version_id=version_id,
                        details="Registry 有 promoted_version_id，但找不到對應 StrategyVersion JSON。",
                    )
                )
                continue
            if str(registry_version.get("source_run_id") or "") != metadata.run_id:
                issues.append(
                    PromotionReconciliationIssue(
                        issue_type="registry_json_source_mismatch",
                        run_id=metadata.run_id,
                        version_id=version_id,
                        details="Registry promoted_version_id 與 StrategyVersion source_run_id 不一致。",
                    )
                )
        return issues

    def _validate_preflight(self, raw: dict[str, Any], metadata) -> Any:
        if raw.get("storage_state") != "committed" or raw.get("integrity_status") != "valid":
            raise PromotionPreflightError("registry run 尚未通過 integrity 檢查")
        if metadata.is_archived:
            raise PromotionPreflightError("archived run 不可 promote")
        if metadata.promoted_version_id:
            raise PromotionPreflightError("run 已 promote")
        if not metadata.parameter_contract_version:
            raise PromotionPreflightError("缺少 parameter contract version")
        if not self._passes_validation_gate(metadata.metrics):
            raise PromotionPreflightError("run 未通過 promotion 最低驗證 Gate")
        lifecycle_decision = self.lifecycle_service.evaluate_run(metadata)
        if lifecycle_decision.action != LifecycleAction.PROMOTE:
            reasons = "；".join(lifecycle_decision.reasons)
            raise PromotionPreflightError(
                f"run 未通過 Month 6 lifecycle promote gate: {reasons}"
            )
        return lifecycle_decision

    def _passes_validation_gate(self, metrics: dict[str, Any]) -> bool:
        total_return = Decimal(str(metrics.get("total_return", "0") or "0"))
        total_trades = int(metrics.get("total_trades") or 0)
        return total_return > Decimal("0") and total_trades > 0
