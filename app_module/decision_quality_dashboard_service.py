from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app_module.decision_quality_dashboard_dtos import (
    DecisionQualityDashboardCards,
    DecisionQualityDashboardRequest,
    DecisionQualityDashboardResult,
    DecisionQualityDashboardRow,
)
from app_module.decision_quality_service import DecisionQualityService


PROCESS_REVIEW_LIMITATIONS = (
    "這是流程覆盤 evidence，不是績效或責任歸因。",
    "Decision Quality Review 只用來提示人工檢查，不會自動套用任何策略或 portfolio 變更。",
    "缺少 journal、source trace 或 evidence linkage 時，只能標記流程缺口，不能判斷訊號有效。",
)


class DecisionQualityDashboardService:
    """Read-only dashboard adapter over saved decision quality reviews."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    def load_dashboard(self, request: DecisionQualityDashboardRequest) -> DecisionQualityDashboardResult:
        reviews = tuple(
            self.backend.list_reviews(
                start_date=_blank_to_none(request.start_date),
                end_date=_blank_to_none(request.end_date),
                review_type=_blank_to_none(request.review_type),
            )
        )
        items = tuple(self.backend.list_items(status=_blank_to_none(request.status)))
        rows = tuple(_row_from_item(item) for item in items if _item_matches(item, request))
        if request.min_score is not None and reviews and _latest_review(reviews).decision_quality_score_bp < int(request.min_score):
            rows = ()
        return DecisionQualityDashboardResult(
            request=request,
            cards=_cards_from_reviews_and_rows(reviews, rows),
            rows=rows,
            empty_state_message=_empty_state_message(reviews, rows),
            limitations=PROCESS_REVIEW_LIMITATIONS,
            quality_counts=dict(Counter(row.quality for row in rows)),
            warning_counts=_warning_counts(rows),
        )


def create_decision_quality_dashboard_service(
    config: Any,
    *,
    db_path: str | Path | None = None,
) -> DecisionQualityDashboardService:
    return DecisionQualityDashboardService(DecisionQualityService(config, db_path=db_path))


def _row_from_item(item: Any) -> DecisionQualityDashboardRow:
    evidence = item.evidence_json if isinstance(item.evidence_json, dict) else {}
    metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
    warnings = evidence.get("warnings") or metadata.get("warnings") or ()
    quality = evidence.get("data_quality") or evidence.get("quality") or metadata.get("quality") or "observed"
    return DecisionQualityDashboardRow(
        item_type=str(item.item_type or ""),
        symbol=str(item.symbol or ""),
        event_date=str(item.event_date or item.decision_date or ""),
        source_type=str(item.source_type or ""),
        severity=str(item.severity or ""),
        status=str(item.status or ""),
        suggested_review_question=str(item.suggested_review_question or ""),
        reason_codes=tuple(str(value) for value in item.reason_codes_json),
        related_gap_id=str(item.related_gap_id or ""),
        related_decay_id=str(item.related_decay_id or ""),
        quality=str(quality or "observed"),
        warnings=tuple(str(value) for value in _as_sequence(warnings)),
    )


def _cards_from_reviews_and_rows(
    reviews: tuple[Any, ...],
    rows: tuple[DecisionQualityDashboardRow, ...],
) -> DecisionQualityDashboardCards:
    latest = _latest_review(reviews) if reviews else None
    statuses = Counter(row.status for row in rows)
    return DecisionQualityDashboardCards(
        decision_quality_score=int(getattr(latest, "decision_quality_score_bp", 0) or 0),
        process_adherence_score=int(getattr(latest, "process_adherence_score_bp", 0) or 0),
        evidence_usage_score=int(getattr(latest, "evidence_usage_score_bp", 0) or 0),
        risk_discipline_score=int(getattr(latest, "risk_discipline_score_bp", 0) or 0),
        review_completeness_score=int(getattr(latest, "review_completeness_score_bp", 0) or 0),
        open_items=statuses["open"],
        reviewed_items=statuses["reviewed"],
        dismissed_items=statuses["dismissed"],
        warnings_count=sum(len(getattr(review, "warnings_json", ())) for review in reviews)
        + sum(len(row.warnings) for row in rows),
    )


def _item_matches(item: Any, request: DecisionQualityDashboardRequest) -> bool:
    return all(
        (
            _matches(getattr(item, "symbol", ""), request.symbol),
            _matches(getattr(item, "item_type", ""), request.item_type),
            _matches(getattr(item, "severity", ""), request.severity),
        )
    )


def _empty_state_message(reviews: tuple[Any, ...], rows: tuple[DecisionQualityDashboardRow, ...]) -> str:
    if not reviews and not rows:
        return "尚無 decision quality review evidence。請先以 dry-run 或人工確認流程產生覆盤資料。"
    if not rows:
        return "目前篩選條件下沒有待檢查項目。這不代表流程有效，只代表沒有符合條件的覆盤 evidence。"
    return ""


def _latest_review(reviews: tuple[Any, ...]) -> Any:
    return sorted(reviews, key=lambda item: (item.review_period_end, item.review_id))[-1]


def _warning_counts(rows: tuple[DecisionQualityDashboardRow, ...]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(row.warnings)
    return dict(counter)


def _matches(actual: str | None, expected: str | None) -> bool:
    expected_text = _blank_to_none(expected)
    return expected_text is None or str(actual or "") == expected_text


def _blank_to_none(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)
