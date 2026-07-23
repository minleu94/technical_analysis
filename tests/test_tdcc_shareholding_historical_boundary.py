from datetime import date
from data_module.phase3c_backfill_runner import Phase3CBackfillRunner

def test_tdcc_shareholding_historical_boundary_blocked(tmp_path):
    cand_db = tmp_path / "candidate.db"
    runner = Phase3CBackfillRunner(
        candidate_db_path=cand_db,
        sources=("tdcc",),
        production_data_root=tmp_path / "fake_data",
        production_db_path=tmp_path / "fake_data" / "sqlite" / "twstock.db",
    )
    summary = runner.run_backfill(
        start_date=date(2024, 7, 22),
        end_date=date(2024, 7, 22),
        dry_run=True,
    )

    tdcc_results = [r for r in summary.daily_results if r["source"] == "tdcc"]
    assert len(tdcc_results) == 1
    assert tdcc_results[0]["status"] == "BLOCKED_NO_HISTORICAL_ENDPOINT"
    assert "僅提供最新單週公開資料" in summary.tdcc_historical_status
