from pathlib import Path

from mcp_servers.project_context_server import (
    PROJECT_ROOT,
    build_twstock_config_snapshot,
    read_project_snapshot,
)


def test_build_twstock_config_snapshot_uses_twstock_config_paths(tmp_path, monkeypatch):
    data_root = tmp_path / "fa_data"
    output_root = tmp_path / "fa_output"
    monkeypatch.setenv("DATA_ROOT", str(data_root))
    monkeypatch.setenv("OUTPUT_ROOT", str(output_root))
    monkeypatch.setenv("PROFILE", "test")

    snapshot = build_twstock_config_snapshot()

    assert snapshot["profile"] == "test"
    assert snapshot["data_root"] == str(data_root / "_test")
    assert snapshot["output_root"] == str(output_root / "_test")
    assert snapshot["daily_price_dir"] == str(data_root / "_test" / "daily_price")
    assert snapshot["stock_data_file"] == str(
        data_root / "_test" / "meta_data" / "stock_data_whole.csv"
    )


def test_read_project_snapshot_reads_authoritative_file():
    snapshot = read_project_snapshot()

    assert snapshot["path"] == str(PROJECT_ROOT / "docs" / "00_core" / "PROJECT_SNAPSHOT.md")
    assert "可驗證" in snapshot["content"]
    assert snapshot["line_count"] > 0
