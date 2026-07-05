from __future__ import annotations

from datetime import date
from decimal import Decimal

from app_module.cross_sectional_factor_dtos import ConceptBasketDefinition
from app_module.cross_sectional_factor_pipeline import CrossSectionalFactorPipeline
from decision_module.factors.factor_adapters import (
    build_technical_total_score_factor,
    build_volume_ratio_factor,
)


def test_pipeline_ranks_factor_rows_with_stable_tie_rank():
    records = [
        build_technical_total_score_factor(
            stock_code="2330",
            as_of_date=date(2026, 7, 4),
            available_date=date(2026, 7, 5),
            total_score=Decimal("80"),
        ),
        build_technical_total_score_factor(
            stock_code="2317",
            as_of_date=date(2026, 7, 4),
            available_date=date(2026, 7, 5),
            total_score=Decimal("80"),
        ),
    ]

    snapshot = CrossSectionalFactorPipeline().build_snapshot(
        records,
        decision_date=date(2026, 7, 5),
        universe_id="test-universe",
    )

    assert [row.stock_code for row in snapshot.rows] == ["2317", "2330"]
    assert [row.rank for row in snapshot.rows] == [1, 1]
    assert [row.quantile_bp for row in snapshot.rows] == [10000, 10000]
    assert snapshot.metadata["gate_summary"]["accepted_count"] == 2


def test_pipeline_neutralizes_lookahead_and_skips_missing_records():
    records = [
        build_volume_ratio_factor(
            stock_code="2330",
            as_of_date=date(2026, 7, 6),
            available_date=date(2026, 7, 6),
            volume_ratio=Decimal("0.8"),
        ),
        build_volume_ratio_factor(
            stock_code="2317",
            as_of_date=date(2026, 7, 4),
            available_date=date(2026, 7, 5),
            volume_ratio=None,
        ),
    ]

    snapshot = CrossSectionalFactorPipeline().build_snapshot(
        records,
        decision_date=date(2026, 7, 5),
        universe_id="test-universe",
    )

    assert len(snapshot.rows) == 2
    neutralized = [row for row in snapshot.rows if row.stock_code == "2330"][0]
    missing = [row for row in snapshot.rows if row.stock_code == "2317"][0]
    assert neutralized.quality.value == "neutral"
    assert neutralized.score_bp == 5000
    assert missing.quality.value == "neutral"
    assert snapshot.metadata["gate_summary"]["neutralized_count"] == 2
    assert {item.code for item in snapshot.diagnostics} == {
        "factor.neutralized_lookahead",
        "factor.neutralized_missing",
    }


def test_pipeline_attaches_available_concept_basket_and_sector():
    record = build_technical_total_score_factor(
        stock_code="2330",
        as_of_date=date(2026, 7, 4),
        available_date=date(2026, 7, 5),
        total_score=Decimal("90"),
    )
    concept = ConceptBasketDefinition(
        basket_id="ai",
        display_name="AI 概念股",
        basket_version="ai-v1",
        members=("2330", "3661"),
        available_date=date(2026, 7, 5),
    )

    snapshot = CrossSectionalFactorPipeline().build_snapshot(
        [record],
        decision_date=date(2026, 7, 5),
        universe_id="test-universe",
        sector_by_stock={"2330": "半導體"},
        concept_baskets=(concept,),
    )

    assert snapshot.rows[0].sector == "半導體"
    assert snapshot.rows[0].concept_basket == "ai"
    assert snapshot.rows[0].metadata["concept_basket_version"] == "ai-v1"


def test_pipeline_blocks_unavailable_concept_basket_assignment():
    record = build_technical_total_score_factor(
        stock_code="2330",
        as_of_date=date(2026, 7, 4),
        available_date=date(2026, 7, 5),
        total_score=Decimal("90"),
    )
    concept = ConceptBasketDefinition(
        basket_id="ai",
        display_name="AI 概念股",
        basket_version="ai-v2",
        members=("2330",),
        available_date=date(2026, 7, 6),
    )

    snapshot = CrossSectionalFactorPipeline().build_snapshot(
        [record],
        decision_date=date(2026, 7, 5),
        universe_id="test-universe",
        concept_baskets=(concept,),
    )

    assert snapshot.rows[0].concept_basket is None
    assert any(item.code == "concept_basket_unavailable" for item in snapshot.diagnostics)
