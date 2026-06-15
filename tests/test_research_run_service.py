from pathlib import Path
from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app_module.research_run_dtos import ResearchRunMetadataDTO
from app_module.research_run_repository import ResearchRunConflictError, ResearchRunRepository
from decision_module.factors.factor_adapters import build_technical_total_score_factor
from data_module.config import TWStockConfig


def _config(tmp_path):
    return TWStockConfig(data_root=tmp_path / "data", output_root=tmp_path / "output")


def _metadata(run_id: str = "run-001", payload_hash: str = "sha256:payload"):
    return ResearchRunMetadataDTO(
        run_id=run_id,
        run_name="Research Run",
        run_type="single_backtest",
        strategy_id="baseline_score",
        payload_hash=payload_hash,
        created_at="2026-06-14T12:00:00",
    )


def _equity_frame():
    return pd.DataFrame(
        {
            "日期": ["2026-01-02", "2026-01-05"],
            "portfolio_value": [1000000, 1010000],
        }
    )


def _trades_frame():
    return pd.DataFrame(
        {
            "日期": ["2026-01-05"],
            "stock_code": ["2330"],
            "side": ["buy"],
            "quantity": [1000],
        }
    )


def test_save_run_is_immutable_and_idempotent(tmp_path):
    from app_module.research_run_service import ResearchRunService

    service = ResearchRunService(_config(tmp_path))

    saved = service.save_run(_metadata(), _equity_frame(), _trades_frame())
    second = service.save_run(_metadata(), _equity_frame(), _trades_frame())

    assert second == saved
    assert Path(saved.equity_path).exists()
    assert Path(saved.trades_path).exists()

    with pytest.raises(ResearchRunConflictError):
        service.save_run(_metadata(payload_hash="sha256:changed"), _equity_frame(), _trades_frame())


def test_save_run_persists_factor_snapshot_and_contributions(tmp_path):
    from app_module.research_run_service import ResearchRunService

    service = ResearchRunService(_config(tmp_path))
    factor_records = [
        build_technical_total_score_factor(
            stock_code="2330",
            as_of_date=date(2026, 6, 12),
            available_date=date(2026, 6, 12),
            total_score=Decimal("82.35"),
        )
    ]

    saved = service.save_run(
        _metadata(run_id="run-factor"),
        _equity_frame(),
        _trades_frame(),
        factor_records=factor_records,
        factor_decision_date=date(2026, 6, 14),
    )
    loaded = service.load_run_data(saved.run_id)

    assert loaded.metadata.factor_snapshot["records"][0]["factor_name"] == "technical.total_score"
    assert loaded.metadata.factor_contributions["by_stock"]["2330"][0]["score_bp"] == 8235
    assert loaded.metadata.factor_contributions["summary_by_factor"]["technical.total_score"][
        "accepted_count"
    ] == 1


def test_save_run_preserves_existing_manifest_when_explicit_factor_metadata_is_added(tmp_path):
    from app_module.research_run_service import ResearchRunService

    service = ResearchRunService(_config(tmp_path))
    metadata = ResearchRunMetadataDTO(
        run_id="run-explicit-factor",
        run_name="Research Run",
        run_type="single_backtest",
        payload_hash="sha256:explicit",
        data_manifest={"daily_prices": {"max_date": "2026-06-12"}},
        created_at="2026-06-14T12:00:00",
    )

    saved = service.save_run(
        metadata,
        _equity_frame(),
        _trades_frame(),
        factor_snapshot={"schema_version": 1, "records": []},
        factor_contributions={"schema_version": 1, "by_stock": {}},
    )

    assert saved.data_manifest["daily_prices"]["max_date"] == "2026-06-12"
    assert saved.factor_snapshot["schema_version"] == 1
    assert saved.factor_contributions["by_stock"] == {}


@pytest.mark.parametrize(
    "fail_at",
    [
        "before_temp_write",
        "after_temp_write",
        "after_hash",
        "after_staging_row",
        "after_first_rename",
        "after_second_rename",
        "before_final_commit",
    ],
)
def test_reconcile_recovers_or_marks_incomplete_save(tmp_path, fail_at):
    from app_module.research_run_service import InjectedResearchRunFailure, ResearchRunService

    config = _config(tmp_path)
    service = ResearchRunService(config)

    with pytest.raises(InjectedResearchRunFailure):
        service.save_run(_metadata(run_id=f"run-{fail_at}"), _equity_frame(), _trades_frame(), fail_at=fail_at)

    recovered_service = ResearchRunService(config)
    raw = ResearchRunRepository(config).get_raw_metadata_row(f"run-{fail_at}")

    if fail_at == "before_temp_write":
        assert raw is None
        return

    assert raw is not None
    assert raw["storage_state"] in {"committed", "failed"}
    if raw["storage_state"] == "committed":
        loaded = recovered_service.load_run_data(f"run-{fail_at}")
        assert loaded.equity.equals(_equity_frame())
        assert loaded.trades.equals(_trades_frame())
    else:
        assert raw["integrity_status"] == "failed"


def test_load_run_data_rejects_hash_mismatch(tmp_path):
    from app_module.research_run_service import ResearchRunIntegrityError, ResearchRunService

    service = ResearchRunService(_config(tmp_path))
    saved = service.save_run(_metadata(), _equity_frame(), _trades_frame())
    Path(saved.equity_path).write_text("tampered", encoding="utf-8")

    with pytest.raises(ResearchRunIntegrityError):
        service.load_run_data(saved.run_id)


def test_archive_run_is_soft_delete_and_default_list_excludes_it(tmp_path):
    from app_module.research_run_service import ResearchRunService

    service = ResearchRunService(_config(tmp_path))
    saved = service.save_run(_metadata(), _equity_frame(), _trades_frame())

    service.archive_run(saved.run_id)

    raw = ResearchRunRepository(service.config).get_raw_metadata_row(saved.run_id)
    assert raw["is_archived"] == 1
    assert Path(saved.equity_path).exists()
    assert Path(saved.trades_path).exists()
    assert service.list_runs() == []
    assert [run.run_id for run in service.list_runs(include_archived=True)] == [saved.run_id]


def test_archive_run_rejects_promoted_run(tmp_path):
    from app_module.research_run_service import PromotedResearchRunArchiveError, ResearchRunService

    service = ResearchRunService(_config(tmp_path))
    saved = service.save_run(_metadata(), _equity_frame(), _trades_frame())
    service.repository.mark_promoted(saved.run_id, "strategy-v1")

    with pytest.raises(PromotedResearchRunArchiveError):
        service.archive_run(saved.run_id)
