from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app_module.decision_desk_dtos import DecisionDeskQuality
from app_module.evidence_event_dtos import EvidenceDataQuality
from app_module.evidence_importer_support import date_text, normalize_quality, score_bp, string_tuple


def test_normalize_quality_preserves_decision_desk_quality_mapping() -> None:
    assert normalize_quality(DecisionDeskQuality.OBSERVED) is EvidenceDataQuality.OBSERVED
    assert normalize_quality(DecisionDeskQuality.ESTIMATED) is EvidenceDataQuality.ESTIMATED
    assert normalize_quality("unknown") is EvidenceDataQuality.MISSING


def test_date_text_preserves_date_datetime_and_invalid_text_fallback() -> None:
    assert date_text(date(2026, 7, 10)) == "2026-07-10"
    assert date_text(datetime(2026, 7, 10, 9, 30)) == "2026-07-10"
    assert date_text("not-a-date-value", fallback="2026-07-01") == "not-a-date"


def test_string_tuple_and_score_bp_preserve_payload_normalization() -> None:
    assert string_tuple("rank_top; volume_ok") == ("rank_top", "volume_ok")
    assert string_tuple(["rank_top", "", 7]) == ("rank_top", "7")
    assert score_bp(Decimal("82.345")) == 8235
    assert score_bp(True) is None
