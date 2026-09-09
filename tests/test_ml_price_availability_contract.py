from __future__ import annotations

import pytest

from data_module.ml_price_availability_contract import (
    PRICE_AVAILABILITY_CONTRACT_VERSION,
    build_price_unavailable_research_contract,
)


def _raw_row(*, open_value: object = "--") -> dict[str, object]:
    return {
        "symbol": "6949",
        "name": "沛爾生醫*-創",
        "open": open_value,
        "high": open_value,
        "low": open_value,
        "close": open_value,
        "volume": 24_486_488,
        "source_date": "20260907",
    }


def test_price_unavailable_contract_preserves_row_mask_and_explicit_windows() -> None:
    raw_row = _raw_row(open_value=None)
    contract = build_price_unavailable_research_contract(
        symbol="6949",
        date_iso="2026-09-07",
        raw_row=raw_row,
        feature_window_dates=("2026-09-05", "2026-09-07"),
        label_window_dates=("2026-09-08", "2026-09-12"),
        source_file={"path": "daily_price/20260907.csv", "market": "TWSE"},
    )

    assert contract["schema_version"] == PRICE_AVAILABILITY_CONTRACT_VERSION
    assert contract["status"] == "price_unavailable"
    assert contract["raw_row"] == raw_row
    assert contract["missing_mask"] == {
        "open": True,
        "high": True,
        "low": True,
        "close": True,
    }
    assert contract["volume_shares"] == 24_486_488
    assert contract["affected_window"] == {
        "feature_window_dates": ["2026-09-05", "2026-09-07"],
        "label_window_dates": ["2026-09-08", "2026-09-12"],
        "affected_dates": [
            "2026-09-05",
            "2026-09-07",
            "2026-09-08",
            "2026-09-12",
        ],
        "window_scope": "explicit",
        "feature_window_complete": True,
        "label_window_complete": True,
        "horizon_expansion_required": False,
        "adjacency_break_at_anchor": True,
        "surrounding_rows_may_not_be_bridged": True,
    }
    assert contract["disposition"]["preserve_source_row"] is True
    assert contract["disposition"]["drop_source_row"] is False
    assert contract["disposition"]["zero_fill"] is False
    assert contract["disposition"]["require_official_cause"] is False
    assert contract["disposition"]["source_quality_research_eligible"] is True


def test_anchor_only_contract_cannot_be_used_as_complete_horizon() -> None:
    contract = build_price_unavailable_research_contract(
        symbol="2330",
        date_iso="2026-09-07",
        raw_row=_raw_row(),
    )

    assert contract["affected_window"]["window_scope"] == "anchor_only"
    assert contract["affected_window"]["feature_window_complete"] is False
    assert contract["affected_window"]["label_window_complete"] is False
    assert contract["affected_window"]["horizon_expansion_required"] is True
    assert contract["affected_window"]["feature_window_dates"] == ["2026-09-07"]
    assert contract["affected_window"]["label_window_dates"] == []
    assert contract["availability"]["available_at"] is None
    assert contract["availability"]["cause_inferred"] is False


def test_partial_window_is_still_incomplete_for_the_missing_side() -> None:
    feature_only = build_price_unavailable_research_contract(
        symbol="2330",
        date_iso="2026-09-07",
        raw_row=_raw_row(),
        feature_window_dates=("2026-09-07",),
    )
    label_only = build_price_unavailable_research_contract(
        symbol="2330",
        date_iso="2026-09-07",
        raw_row=_raw_row(),
        label_window_dates=("2026-09-08",),
    )

    assert feature_only["affected_window"]["feature_window_complete"] is True
    assert feature_only["affected_window"]["label_window_complete"] is False
    assert feature_only["affected_window"]["horizon_expansion_required"] is True
    assert label_only["affected_window"]["feature_window_complete"] is False
    assert label_only["affected_window"]["label_window_complete"] is True
    assert label_only["affected_window"]["horizon_expansion_required"] is True


def test_contract_rejects_noncanonical_date_or_unavailable_at_without_timezone() -> None:
    with pytest.raises(ValueError, match="canonical YYYY-MM-DD"):
        build_price_unavailable_research_contract(
            symbol="2330",
            date_iso="20260907",
            raw_row=_raw_row(),
        )
    with pytest.raises(ValueError, match="include a timezone"):
        build_price_unavailable_research_contract(
            symbol="2330",
            date_iso="2026-09-07",
            raw_row=_raw_row(),
            available_at="2026-09-08T12:00:00",
        )


def test_contract_rejects_fully_available_price_row() -> None:
    with pytest.raises(ValueError, match="no unavailable price field"):
        build_price_unavailable_research_contract(
            symbol="2330",
            date_iso="2026-09-07",
            raw_row={
                "open": "100.00",
                "high": "101.00",
                "low": "99.00",
                "close": "100.50",
                "volume": 1000,
            },
        )


@pytest.mark.parametrize("bad_value", ["-1", "NaN", "not-a-price", 0])
def test_invalid_price_is_not_eligible_for_missing_price_research_exception(
    bad_value: object,
) -> None:
    contract = build_price_unavailable_research_contract(
        symbol="2330",
        date_iso="2026-09-07",
        raw_row={
            "open": bad_value,
            "high": "100",
            "low": "99",
            "close": "100",
            "volume": 1000,
        },
    )

    assert contract["status"] == "price_unavailable"
    assert contract["field_status"]["open"] == "invalid"
    assert contract["disposition"]["source_quality_research_eligible"] is False
    assert contract["disposition"]["source_quality_disposition"] == (
        "invalid_price_requires_quarantine"
    )
