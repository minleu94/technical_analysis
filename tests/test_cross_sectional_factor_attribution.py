from __future__ import annotations

from datetime import date
from decimal import Decimal

from app_module.cross_sectional_factor_attribution import (
    build_cross_sectional_factor_attribution_summary,
)
from app_module.cross_sectional_factor_dtos import (
    CrossSectionalFactorDiagnostic,
    CrossSectionalFactorRow,
    CrossSectionalFactorSnapshot,
)
from app_module.cross_sectional_factor_repository import CrossSectionalFactorRepository
from decision_module.factors.factor_dtos import FactorQuality, MissingPolicy


def _row(
    *,
    row_id: str,
    stock_code: str,
    quantile_bp: int,
    quality: FactorQuality = FactorQuality.OBSERVED,
    sector: str = "半導體",
    concept_basket: str | None = "ai",
) -> CrossSectionalFactorRow:
    return CrossSectionalFactorRow(
        row_id=row_id,
        stock_code=stock_code,
        factor_name="technical.total_score",
        as_of_date=date(2026, 7, 4),
        available_date=date(2026, 7, 5),
        value=Decimal("80"),
        score_bp=8000,
        rank=1,
        quantile_bp=quantile_bp,
        universe_size=2,
        quality=quality,
        missing_policy=MissingPolicy.FAIL_CLOSED,
        source_version="technical-v1",
        sector=sector,
        concept_basket=concept_basket,
    )


def test_attribution_summary_counts_quality_rank_sector_and_concept(tmp_path):
    repository = CrossSectionalFactorRepository(tmp_path / "factors.db")
    repository.save_snapshot(
        CrossSectionalFactorSnapshot(
            snapshot_id="csf_20260705_test",
            decision_date=date(2026, 7, 5),
            factor_set_version="v1.6-test",
            universe_id="test-universe",
            source_version="unit-test",
            rows=(
                _row(row_id="row-1", stock_code="2330", quantile_bp=10000),
                _row(
                    row_id="row-2",
                    stock_code="2317",
                    quantile_bp=0,
                    quality=FactorQuality.NEUTRAL,
                    sector="電子",
                    concept_basket=None,
                ),
            ),
            diagnostics=(
                CrossSectionalFactorDiagnostic(
                    code="factor.neutralized_missing",
                    message="factor is missing; neutralized",
                    factor_name="technical.total_score",
                    stock_code="2317",
                ),
            ),
        )
    )

    summary = build_cross_sectional_factor_attribution_summary(
        repository,
        snapshot_id="csf_20260705_test",
    )

    assert summary["snapshot_id"] == "csf_20260705_test"
    assert summary["row_count"] == 2
    assert summary["quality_counts"] == {"neutral": 1, "observed": 1}
    assert summary["rank_bucket_counts"] == {"0-2000": 1, "8001-10000": 1}
    assert summary["sector_counts"] == {"半導體": 1, "電子": 1}
    assert summary["concept_basket_counts"] == {"ai": 1, "missing": 1}
    assert summary["diagnostic_counts"] == {"factor.neutralized_missing": 1}
