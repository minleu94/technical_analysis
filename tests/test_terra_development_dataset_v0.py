from __future__ import annotations

from pathlib import Path
from decimal import Decimal
from datetime import date, timedelta
import json
import sqlite3

import pytest

from development_module.contracts import DevelopmentDatasetManifest, DevelopmentGenerationRequest
from development_module.generation import TerraDevelopmentDatasetGenerator
from development_module.governance import load_development_data_usage_decision
from development_module.output_guard import validate_development_output_root
from development_module.source_adapter import CoreSourceAdapter, CoreSourceSnapshot
from development_module.universe import ConservativeObservedHistoryUniverse
from development_module.writer import DevelopmentArtifactWriter
from data_module.ml_historical_snapshot_provider import (
    HistoricalIndexObservation,
    HistoricalPriceObservation,
    HistoricalTechnicalObservation,
)


def test_output_root_rejects_data_root_and_accepts_explicit_external_root(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    formal_db = data_root / "sqlite" / "twstock.db"

    with pytest.raises(ValueError, match="development_output_root"):
        validate_development_output_root(
            data_root,
            data_root=data_root,
            formal_db=formal_db,
        )

    expected = (tmp_path / "development").resolve()
    assert validate_development_output_root(
        expected,
        data_root=data_root,
        formal_db=formal_db,
    ) == expected


def test_manifest_rejects_nonzero_production_alpha_or_formal_oos() -> None:
    with pytest.raises(ValueError, match="formal_oos_allowed"):
        DevelopmentDatasetManifest.minimal(formal_oos_allowed=True)

    with pytest.raises(ValueError, match="production_blend_alpha_bp"):
        DevelopmentDatasetManifest.minimal(production_blend_alpha_bp=1)


def test_usage_decision_requires_seen_oos_and_rejects_consumed_holdout(tmp_path: Path) -> None:
    output_root = tmp_path / "development"
    governance = output_root / "governance"
    governance.mkdir(parents=True)
    decision_path = governance / "DevelopmentDataUsageDecision.jsonl"
    decision_path.write_text(
        json.dumps({
            "decision": "seen_oos", "owner_provided_authorization": "owner",
            "year_2025_usage": "development_only", "new_holdout_start": "2026-07-15",
            "effective_timestamp_utc": "2026-07-14T05:07:25Z",
            "formal_oos_allowed": False, "production_blend_alpha_bp": 0,
            "development_output_root": str(output_root),
        }) + "\n",
        encoding="utf-8",
    )

    decision = load_development_data_usage_decision(decision_path, output_root=output_root)

    assert decision.new_holdout_start == "2026-07-15"
    (governance / "HoldoutConsumptionRegistry.jsonl").write_text(
        json.dumps({"trading_session": "2026-07-15"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="holdout"):
        load_development_data_usage_decision(decision_path, output_root=output_root)


def test_usage_decision_rejects_a_missing_effective_timestamp(tmp_path: Path) -> None:
    output_root = tmp_path / "development"
    governance = output_root / "governance"
    governance.mkdir(parents=True)
    decision_path = governance / "DevelopmentDataUsageDecision.jsonl"
    decision_path.write_text(
        json.dumps({
            "decision": "seen_oos", "owner_provided_authorization": "owner",
            "year_2025_usage": "development_only", "new_holdout_start": "2026-07-15",
            "formal_oos_allowed": False, "production_blend_alpha_bp": 0,
            "development_output_root": str(output_root),
        }) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="effective timestamp"):
        load_development_data_usage_decision(decision_path, output_root=output_root)


def test_writer_rejects_a_formal_data_root_even_for_direct_module_call(tmp_path: Path) -> None:
    formal_root = tmp_path / "formal"
    formal_db = formal_root / "sqlite" / "twstock.db"
    with pytest.raises(ValueError, match="development_output_root"):
        DevelopmentArtifactWriter(
            formal_root / "output",
            data_root=formal_root,
            formal_db=formal_db,
        )


def test_source_adapter_is_query_only_and_fingerprints_each_core_source(tmp_path: Path) -> None:
    database = tmp_path / "source.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            'CREATE TABLE daily_prices ("日期" TEXT, "證券代號" TEXT, "成交股數" INTEGER, '
            '"成交金額" INTEGER, "開盤價" TEXT, "最高價" TEXT, "最低價" TEXT, "收盤價" TEXT)'
        )
        connection.execute(
            'CREATE TABLE technical_indicators ("日期" TEXT, "證券代號" TEXT, '
            '"RSI" TEXT, "MACD" TEXT, "ADX" TEXT)'
        )
        connection.execute('CREATE TABLE market_indices ("日期" TEXT, "收盤指數" TEXT, "收盤價" TEXT)')
        connection.execute('CREATE TABLE industry_indices ("日期" TEXT, "指數名稱" TEXT, "收盤指數" TEXT)')
        connection.execute('INSERT INTO daily_prices VALUES ("20250102", "2330", 1, 2, "1", "1", "1", "1")')
        connection.execute('INSERT INTO technical_indicators VALUES ("20250102", "2330", "50", "0", "20")')
        connection.execute('INSERT INTO market_indices VALUES ("20250102", "100", NULL)')
        connection.execute('INSERT INTO industry_indices VALUES ("20250102", "半導體", "100")')
    before = database.stat()

    snapshot = CoreSourceAdapter(database).load("2025-01-01", "2026-12-31")

    assert snapshot.source_tables == (
        "daily_prices", "technical_indicators", "market_indices", "industry_indices"
    )
    assert set(snapshot.source_fingerprints) == set(snapshot.source_tables)
    assert snapshot.query_only is True
    assert database.stat().st_size == before.st_size
    assert database.stat().st_mtime_ns == before.st_mtime_ns


def test_conservative_universe_requires_252_prior_observed_days_and_reports_gaps() -> None:
    observations = tuple(
        HistoricalPriceObservation(
            symbol="2330",
            trading_date=f"2024-01-{day:02d}",
            open_price=Decimal("1"), high_price=Decimal("1"), low_price=Decimal("1"),
            close_price=Decimal("1"), volume=1, turnover_amount_minor=1,
        )
        for day in range(1, 253)
    ) + tuple(
        HistoricalPriceObservation(
            symbol="9999",
            trading_date=f"2024-01-{day:02d}",
            open_price=Decimal("1"), high_price=Decimal("1"), low_price=Decimal("1"),
            close_price=Decimal("1"), volume=1, turnover_amount_minor=1,
        )
        for day in range(1, 252)
    )

    selected, diagnostics = ConservativeObservedHistoryUniverse(252).select(
        observations,
        decision_date="2025-01-01",
    )

    assert selected == ("2330",)
    assert diagnostics["listing_date_unavailable"] == 2
    assert diagnostics["delisting_date_unavailable"] == 2
    assert diagnostics["insufficient_observed_history"] == 1


def _generation_snapshot() -> CoreSourceSnapshot:
    start = date(2024, 1, 1)
    prices: list[HistoricalPriceObservation] = []
    technicals: list[HistoricalTechnicalObservation] = []
    market: list[HistoricalIndexObservation] = []
    for offset in range(800):
        trading_date = (start + timedelta(days=offset)).isoformat()
        value = Decimal(100 + offset)
        prices.append(HistoricalPriceObservation(
            symbol="2330", trading_date=trading_date, open_price=value, high_price=value,
            low_price=value, close_price=value, volume=1000 + offset,
            turnover_amount_minor=10_000 + offset,
        ))
        technicals.append(HistoricalTechnicalObservation(
            symbol="2330", trading_date=trading_date, rsi=Decimal("50"),
            macd=Decimal("1"), adx=Decimal("20"),
        ))
        market.append(HistoricalIndexObservation("market", trading_date, value))
    return CoreSourceSnapshot(
        prices=tuple(prices), technicals=tuple(technicals), market=tuple(market), industries=(),
        source_fingerprints={
            "daily_prices": "sha256:" + "a" * 64,
            "technical_indicators": "sha256:" + "b" * 64,
            "market_indices": "sha256:" + "c" * 64,
            "industry_indices": "sha256:" + "d" * 64,
        },
    )


def _generation_request() -> DevelopmentGenerationRequest:
    return DevelopmentGenerationRequest(
        generation_id="terra-v0-test", decision_date_start="2025-11-01",
        decision_date_end="2026-01-05", training_as_of="2025-12-31",
        evaluation_as_of="2026-02-05", new_holdout_start="2026-07-15",
        usage_decision_sha256="sha256:" + "e" * 64,
    )


def test_generation_uses_t_minus_1_and_keeps_2025_fit_separate_from_2026_evaluation() -> None:
    result = TerraDevelopmentDatasetGenerator(_generation_snapshot()).generate(_generation_request())

    assert result.fit_rows
    assert result.evaluation_rows
    assert all(row.feature.feature_as_of_date < row.feature.decision_date for row in result.fit_rows)
    assert {row.feature.decision_date[:4] for row in result.fit_rows} == {"2025"}
    assert {row.feature.decision_date[:4] for row in result.evaluation_rows} == {"2026"}
    assert result.manifest.dataset_status == "research_only_degraded"
    assert result.manifest.formal_oos_allowed is False
    assert result.manifest.production_blend_alpha_bp == 0
    assert result.manifest.universe_policy_id == "conservative_observed_history"
    assert result.manifest.corporate_action_coverage == "research_only_degraded"
    assert result.manifest.corporate_action_blockers == ("corporate_action_coverage_missing",)


def test_writer_is_append_only_and_content_hash_is_deterministic(tmp_path: Path) -> None:
    result = TerraDevelopmentDatasetGenerator(_generation_snapshot()).generate(_generation_request())
    writer = DevelopmentArtifactWriter(
        tmp_path,
        data_root=tmp_path / "formal-data",
        formal_db=tmp_path / "formal-data" / "sqlite" / "twstock.db",
    )

    first = writer.write(result)

    with pytest.raises(FileExistsError):
        writer.write(result)
    assert first.manifest_path.exists()
    assert first.dataset_path.exists()
    assert result.manifest.content_hash.startswith("sha256:")
    assert result.manifest.content_hash == TerraDevelopmentDatasetGenerator(
        _generation_snapshot()
    ).generate(_generation_request()).manifest.content_hash


def test_generation_rejects_dates_at_or_after_the_new_holdout_start() -> None:
    request = DevelopmentGenerationRequest(
        generation_id="holdout-consumption", decision_date_start="2026-07-15",
        decision_date_end="2026-07-15", training_as_of="2025-12-31",
        evaluation_as_of="2026-08-31", new_holdout_start="2026-07-15",
        usage_decision_sha256="sha256:" + "e" * 64,
    )

    with pytest.raises(ValueError, match="new holdout"):
        TerraDevelopmentDatasetGenerator(_generation_snapshot()).generate(request)
