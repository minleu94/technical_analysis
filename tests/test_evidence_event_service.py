from __future__ import annotations

from pathlib import Path

import pytest

from data_module.config import TWStockConfig
from app_module.evidence_event_dtos import EvidenceDataQuality, EvidenceEventType
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.evidence_event_service import EvidenceEventService, canonical_evidence_json


def _config(tmp_path: Path) -> TWStockConfig:
    return TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")


def test_canonical_evidence_json_is_deterministic():
    left = canonical_evidence_json({"b": [2, 1], "a": {"z": "x"}})
    right = canonical_evidence_json({"a": {"z": "x"}, "b": [2, 1]})

    assert left == right
    assert left == '{"a":{"z":"x"},"b":[2,1]}'


def test_build_event_hash_is_stable_for_reordered_json_fields(tmp_path):
    service = EvidenceEventService(EvidenceEventRepository(_config(tmp_path)))
    first = service.build_event_hash(
        event_date="2026-06-01",
        decision_date="2026-06-01",
        symbol="2330",
        event_type=EvidenceEventType.WATCHLIST_TRIGGER,
        source_type="decision_desk",
        source_id="desk-001",
        source_snapshot_id="snapshot-001",
        reason_codes=("b", "a"),
        why_not_codes=(),
        risk_codes=("risk",),
        strategy_version_id="",
        profile_id="",
        run_id="",
        metadata={"z": 1, "a": 2},
    )
    second = service.build_event_hash(
        event_date="2026-06-01",
        decision_date="2026-06-01",
        symbol="2330",
        event_type=EvidenceEventType.WATCHLIST_TRIGGER,
        source_type="decision_desk",
        source_id="desk-001",
        source_snapshot_id="snapshot-001",
        reason_codes=("b", "a"),
        why_not_codes=(),
        risk_codes=("risk",),
        strategy_version_id="",
        profile_id="",
        run_id="",
        metadata={"a": 2, "z": 1},
    )

    assert first == second
    assert first.startswith("sha256:")


def test_record_event_fails_closed_when_required_fields_missing(tmp_path):
    service = EvidenceEventService(EvidenceEventRepository(_config(tmp_path)))

    with pytest.raises(ValueError, match="symbol"):
        service.record_event(
            event_date="2026-06-01",
            decision_date="2026-06-01",
            symbol="",
            event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
            event_family="recommendation",
            source_type="recommendation_result",
            source_id="rec-001",
            data_quality=EvidenceDataQuality.OBSERVED,
            as_of_date="2026-06-01",
            available_date="2026-06-01",
        )


def test_record_event_normalizes_json_and_is_idempotent(tmp_path):
    service = EvidenceEventService(EvidenceEventRepository(_config(tmp_path)))

    first = service.record_event(
        event_date="2026-06-01",
        decision_date="2026-06-01",
        symbol="2330",
        event_type=EvidenceEventType.RECOMMENDATION_INCLUDED,
        event_family="recommendation",
        source_type="recommendation_result",
        source_id="rec-001",
        source_snapshot_id="snapshot-001",
        reason_codes=["rank_top", "volume_ok"],
        why_not_codes=None,
        risk_codes=("liquidity_watch",),
        data_quality=EvidenceDataQuality.OBSERVED,
        warnings={"late_snapshot"},
        as_of_date="2026-06-01",
        available_date="2026-06-01",
        metadata={"z": 1, "a": 2},
    )
    duplicate = service.record_event(
        event_date="2026-06-01",
        decision_date="2026-06-01",
        symbol="2330",
        event_type="recommendation_included",
        event_family="recommendation",
        source_type="recommendation_result",
        source_id="rec-001",
        source_snapshot_id="snapshot-001",
        reason_codes=("rank_top", "volume_ok"),
        why_not_codes=(),
        risk_codes=("liquidity_watch",),
        data_quality="observed",
        warnings=("late_snapshot",),
        as_of_date="2026-06-01",
        available_date="2026-06-01",
        metadata={"a": 2, "z": 1},
    )

    assert first.event_id == duplicate.event_id
    assert first.reason_codes == ("rank_top", "volume_ok")
    assert first.why_not_codes == ()
    assert first.warnings == ("late_snapshot",)
    assert first.metadata == {"a": 2, "z": 1}


def test_record_events_skips_nothing_and_returns_existing_rows(tmp_path):
    service = EvidenceEventService(EvidenceEventRepository(_config(tmp_path)))
    payload = {
        "event_date": "2026-06-01",
        "decision_date": "2026-06-01",
        "symbol": "2330",
        "event_type": EvidenceEventType.PORTFOLIO_ALERT,
        "event_family": "portfolio",
        "source_type": "portfolio_alert",
        "source_id": "alert-001",
        "reason_codes": ("condition:warning",),
        "data_quality": EvidenceDataQuality.DEGRADED,
        "warnings": ("chip_estimated",),
        "as_of_date": "2026-06-01",
        "available_date": "2026-06-01",
    }

    records = service.record_events([payload, payload])

    assert len(records) == 2
    assert records[0].event_id == records[1].event_id
