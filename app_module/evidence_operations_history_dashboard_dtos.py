from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceOperationsHistoryDashboardRequest:
    start_date: str | None = None
    end_date: str | None = None
    limit: int = 50


@dataclass(frozen=True)
class EvidenceOperationsHistoryDashboardCards:
    reviews_count: int = 0
    needs_manual_review_count: int = 0
    coverage_only_count: int = 0
    ready_for_closeout_count: int = 0
    production_scheduler_allowed_count: int = 0
    warnings_count: int = 0


@dataclass(frozen=True)
class EvidenceOperationsHistoryDashboardRow:
    period_start: str
    period_end: str
    review_status: str
    scheduler_readiness: str
    production_scheduler_allowed: bool
    decision_quality_reviews_count: int
    signal_decay_observations_count: int
    manual_lifecycle_candidate_count: int
    warnings_count: int
    review_id: str
    created_at: str = ""


@dataclass(frozen=True)
class EvidenceOperationsHistoryDashboardResult:
    request: EvidenceOperationsHistoryDashboardRequest
    cards: EvidenceOperationsHistoryDashboardCards
    rows: tuple[EvidenceOperationsHistoryDashboardRow, ...] = ()
    empty_state_message: str = ""
    limitations: tuple[str, ...] = (
        "Evidence Operations history 只讀取已保存 weekly review，不會啟用 production scheduler。",
        "歷史紀錄只代表人工覆盤封存，不代表策略、推薦或警示具備投資有效性。",
        "demote / retire candidate 仍需人工審核，不會自動修改策略版本或持倉。",
    )
