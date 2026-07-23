import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from app_module.update_service import UpdateService
from ui_qt.views.update_view import UpdateView


class FakeConfig:
    def __init__(self, tmp_path: Path):
        self.use_sqlite = False
        self.data_root = tmp_path
        self.output_root = tmp_path / "output"
        self.profile = "test"
        self.log_dir = tmp_path / "logs"
        self.db_file = tmp_path / "test.db"
        self.meta_data_dir = tmp_path / "metadata"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.meta_data_dir.mkdir(parents=True, exist_ok=True)


def test_update_view_candidate_status_rendering(tmp_path):
    _app = QApplication.instance() or QApplication(sys.argv)
    mock_service = MagicMock()
    mock_service.config = FakeConfig(tmp_path)
    mock_service.scripts_dir = tmp_path / "scripts"

    view = UpdateView(update_service=mock_service)

    fake_status = {
        "institutional_flow": {
            "total_records": 1200,
            "earliest_date": "2024-07-22",
            "latest_date": "2026-07-22",
            "coverage_pct": "98.5%",
            "status": "CANDIDATE_AVAILABLE",
            "disclaimer": "候選研究資料，不參與評分",
        },
        "credit_transaction": {
            "total_records": 0,
            "earliest_date": "無",
            "latest_date": "無",
            "coverage_pct": "0.0%",
            "status": "MISSING",
            "disclaimer": "候選研究資料，不參與評分",
        },
        "tdcc_shareholding": {
            "total_records": 0,
            "earliest_date": "無",
            "latest_date": "無",
            "coverage_pct": "0.0%",
            "status": "MISSING",
            "disclaimer": "候選研究資料，不參與評分",
        },
    }

    view._on_status_checked(fake_status)

    inst_text = view.institutional_status_text.toPlainText()
    assert "CANDIDATE_AVAILABLE" in inst_text
    assert "2024-07-22" in inst_text
    assert "候選研究資料，不參與評分" in inst_text

    credit_text = view.credit_status_text.toPlainText()
    assert "MISSING" in credit_text
    assert "候選研究資料，不參與評分" in credit_text


def test_update_service_reads_only_explicit_candidate_db(monkeypatch, tmp_path):
    config = FakeConfig(tmp_path)
    candidate_db = tmp_path / "isolated_candidate.db"
    import sqlite3

    with sqlite3.connect(candidate_db) as conn:
        conn.execute("CREATE TABLE institutional_flows (decision_date TEXT)")
        conn.execute("INSERT INTO institutional_flows VALUES ('2024-07-22')")
        conn.execute(
            """
            CREATE TABLE phase3c_backfill_checkpoints (
                decision_date TEXT, source TEXT, status TEXT
            )
            """
        )
        conn.execute("INSERT INTO phase3c_backfill_checkpoints VALUES ('2024-07-22', 'institutional', 'SUCCESS')")

    monkeypatch.setenv("PHASE3C_CANDIDATE_DB_PATH", str(candidate_db))
    status = UpdateService(config).check_decision_data_status()

    assert status["institutional_flow"]["status"] == "CANDIDATE_AVAILABLE"
    assert status["institutional_flow"]["coverage_pct"] == "100.0%"
    assert status["credit_transaction"]["status"] == "MISSING"
