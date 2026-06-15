import json
import pickle
from datetime import date
from decimal import Decimal

import pytest

from decision_module.factors.factor_dtos import (
    FactorDefinition,
    FactorDiagnostic,
    FactorGateResult,
    FactorQuality,
    FactorRecord,
    MissingPolicy,
)


def test_factor_package_exports_factor_value():
    from decision_module.factors import FactorValue

    assert FactorValue is not None


def test_factor_record_accepts_integer_score_bp():
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata={"window": 20},
    )

    assert record.score_bp == 8235
    assert record.to_dict()["quality"] == "observed"
    assert record.to_dict()["value"] == "82.35"


def test_factor_record_rejects_out_of_range_score_bp():
    with pytest.raises(ValueError, match="score_bp"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=Decimal("101"),
            score_bp=10001,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
        )


def test_factor_record_rejects_empty_factor_name():
    with pytest.raises(ValueError, match="factor_name"):
        FactorRecord(
            factor_name="",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=Decimal("82.35"),
            score_bp=8235,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
        )


def test_factor_record_rejects_empty_stock_code():
    with pytest.raises(ValueError, match="stock_code"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=Decimal("82.35"),
            score_bp=8235,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
        )


def test_factor_record_rejects_float_value():
    with pytest.raises((TypeError, ValueError), match="value"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=1.2,
            score_bp=120,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
        )


def test_factor_record_rejects_bool_value():
    with pytest.raises((TypeError, ValueError), match="value"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=True,
            score_bp=120,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
        )


def test_factor_record_rejects_bool_score_bp():
    with pytest.raises((TypeError, ValueError), match="score_bp"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=Decimal("1.2"),
            score_bp=True,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
        )


def test_factor_record_accepts_missing_value_and_score():
    record = FactorRecord(
        factor_name="fundamental.revenue_yoy",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=None,
        score_bp=None,
        quality=FactorQuality.MISSING,
        missing_policy=MissingPolicy.SKIP,
        source_version="revenue-v1",
    )

    serialized = record.to_dict()

    assert serialized["value"] is None
    assert serialized["score_bp"] is None


def test_factor_record_preserves_integer_value_in_serialization():
    record = FactorRecord(
        factor_name="broker_flow.net_buy_days",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=3,
        score_bp=7000,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="broker-flow-v1",
    )

    assert record.to_dict()["value"] == 3


def test_factor_record_metadata_is_immutable_after_construction():
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata={"x": 1},
    )

    with pytest.raises(TypeError):
        record.metadata["x"] = 2


def test_factor_record_metadata_is_deep_frozen_after_construction():
    nested = {"outer": {"inner": {"x": 1}}, "items": [{"x": 1}]}
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata=nested,
    )

    nested["outer"]["inner"]["x"] = 2
    nested["items"][0]["x"] = 2

    assert record.metadata["outer"]["inner"]["x"] == 1
    assert record.metadata["items"][0]["x"] == 1
    assert isinstance(record.metadata["items"], tuple)

    with pytest.raises(TypeError):
        record.metadata["outer"]["inner"]["x"] = 3
    with pytest.raises(TypeError):
        record.metadata["items"][0]["x"] = 3


def test_factor_record_can_round_trip_through_pickle():
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata={"outer": {"inner": {"x": 1}}},
    )

    restored = pickle.loads(pickle.dumps(record))

    assert restored == record
    assert restored.metadata["outer"]["inner"]["x"] == 1


def test_factor_record_to_dict_serializes_metadata_json_safely():
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata={
            "as_of": date(2026, 6, 12),
            "quality": FactorQuality.OBSERVED,
            "thresholds": (Decimal("1.1"), {"updated": date(2026, 6, 13)}),
        },
    )

    serialized = record.to_dict()

    assert serialized["metadata"]["as_of"] == "2026-06-12"
    assert serialized["metadata"]["quality"] == "observed"
    assert serialized["metadata"]["thresholds"] == [
        "1.1",
        {"updated": "2026-06-13"},
    ]
    json.dumps(serialized, ensure_ascii=False, sort_keys=True)


def test_factor_record_rejects_unsupported_object_metadata_at_construction():
    with pytest.raises(TypeError, match="metadata"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=Decimal("82.35"),
            score_bp=8235,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
            metadata={"unsupported": object()},
        )


