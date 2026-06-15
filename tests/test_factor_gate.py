from datetime import date
from decimal import Decimal

import pytest

from decision_module.factors.factor_dtos import FactorQuality, FactorRecord, MissingPolicy
from decision_module.factors.factor_gate import (
    FactorGate,
    FactorLookAheadError,
    FactorMissingError,
)


def _record(
    *,
    available_date,
    policy=MissingPolicy.FAIL_CLOSED,
    quality=FactorQuality.OBSERVED,
):
    return FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=available_date,
        value=Decimal("80"),
        score_bp=8000,
        quality=quality,
        missing_policy=policy,
        source_version="technical-v1",
    )


def test_gate_accepts_available_factor():
    result = FactorGate().validate_for_decision(
        [_record(available_date=date(2026, 6, 12))],
        decision_date=date(2026, 6, 14),
    )

    assert len(result.accepted) == 1
    assert not result.diagnostics


def test_gate_rejects_future_factor_fail_closed():
    with pytest.raises(FactorLookAheadError) as exc_info:
        FactorGate().validate_for_decision(
            [_record(available_date=date(2026, 6, 15))],
            decision_date=date(2026, 6, 14),
        )

    message = str(exc_info.value)
    assert "technical.total_score" in message
    assert "2330" in message
    assert "as_of_date=2026-06-12" in message
    assert "available_date=2026-06-15" in message
    assert "decision_date=2026-06-14" in message
    assert "technical-v1" in message


def test_gate_neutralizes_future_factor_when_policy_is_neutral():
    result = FactorGate().validate_for_decision(
        [_record(available_date=date(2026, 6, 15), policy=MissingPolicy.NEUTRAL)],
        decision_date=date(2026, 6, 14),
        neutral_score_bp=5000,
    )

    assert result.neutralized[0].quality == FactorQuality.NEUTRAL
    assert result.neutralized[0].score_bp == 5000
    assert result.diagnostics[0].code == "factor.neutralized_lookahead"


def test_gate_skips_future_factor_when_policy_is_skip():
    result = FactorGate().validate_for_decision(
        [_record(available_date=date(2026, 6, 15), policy=MissingPolicy.SKIP)],
        decision_date=date(2026, 6, 14),
    )

    assert len(result.skipped) == 1
    assert result.diagnostics[0].code == "factor.skipped_lookahead"


def test_gate_skips_missing_factor_when_policy_is_skip():
    result = FactorGate().validate_for_decision(
        [
            _record(
                available_date=date(2026, 6, 12),
                policy=MissingPolicy.SKIP,
                quality=FactorQuality.MISSING,
            )
        ],
        decision_date=date(2026, 6, 14),
    )

    assert len(result.skipped) == 1
    assert result.diagnostics[0].code == "factor.skipped_missing"


def test_gate_neutralizes_missing_factor_when_policy_is_neutral():
    result = FactorGate().validate_for_decision(
        [
            _record(
                available_date=date(2026, 6, 12),
                policy=MissingPolicy.NEUTRAL,
                quality=FactorQuality.MISSING,
            )
        ],
        decision_date=date(2026, 6, 14),
        neutral_score_bp=4500,
    )

    assert result.neutralized[0].quality == FactorQuality.NEUTRAL
    assert result.neutralized[0].score_bp == 4500
    assert result.diagnostics[0].code == "factor.neutralized_missing"


def test_gate_rejects_missing_factor_fail_closed():
    with pytest.raises(FactorMissingError) as exc_info:
        FactorGate().validate_for_decision(
            [_record(available_date=date(2026, 6, 12), quality=FactorQuality.MISSING)],
            decision_date=date(2026, 6, 14),
        )

    message = str(exc_info.value)
    assert "technical.total_score" in message
    assert "2330" in message
    assert "missing" in message


def test_gate_rejects_bool_neutral_score_bp_before_records_are_processed():
    with pytest.raises(TypeError, match="neutral_score_bp"):
        FactorGate().validate_for_decision(
            [],
            decision_date=date(2026, 6, 14),
            neutral_score_bp=True,
        )


def test_gate_rejects_out_of_range_neutral_score_bp_before_neutralization():
    with pytest.raises(ValueError, match="neutral_score_bp"):
        FactorGate().validate_for_decision(
            [_record(available_date=date(2026, 6, 12))],
            decision_date=date(2026, 6, 14),
            neutral_score_bp=10001,
        )


def test_gate_result_exposes_tuples():
    result = FactorGate().validate_for_decision(
        [
            _record(available_date=date(2026, 6, 12)),
            _record(available_date=date(2026, 6, 12), policy=MissingPolicy.SKIP, quality=FactorQuality.MISSING),
            _record(available_date=date(2026, 6, 12), policy=MissingPolicy.NEUTRAL, quality=FactorQuality.MISSING),
        ],
        decision_date=date(2026, 6, 14),
    )

    assert isinstance(result.accepted, tuple)
    assert isinstance(result.neutralized, tuple)
    assert isinstance(result.skipped, tuple)
    assert isinstance(result.diagnostics, tuple)
