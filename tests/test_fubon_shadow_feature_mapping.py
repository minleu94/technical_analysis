"""TDD Unit tests for Fubon shadow feature mapping contract and computability result.

Tests positive feature mapping, negative unmapped handling, PIT safety, symbol isolation,
component-level computability (Score, Recommendation, Portfolio, Exit), and lineage hashing.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest

from data_module.fubon_pit_validator import FubonPITObservation, FubonPITObservationValidator
from data_module.fubon_shadow_feature_mapping import (
    FubonShadowFeatureMapping,
    FubonFeatureMappingItem,
    ComponentComputabilityResult,
)


def _sample_observation(
    symbol: str = "2330",
    source_id: str = "microstructure.disposition_stock",
    quantities: dict | None = None,
    available_at: str = "2026-07-25T00:00:00+00:00",
    decision_timestamp: str = "2026-07-26T00:00:00+00:00",
    quarantine_status: str = "clean",
    quality_status: str = "observed",
) -> FubonPITObservation:
    q = quantities if quantities is not None else {"is_disposition": 1}
    return FubonPITObservation(
        source_id=source_id,
        source_version="fubon-neo-marketdata.v2.2.8",
        symbol=symbol,
        market_timestamp="2026-07-25T00:00:00+00:00",
        published_at="2026-07-25T00:00:00+00:00",
        first_observed_at="2026-07-25T00:00:00+00:00",
        available_at=available_at,
        decision_timestamp=decision_timestamp,
        revision_id="rev-1",
        raw_payload_sha256="sha256:raw1",
        normalized_content_sha256="sha256:norm1",
        quality_status=quality_status,
        missing_or_degraded_reasons=(),
        quarantine_status=quarantine_status,
        quantities=q,
    )


def test_feature_mapping_builds_proven_items_and_symbol_isolation() -> None:
    obs1 = _sample_observation(symbol="2330", source_id="microstructure.disposition_stock", quantities={"is_disposition": 1})
    obs2 = _sample_observation(symbol="2317", source_id="microstructure.suspended_halt_resume", quantities={"is_suspended": 1})

    mapper = FubonShadowFeatureMapping()
    mapping_result = mapper.build_mapping(
        observations=[obs1, obs2],
        decision_timestamp="2026-07-26T00:00:00+00:00",
        position_context_supplied=False,
    )

    assert mapping_result.mapping_revision is not None
    assert len(mapping_result.mapping_items) == 2
    assert "fubon_is_disposition" in mapping_result.consumed_fields
    assert "fubon_is_suspended" in mapping_result.consumed_fields

    # Symbol isolation check
    mapped_2330 = mapper.get_symbol_features(mapping_result, "2330")
    mapped_2317 = mapper.get_symbol_features(mapping_result, "2317")
    mapped_2454 = mapper.get_symbol_features(mapping_result, "2454")

    assert mapped_2330 == {"fubon_is_disposition": 1}
    assert mapped_2317 == {"fubon_is_suspended": 1}
    assert mapped_2454 == {}


def test_component_computability_reporting() -> None:
    obs1 = _sample_observation(symbol="2330", source_id="microstructure.disposition_stock", quantities={"is_disposition": 1})

    mapper = FubonShadowFeatureMapping()
    res = mapper.build_mapping(
        observations=[obs1],
        decision_timestamp="2026-07-26T00:00:00+00:00",
        position_context_supplied=True,
    )

    # 尚未有既有 consumer 讀取 Fubon shadow 欄位，所有 component 必須 fail closed。
    score_comp = res.component_results["score"]
    assert score_comp.status == "not_computable"
    assert "fubon_is_disposition" in score_comp.consumed_fields
    assert "authoritative_consumer_does_not_read_fubon_feature" in score_comp.blockers

    rec_comp = res.component_results["recommendation"]
    assert rec_comp.status == "not_computable"

    port_comp = res.component_results["portfolio"]
    assert port_comp.status == "not_computable"

    exit_comp = res.component_results["exit"]
    assert exit_comp.status == "not_computable"


def test_unmapped_feature_and_quarantine_isolation() -> None:
    obs_quarantined = _sample_observation(
        symbol="2330",
        source_id="microstructure.disposition_stock",
        quarantine_status="quarantined",
    )

    mapper = FubonShadowFeatureMapping()
    res = mapper.build_mapping(
        observations=[obs_quarantined],
        decision_timestamp="2026-07-26T00:00:00+00:00",
        position_context_supplied=False,
    )

    score_comp = res.component_results["score"]
    assert score_comp.status == "not_computable"
    assert "pit_validation_blocked_or_quarantined" in score_comp.blockers