def test_factor_record_rejects_float_metadata_at_construction():
    with pytest.raises(TypeError, match="metadata"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=Decimal("82.35"),
            score_bp=8235,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
            metadata={"unsupported": 1.2},
        )


def test_factor_record_rejects_non_string_metadata_key_at_construction():
    with pytest.raises(TypeError, match="metadata|key"):
        FactorRecord(
            factor_name="technical.total_score",
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            value=Decimal("82.35"),
            score_bp=8235,
            quality=FactorQuality.OBSERVED,
            missing_policy=MissingPolicy.FAIL_CLOSED,
            source_version="technical-v1",
            metadata={1: "bad"},
        )


def test_factor_record_metadata_set_is_frozen_after_construction():
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata={"tags": {"momentum", "volume"}},
    )

    assert isinstance(record.metadata["tags"], frozenset)
    with pytest.raises(AttributeError):
        record.metadata["tags"].add("breakout")


def test_factor_record_to_dict_serializes_set_metadata_deterministically():
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata={"tags": {"momentum", "quality"}},
    )

    serialized = record.to_dict()

    assert serialized["metadata"]["tags"] == ["momentum", "quality"]
    json.dumps(serialized, ensure_ascii=False, sort_keys=True)


def test_factor_record_metadata_does_not_alias_nested_mutables():
    metadata = {
        "outer": {"inner": {"x": 1}},
        "items": [{"x": 1}],
        "tags": {"momentum"},
    }
    record = FactorRecord(
        factor_name="technical.total_score",
        stock_code="2330",
        as_of_date=date(2026, 6, 12),
        available_date=date(2026, 6, 12),
        value=Decimal("82.35"),
        score_bp=8235,
        quality=FactorQuality.OBSERVED,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        metadata=metadata,
    )

    metadata["outer"]["inner"]["x"] = 2
    metadata["items"][0]["x"] = 2
    metadata["tags"].add("volume")

    assert record.metadata["outer"]["inner"]["x"] == 1
    assert record.metadata["items"][0]["x"] == 1
    assert record.metadata["tags"] == frozenset({"momentum"})


def test_factor_definition_declares_neutral_score_and_stale_days():
    definition = FactorDefinition(
        factor_name="volume.volume_ratio",
        display_name="量能比率",
        category="volume",
        source_version="volume-v1",
        default_missing_policy=MissingPolicy.NEUTRAL,
        neutral_score_bp=5000,
        stale_after_days=5,
    )

    assert definition.neutral_score_bp == 5000
    assert definition.stale_after_days == 5


def test_factor_definition_rejects_out_of_range_neutral_score_bp():
    with pytest.raises(ValueError, match="neutral_score_bp"):
        FactorDefinition(
            factor_name="volume.volume_ratio",
            display_name="量能比率",
            category="volume",
            source_version="volume-v1",
            default_missing_policy=MissingPolicy.NEUTRAL,
            neutral_score_bp=10001,
        )


def test_factor_definition_rejects_bool_neutral_score_bp():
    with pytest.raises((TypeError, ValueError), match="neutral_score_bp"):
        FactorDefinition(
            factor_name="volume.volume_ratio",
            display_name="量能比率",
            category="volume",
            source_version="volume-v1",
            default_missing_policy=MissingPolicy.NEUTRAL,
            neutral_score_bp=True,
        )


def test_factor_diagnostic_to_dict():
    diagnostic = FactorDiagnostic(
        code="missing_factor",
        factor_name="volume.volume_ratio",
        stock_code="2330",
        message="factor is missing",
    )

    assert diagnostic.to_dict() == {
        "code": "missing_factor",
        "factor_name": "volume.volume_ratio",
        "stock_code": "2330",
        "message": "factor is missing",
    }


def test_factor_gate_result_defaults_are_empty_tuples():
    result = FactorGateResult()

    assert result.accepted == ()
    assert result.neutralized == ()
    assert result.skipped == ()
    assert result.diagnostics == ()


def test_factor_gate_result_coerces_list_inputs_to_tuples():
    diagnostic = FactorDiagnostic(
        code="missing_factor",
        factor_name="volume.volume_ratio",
        stock_code="2330",
        message="factor is missing",
    )

    result = FactorGateResult(
        accepted=[],
        neutralized=[],
        skipped=[],
        diagnostics=[diagnostic],
    )

    assert result.accepted == ()
    assert result.neutralized == ()
    assert result.skipped == ()
    assert result.diagnostics == (diagnostic,)
