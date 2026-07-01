from __future__ import annotations

from pathlib import Path

from app_module.decision_quality_dtos import DecisionQualityItem, DecisionQualityReview
from app_module.decision_quality_repository import DecisionQualityRepository
from data_module.config import TWStockConfig


def _config(tmp_path: Path) -> TWStockConfig:
    config = TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")
    config.db_file = tmp_path / "decision_quality.db"
    config.use_sqlite = True
    return config


def _review(**overrides) -> DecisionQualityReview:
    base = {
        "review_id": "dqr-2026-06",
        "review_hash": "sha256:dqr-2026-06",
        "review_period_start": "2026-06-01",
        "review_period_end": "2026-06-30",
        "review_type": "monthly",
        "portfolio_mode_counts_json": {"simulated": 1},
        "evidence_event_count": 3,
        "trade_count": 1,
        "journal_entry_count": 0,
        "portfolio_alert_count": 1,
        "ignored_alert_count": 1,
        "manual_override_count": 0,
        "missed_high_quality_signal_count": 0,
        "unreviewed_decay_candidate_count": 0,
        "unlinked_trade_count": 1,
        "decision_quality_score_bp": 5000,
        "process_adherence_score_bp": 5000,
        "evidence_usage_score_bp": 5000,
        "risk_discipline_score_bp": 5000,
        "review_completeness_score_bp": 0,
        "review_status": "incomplete",
        "quality": "degraded",
        "warnings_json": ["journal_missing"],
        "diagnostics_json": [{"code": "source_trace_gap"}],
        "metadata_json": {"source": "unit-test"},
    }
    base.update(overrides)
    return DecisionQualityReview(**base)


def _item(**overrides) -> DecisionQualityItem:
    base = {
        "item_id": "dqi-1",
        "review_id": "dqr-2026-06",
        "item_type": "trade_without_source_trace",
        "symbol": "2330",
        "event_date": "2026-06-10",
        "decision_date": "2026-06-10",
        "source_type": "portfolio_trade",
        "source_id": "trade-1",
        "related_trade_id": "trade-1",
        "severity": "medium",
        "status": "open",
        "reason_codes_json": ["source_trace_missing"],
        "evidence_json": {"trade_id": "trade-1"},
        "suggested_review_question": "這筆流程紀錄是否需要補上來源假設或研究連結？",
    }
    base.update(overrides)
    return DecisionQualityItem(**base)


def test_repository_idempotent_review_save_and_list_items(tmp_path: Path) -> None:
    repo = DecisionQualityRepository(_config(tmp_path))

    saved = repo.save_review(_review(), items=[_item()])
    duplicate = repo.save_review(_review(review_id="dqr-other"), items=[_item(item_id="dqi-other")])

    assert duplicate.review_id == saved.review_id
    assert repo.get_review("dqr-2026-06") == saved
    assert [review.review_id for review in repo.list_reviews()] == ["dqr-2026-06"]
    items = repo.list_items(review_id="dqr-2026-06")
    assert [item.item_id for item in items] == ["dqi-1"]
    assert items[0].reason_codes_json == ["source_trace_missing"]


def test_mark_item_reviewed_and_dismissed_preserves_status_history(tmp_path: Path) -> None:
    repo = DecisionQualityRepository(_config(tmp_path))
    repo.save_review(_review(), items=[_item()])

    reviewed = repo.mark_item_reviewed("dqi-1", reviewer="qa", note="已補覆盤紀錄")
    dismissed = repo.mark_item_dismissed("dqi-1", reviewer="qa", reason_code="not_applicable", note="資料不適用")
    history = repo.list_item_status_history("dqi-1")

    assert reviewed.status == "reviewed"
    assert dismissed.status == "dismissed"
    assert [row["new_status"] for row in history] == ["reviewed", "dismissed"]
    assert history[-1]["reason_code"] == "not_applicable"


def test_create_action_item_is_append_only(tmp_path: Path) -> None:
    repo = DecisionQualityRepository(_config(tmp_path))
    repo.save_review(_review(), items=[_item()])

    action = repo.create_action_item(
        review_id="dqr-2026-06",
        item_id="dqi-1",
        description="補上週覆盤問題清單",
        owner="human",
    )

    actions = repo.list_action_items(review_id="dqr-2026-06")
    assert action.action_item_id.startswith("dqa_")
    assert [item.description for item in actions] == ["補上週覆盤問題清單"]
