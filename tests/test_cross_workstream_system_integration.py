from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app_module.market_data_visibility_service import MarketDataVisibilityService
from app_module.ml_shadow_projection_dtos import (
    MLShadowPredictionProjectionDTO,
    MLShadowProjectionDTO,
)
from app_module.system_execution_blueprint_adapters import (
    SystemExecutionBlueprintAdapter,
)
from ml_module.feature_registry import CORE_LONG_HISTORY_FEATURE_REGISTRY
from ml_module.historical_contracts import HistoricalFeatureRow, HistoricalLabelRow
from ml_module.historical_dataset_builder import HistoricalDatasetBuilder
from ml_module.label_registry import CORE_LONG_HISTORY_LABEL_REGISTRY


ROOT = Path(__file__).resolve().parents[1]


def _seed_governed_source(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE daily_prices (
                股票代碼 TEXT NOT NULL,
                證券代號 TEXT NOT NULL,
                日期 TEXT NOT NULL,
                收盤價 TEXT
            );
            INSERT INTO daily_prices VALUES ('2330', '2330', '20240122', '100');
            CREATE TABLE fundamental_monthly_revenues (
                stock_code TEXT, period TEXT, as_of_date TEXT,
                announced_date TEXT, available_date TEXT, revenue TEXT,
                source TEXT, source_version TEXT, quality TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE institutional_flows (
                stock_code TEXT, decision_date TEXT, available_date TEXT,
                source_version TEXT, quality TEXT,
                foreign_investor_net INTEGER,
                investment_trust_net INTEGER, dealer_net INTEGER
            );
            CREATE TABLE credit_transactions (
                stock_code TEXT, decision_date TEXT, available_date TEXT,
                source_version TEXT, quality TEXT
            );
            CREATE TABLE tdcc_shareholding (
                stock_code TEXT, decision_date TEXT, available_date TEXT,
                source_version TEXT, quality TEXT
            );
            CREATE TABLE broker_flows (日期 TEXT, 證券代號 TEXT);
            """
        )


def _run_evidence_replay(tmp_path: Path) -> tuple[dict[str, object], Path, bytes]:
    source = tmp_path / "governed.sqlite3"
    _seed_governed_source(source)
    source_before = source.read_bytes()
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "scenario_id": "g-integration-chain",
                "decision_date": "2024-01-22",
                "tier": "engineering_fixture",
            }
        ),
        encoding="utf-8",
    )
    replay_summary = tmp_path / "replay-summary.json"
    replay_summary.write_text(
        json.dumps(
            {
                "replay_run_id": "g-replay",
                "available_date": "2024-01-22",
                "days": [{"decision_date": "2024-01-22"}],
            }
        ),
        encoding="utf-8",
    )
    output_root = tmp_path / "output"
    working_copy = tmp_path / "working" / "replay.sqlite3"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_evidence_rehearsal.py",
            "--execution-mode",
            "working_copy_e2e",
            "--scenario",
            str(scenario),
            "--source-db",
            str(source),
            "--working-copy-db",
            str(working_copy),
            "--replay-summary",
            str(replay_summary),
            "--output-root",
            str(output_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((output_root / "rehearsal-report.json").read_text(encoding="utf-8"))
    return report, source, source_before


def _build_research_only_dataset() -> object:
    feature = HistoricalFeatureRow(
        symbol="2330",
        decision_date="2024-01-22",
        feature_as_of_date="2024-01-19",
        available_date="2024-01-22",
        values=tuple(
            (spec.feature_id, index)
            for index, spec in enumerate(
                CORE_LONG_HISTORY_FEATURE_REGISTRY.specs, start=1
            )
        ),
    )
    labels = tuple(
        HistoricalLabelRow(
            symbol="2330",
            decision_date="2024-01-22",
            label_id=spec.label_id,
            value=index,
            horizon_end_date="2024-02-22",
            available_date="2024-02-23",
            maturity_status="ready",
            quality="degraded",
        )
        for index, spec in enumerate(
            CORE_LONG_HISTORY_LABEL_REGISTRY.specs, start=1
        )
    )
    return HistoricalDatasetBuilder().build(
        feature_rows=(feature,),
        labels=labels,
        training_as_of="2024-12-31",
        dataset_id="g-pit-safe-dataset",
        created_at="2026-07-13T00:00:00+00:00",
        source_fingerprints={"governed": "sha256:" + "a" * 64},
    )


def _shadow_projection() -> MLShadowProjectionDTO:
    prediction = MLShadowPredictionProjectionDTO(
        prediction_id="prediction:g:2330",
        symbol="2330",
        return_prediction_bp=125,
        ranking_score_bp=6500,
        downside_probability_bp=1800,
        uncertainty_bp=300,
    )
    return MLShadowProjectionDTO(
        decision_date="2025-01-03",
        model_id="model-g",
        dataset_id="g-pit-safe-dataset",
        status="shadow_available",
        predictions=(prediction,),
        blockers=(),
    )


def test_temp_sqlite_chain_preserves_read_only_and_fail_closed_truth(
    tmp_path: Path,
) -> None:
    evidence, source, source_before = _run_evidence_replay(tmp_path)
    dataset = _build_research_only_dataset()
    shadow = _shadow_projection()
    visibility = MarketDataVisibilityService(source).build_summary(
        as_of_date=date(2024, 1, 22)
    )

    snapshot = SystemExecutionBlueprintAdapter.compose(
        evidence_execution=evidence,
        dataset_manifest=dataset.manifest.to_dict(),
        dataset_formal_oos_allowed=dataset.formal_oos_allowed,
        shadow_projection=shadow,
        dashboard_visibility=visibility,
        broker_query={
            "limit_per_side": 50,
            "top_count": 0,
            "bottom_count": 0,
            "limit_pushed_down": True,
        },
        candidate_source_acceptance={
            "source_accepted": False,
            "license_accepted": False,
            "production_scheduler_allowed": False,
        },
        pit_eligibility={
            "formal_oos_allowed": False,
            "official_monthly_rows": 0,
            "official_quarterly_rows": 0,
            "corporate_coverage": "unknown",
        },
    )

    assert source.read_bytes() == source_before
    assert evidence["execution"]["source_db_write_performed"] is False
    assert evidence["execution"]["working_copy_write_performed"] is True
    assert dataset.manifest is not None
    assert dataset.manifest.decision_date_end <= "2024-12-31"
    assert dataset.formal_oos_allowed is False
    assert snapshot.formal_boundaries["production_blend_alpha_bp"] == 0
    assert snapshot.formal_boundaries["formal_rule_unchanged"] is True
    assert snapshot.formal_boundaries["production_action_allowed"] is False
    assert snapshot.dashboard_visibility["institutional_flows"]["quality"] == "MISSING"
    assert snapshot.external_pending == (
        "forward_evidence",
        "source_acceptance",
        "production_automation",
        "ml_promotion",
    )


@pytest.mark.parametrize(
    "override",
    (
        {"training_end_date": "2025-01-01"},
        {"max_train_label_available_date": "2025-01-01"},
        {"max_blend_selection_label_available_date": "2025-01-01"},
    ),
)
def test_time_boundaries_reject_2025_training_or_selection_data(
    override: dict[str, str],
) -> None:
    payload = {
        "training_end_date": "2024-12-31",
        "max_train_label_available_date": "2024-12-31",
        "max_blend_selection_label_available_date": "2024-12-31",
        "oos_start_date": "2025-01-01",
        "oos_end_date": "2025-12-31",
    }
    payload.update(override)

    with pytest.raises(ValueError, match="2024-12-31"):
        SystemExecutionBlueprintAdapter.verify_time_boundaries(payload)


def test_future_and_immature_rows_are_excluded_before_dataset_freeze() -> None:
    eligible = _build_research_only_dataset()
    feature = HistoricalFeatureRow(
        symbol="2330",
        decision_date="2024-01-22",
        feature_as_of_date="2024-01-19",
        available_date="2024-01-22",
        values=tuple(
            (spec.feature_id, index)
            for index, spec in enumerate(
                CORE_LONG_HISTORY_FEATURE_REGISTRY.specs, start=1
            )
        ),
    )
    immature = tuple(
        HistoricalLabelRow(
            symbol="2330",
            decision_date="2024-01-22",
            label_id=spec.label_id,
            value=None,
            horizon_end_date="2025-01-10",
            available_date="2025-01-10",
            maturity_status="pending",
            quality="degraded",
        )
        for spec in CORE_LONG_HISTORY_LABEL_REGISTRY.specs
    )
    blocked = HistoricalDatasetBuilder().build(
        feature_rows=(feature,),
        labels=immature,
        training_as_of="2024-12-31",
        dataset_id="blocked",
        created_at="2026-07-13T00:00:00+00:00",
        source_fingerprints={"governed": "sha256:" + hashlib.sha256(b"x").hexdigest()},
    )

    assert eligible.rows
    assert blocked.rows == ()
    assert blocked.excluded_diagnostics == {"immature_or_unavailable_label": 1}
