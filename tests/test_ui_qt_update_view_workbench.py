import os
import sys
import json
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QPushButton, QStackedWidget, QMessageBox, QDateEdit, QTextEdit
import pandas as pd

from ui_qt.views.update_view import StatusCard, UpdateView
from app_module.update_status_history import append_update_status_history
from data_module.p0_source_contract_registry import P0_SOURCE_IDS



class _TestableUpdateView(UpdateView):
    def _check_data_status(self):
        return None


class FakeConfig:
    def __init__(self):
        self.use_sqlite = False
        self.data_root = Path(".")
        self.output_root = Path(".")
        self.profile = "test"
        self.log_dir = Path(".")
        self.db_file = Path("test.db")

class FakeUpdateService:
    def __init__(self):
        self.calls = []
        self.config = FakeConfig()
        self.scripts_dir = Path("scripts")

    def export_table_to_csv(self, table_name, target_path, start_date=None, end_date=None):
        self.calls.append(("export_table_to_csv", table_name, target_path, start_date, end_date))
        return {"success": True, "message": "export ok"}

    def check_data_status(self):
        self.calls.append(("check_data_status",))
        return self.check_data_overview()

    def check_data_overview(self):
        self.calls.append(("check_data_overview",))
        return {
            "daily_data": {"latest_date": "2026-05-19", "total_records": 100, "status": "ok"},
            "market_index": {"latest_date": "2026-05-19", "total_records": 10, "status": "ok"},
            "industry_index": {"latest_date": "2026-05-19", "total_records": 20, "status": "ok"},
            "broker_branch": {"latest_date": "2026-05-19", "total_records": 30, "status": "ok"},
            "technical_indicators": {"latest_date": "2026-05-19", "total_records": 40, "status": "ok"},
            "monthly_revenue": {"latest_date": "2026-05", "total_records": 244499, "status": "ok"},
        }

    def check_source_detail(self, source):
        self.calls.append(("check_source_detail", source))
        return {"latest_date": "2026-05-19", "total_records": 1, "status": "ok"}

    def update_daily(self, start_date, end_date):
        self.calls.append(("update_daily", start_date, end_date))
        return {"success": True, "message": "daily ok"}

    def update_tpex_daily_price(self, target_date):
        self.calls.append(("update_tpex_daily_price", target_date))
        return {
            "success": True,
            "message": "tpex ok",
            "tpex_rows": 1,
            "skipped_rows": 0,
            "source_date": target_date.replace("-", ""),
        }

    def update_tpex_daily_price_range(
        self,
        start_date,
        end_date,
        delay_seconds=1.0,
        sync_to_sqlite=False,
        force_refresh=False,
        break_on_repeated_source_date=False,
        twse_no_data_dates=None,
    ):
        self.calls.append((
            "update_tpex_daily_price_range",
            start_date,
            end_date,
            delay_seconds,
            sync_to_sqlite,
            force_refresh,
            break_on_repeated_source_date,
        ))
        return {
            "success": True,
            "message": "tpex range ok",
            "tpex_rows": 1,
            "skipped_rows": 0,
            "source_date": end_date.replace("-", ""),
        }

    def update_market(self, start_date, end_date):
        self.calls.append(("update_market", start_date, end_date))
        return {"success": True, "message": "market ok"}

    def update_industry(self, start_date, end_date):
        self.calls.append(("update_industry", start_date, end_date))
        return {"success": True, "message": "industry ok"}

    def update_broker_branch(self, start_date, end_date):
        self.calls.append(("update_broker_branch", start_date, end_date))
        return {"success": True, "message": "broker ok"}

    def merge_daily_data(self, force_all=False):
        self.calls.append(("merge_daily_data", force_all))
        return {"success": True, "message": "merge daily ok"}

    def merge_broker_branch_data(self):
        self.calls.append(("merge_broker_branch_data",))
        return {"success": True, "message": "merge broker ok"}

    def calculate_technical_indicators(
        self,
        target_stock=None,
        force_all=False,
        start_date=None,
        progress_callback=None,
        incremental_lookback_days=120,
    ):
        self.calls.append((
            "calculate_technical_indicators",
            target_stock,
            force_all,
            start_date,
            incremental_lookback_days,
        ))
        if progress_callback:
            progress_callback("technical indicators ok", 100)
        return {"success": True, "message": "technical ok"}

    def sync_source_to_sqlite(self, source, start_date=None, end_date=None):
        self.calls.append(("sync_source_to_sqlite", source, start_date, end_date))
        return {"success": True, "message": f"{source} sync ok"}

    def dry_run_mops_monthly_revenue_backfill(
        self,
        snapshot_file=None,
        availability_file=None,
        source_version=None,
    ):
        self.calls.append((
            "dry_run_mops_monthly_revenue_backfill",
            str(snapshot_file) if snapshot_file else None,
            str(availability_file) if availability_file else None,
            source_version,
        ))
        return {
            "success": True,
            "ready_for_apply": True,
            "raw_row_count": 1848,
            "normalized_record_count": 1848,
            "diagnostic_count": 0,
            "message": "dry run ok",
        }

    def apply_mops_monthly_revenue_backfill(
        self,
        snapshot_file=None,
        availability_file=None,
        source_version=None,
    ):
        self.calls.append((
            "apply_mops_monthly_revenue_backfill",
            str(snapshot_file) if snapshot_file else None,
            str(availability_file) if availability_file else None,
            source_version,
        ))
        return {
            "success": True,
            "applied": True,
            "inserted_count": 1848,
            "backup_file": "backup.db",
            "message": "apply ok",
        }


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def make_view():
    app()
    return _TestableUpdateView(FakeUpdateService())


def _write_p0_evidence_audit(path: Path) -> Path:
    payload = {
        "schema_version": "p0-source-evidence-audit.v1",
        "safety_flags": {
            "formal_oos_allowed": False,
            "production_blend_alpha_bp": 0,
            "production_allowed": False,
            "scheduler_allowed": False,
            "downstream_eligibility": "none",
            "human_decision": "requires_human_acceptance",
        },
        "machine_evidence_matrix": [
            {
                "source_id": source_id,
                "machine_status": "verified",
                "availability": "network_probed",
                "pit_status": "official_publication_timestamp_missing",
                "raw_row_count": 4,
                "accepted_row_count": 3,
                "blocked_row_count": 1,
                "provider": "official",
                "acquisition_route_id": "route.primary",
                "fallback_used": source_id == "tdcc_shareholding",
                "fallback_from_acquisition_route_id": (
                    "route.legacy" if source_id == "tdcc_shareholding" else None
                ),
                "acquisition_routes": [
                    {"route_id": "route.legacy"},
                    {"route_id": "route.primary"},
                ],
            }
            for source_id in P0_SOURCE_IDS
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_p0_license_evidence(path: Path) -> Path:
    payload = {
        "schema_version": "p0-license-evidence-capture.v1",
        "candidate_only": True,
        "source_acceptance_granted": False,
        "license_accepted": False,
        "downstream_eligibility": "none",
        "formal_eligible": False,
        "production_ingestion_allowed": False,
        "production_scheduler_allowed": False,
        "targets": [
            {
                "license_evidence_url": "https://www.twse.com.tw/zh/terms/use.html",
                "source_ids": ["institutional_flows"],
                "status": "transport_error",
                "content_persisted": False,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_p0_partial_license_evidence(path: Path) -> Path:
    payload = json.loads(_write_p0_license_evidence(path).read_text(encoding="utf-8"))
    payload["targets"][0]["status"] = "captured"
    payload["targets"][0]["content_sha256"] = "a" * 64
    payload["targets"].append(
        {
            "license_evidence_url": (
                "https://www.tpex.org.tw/web/inc/gtsm_disclaimer.php?l=zh-tw"
            ),
            "source_ids": ["institutional_flows"],
            "status": "http_error",
            "content_persisted": False,
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_update_view_projects_p0_routes_fallback_and_pit_into_status_table(tmp_path):
    audit_path = _write_p0_evidence_audit(tmp_path / "p0-audit.json")
    app()
    view = _TestableUpdateView(
        FakeUpdateService(),
        p0_source_audit_path=audit_path,
    )

    status = view._get_overview_status()
    view._on_status_checked(status)

    p0 = status["p0_source_control"]
    assert p0["status"] == "research_shadow"
    assert p0["rows"][9]["fallback_used"] is True
    assert view.p0_source_control_table.rowCount() == 13
    assert "route.primary" in view.p0_source_control_table.item(9, 2).text()
    assert "route.legacy" in view.p0_source_control_table.item(9, 3).text()
    assert "official_publication_timestamp_missing" in view.p0_source_control_table.item(0, 4).text()
    assert "downstream_eligibility=none" in view.p0_source_control_summary_label.text()


def test_update_view_projects_license_candidate_capture_status(tmp_path):
    audit_path = _write_p0_evidence_audit(tmp_path / "p0-audit-license.json")
    license_path = _write_p0_license_evidence(tmp_path / "p0-license.json")
    app()
    view = _TestableUpdateView(
        FakeUpdateService(),
        p0_source_audit_path=audit_path,
        p0_license_evidence_path=license_path,
    )

    status = view._get_overview_status()
    view._on_status_checked(status)

    institutional = status["p0_source_control"]["rows"][7]
    assert institutional["license_evidence_capture_status"] == "capture_transport_error"
    license_cell = view.p0_source_control_table.item(7, 6)
    assert license_cell is not None
    assert "capture_transport_error" in license_cell.text()
    assert "License 候選證據" in view.p0_source_control_summary_label.text()


def test_update_view_explains_partial_license_candidate_capture(tmp_path):
    audit_path = _write_p0_evidence_audit(tmp_path / "p0-audit-license-partial.json")
    license_path = _write_p0_partial_license_evidence(
        tmp_path / "p0-license-partial.json"
    )
    app()
    view = _TestableUpdateView(
        FakeUpdateService(),
        p0_source_audit_path=audit_path,
        p0_license_evidence_path=license_path,
    )

    status = view._get_overview_status()
    view._on_status_checked(status)

    institutional = status["p0_source_control"]["rows"][7]
    assert institutional["license_evidence_capture_status"] == "capture_partial"
    license_cell = view.p0_source_control_table.item(7, 6)
    assert license_cell is not None
    assert "capture_partial" in license_cell.text()
    assert "部分取得，仍需複核" in license_cell.text()


def test_update_view_shows_rejected_fallback_reason_and_date_provenance(tmp_path):
    audit_path = _write_p0_evidence_audit(tmp_path / "p0-audit-fallback-diagnostics.json")
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    rows = payload["machine_evidence_matrix"]
    rows[7].update(
        {
            "fallback_used": False,
            "fallback_attempted": True,
            "fallback_endpoint_id": "tpex:openapi:institutional",
            "fallback_acquisition_route_id": "tpex.institutional",
            "fallback_probe_outcome": "network_error",
            "fallback_error_type": "RuntimeError",
            "fallback_error": "transport failed",
        }
    )
    rows[8].update(
        {
            "fallback_used": False,
            "fallback_attempted": True,
            "fallback_endpoint_id": "tpex:openapi:credit",
            "fallback_acquisition_route_id": "tpex.credit",
            "fallback_probe_outcome": "date_mismatch",
            "fallback_requested_date": "2026-08-28",
            "fallback_observation_dates": ["2026-08-27"],
        }
    )
    audit_path.write_text(json.dumps(payload), encoding="utf-8")

    app()
    view = _TestableUpdateView(
        FakeUpdateService(),
        p0_source_audit_path=audit_path,
    )
    status = view._get_overview_status()
    view._on_status_checked(status)

    institutional_cell = view.p0_source_control_table.item(7, 3)
    credit_cell = view.p0_source_control_table.item(8, 3)
    assert institutional_cell is not None
    assert credit_cell is not None
    assert "已嘗試但未採用" in institutional_cell.text()
    assert "network_error" in institutional_cell.text()
    assert "tpex.institutional" in institutional_cell.text()
    assert "transport failed" in institutional_cell.toolTip()
    assert "date_mismatch" in credit_cell.text()
    assert "要求日：2026-08-28" in credit_cell.text()
    assert "觀測日：2026-08-27" in credit_cell.text()
    assert "Fallback：已嘗試 3／已採用 1／未採用 2" in view.p0_source_control_summary_label.text()


def test_update_view_marks_missing_p0_artifact_as_unavailable(tmp_path):
    app()
    view = _TestableUpdateView(
        FakeUpdateService(),
        p0_source_audit_path=tmp_path / "not-found.json",
    )

    status = view._get_overview_status()
    view._on_status_checked(status)

    assert status["p0_source_control"]["status"] == "audit_unavailable"
    assert view.p0_source_control_table.rowCount() == 13
    assert "讀取問題" in view.p0_source_control_summary_label.text()
    assert "P0 稽核 artifact 不存在" in view.p0_source_control_summary_label.text()


def test_update_view_projects_explicit_data_update_timeline_and_steps(tmp_path):
    update_path = tmp_path / "update-status.json"
    freshness_path = tmp_path / "freshness-status.json"
    update_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "run_id": "run-20260828",
                "started_at": "2026-08-28T08:30:00+08:00",
                "completed_at": "2026-08-28T09:00:00+08:00",
                "end_date": "2026-08-28",
                "steps": [
                    {"name": "下載", "status": "passed", "message": "完成"},
                    {"name": "SQLite", "status": "passed", "message": "同步 10 筆"},
                ],
            }
        ),
        encoding="utf-8",
    )
    freshness_path.write_text(
        json.dumps({"status": "passed", "checked_at": "2026-08-28T09:05:00+08:00"}),
        encoding="utf-8",
    )
    view = _TestableUpdateView(
        FakeUpdateService(),
        data_update_status_path=update_path,
        data_freshness_status_path=freshness_path,
        tpex_status_path=tmp_path / "missing-tpex.json",
    )

    status = view._get_data_update_timeline()
    view._render_data_update_timeline(status)

    assert status["status"] == "current"
    assert "最後成功完成：2026-08-28T09:00:00+08:00" in view.data_update_timeline_summary_label.text()
    assert "目標資料日：2026-08-28" in view.data_update_timeline_summary_label.text()
    assert "明確路徑" in view.data_update_timeline_summary_label.text()
    assert view.data_update_timeline_table.rowCount() == 2
    assert view.data_update_timeline_table.item(1, 0).text() == "SQLite"
    assert UpdateView._timeline_status_text("date_mismatch") == "日期不符"
    assert UpdateView._timeline_status_text("official_no_data") == "官方無資料"
    assert UpdateView._timeline_status_color("official_no_data") == "#fbbf24"


def test_update_view_labels_p0_ratio_as_parser_acceptance_not_universe_coverage():
    view = make_view()

    assert view.p0_source_control_table.horizontalHeaderItem(5).text() == "解析通過率／Rows"
    display = view._format_p0_source_row(
        {
            "source_id": "institutional_flows",
            "label": "三大法人",
            "governance_status": "research_shadow",
            "machine_status": "verified",
            "acquisition_route_id": "twse.T86",
            "pit_status": "official_publication_timestamp_missing",
            "coverage_bp": 10000,
            "accepted_rows": 10,
            "observed_rows": 10,
            "blocked_rows": 0,
        }
    )

    assert "解析通過率 100.00%（accepted/observed）" in display[5]
    assert "accepted 10 / observed 10" in display[5]


def test_update_view_timeline_clears_old_steps_when_artifact_is_missing(tmp_path):
    view = _TestableUpdateView(
        FakeUpdateService(),
        data_update_status_path=tmp_path / "missing.json",
    )
    view._render_data_update_timeline(
        {
            "status": "current",
            "last_success_at": "2026-08-28T09:00:00+08:00",
            "steps": [{"name": "舊步驟", "status": "passed", "message": "舊結果"}],
            "diagnostics": [],
        }
    )
    assert view.data_update_timeline_table.rowCount() == 1

    missing = view._get_data_update_timeline()
    view._render_data_update_timeline(missing)

    assert missing["status"] == "missing"
    assert view.data_update_timeline_table.rowCount() == 0
    assert "最後成功完成：未提供" in view.data_update_timeline_summary_label.text()


def test_update_view_projects_append_only_data_update_history(tmp_path):
    update_path = tmp_path / "update-status.json"
    history_path = tmp_path / "history.jsonl"
    update_payload = {
        "status": "passed",
        "run_id": "run-current",
        "started_at": "2026-08-28T08:30:00+08:00",
        "completed_at": "2026-08-28T09:00:00+08:00",
        "start_date": "2026-08-17",
        "end_date": "2026-08-28",
        "steps": [],
    }
    update_path.write_text(json.dumps(update_payload), encoding="utf-8")
    append_update_status_history(
        history_path,
        {**update_payload, "status": "failed", "run_id": "run-old"},
        captured_at="2026-08-27T09:00:00+08:00",
    )
    append_update_status_history(
        history_path,
        update_payload,
        captured_at="2026-08-28T09:00:01+08:00",
    )

    view = _TestableUpdateView(
        FakeUpdateService(),
        data_update_status_path=update_path,
        data_update_history_path=history_path,
    )
    status = view._get_data_update_timeline()
    view._render_data_update_timeline(status)

    assert status["history"]["status"] == "current"
    assert status["history"]["record_count"] == 2
    assert "執行歷史：2 筆 append-only" in view.data_update_timeline_summary_label.text()
    assert view.data_update_timeline_history_table.rowCount() == 2
    assert view.data_update_timeline_history_table.item(0, 1).text() == "passed"
    assert view.data_update_timeline_history_table.item(0, 2).text() == "run-current"


def test_update_view_explains_missing_history_without_backfilling_latest(tmp_path):
    update_path = tmp_path / "update-status.json"
    update_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "run_id": "run-before-history",
                "started_at": "2026-08-28T08:30:00+08:00",
                "completed_at": "2026-08-28T09:00:00+08:00",
                "end_date": "2026-08-28",
                "steps": [],
            }
        ),
        encoding="utf-8",
    )
    history_path = tmp_path / "history.jsonl"
    freshness_path = tmp_path / "freshness-status.json"
    freshness_path.write_text(
        json.dumps({"status": "passed", "checked_at": "2026-08-28T09:05:00+08:00"}),
        encoding="utf-8",
    )
    view = _TestableUpdateView(
        FakeUpdateService(),
        data_update_status_path=update_path,
        data_update_history_path=history_path,
        data_freshness_status_path=freshness_path,
    )

    status = view._get_data_update_timeline()
    view._render_data_update_timeline(status)

    assert status["status"] == "current"
    assert status["history"]["status"] == "missing"
    summary = view.data_update_timeline_summary_label.text()
    assert "新版 runner 尚未產生" in summary
    assert "不回填舊 latest" in summary
    assert view.data_update_timeline_history_table.rowCount() == 0


def test_update_view_date_controls_use_taiwan_market_date(monkeypatch):
    monkeypatch.setattr(
        "ui_qt.views.update_view.taiwan_market_today",
        lambda: date(2026, 8, 28),
    )

    view = make_view()

    expected = QDate(2026, 8, 28)
    assert view.end_date.date() == expected
    for key in ("daily", "market", "industry", "broker_branch"):
        assert getattr(view, f"{key}_end_date").date() == expected

    view.daily_end_date.setDate(QDate(2026, 1, 1))
    view._set_shared_end_date_today("daily")
    assert view.daily_end_date.date() == expected
    assert view.end_date.date() == expected


def test_update_view_shows_structured_sqlite_sync_result():
    view = make_view()

    rendered = view._set_sqlite_sync_status(
        {
            "success": True,
            "source": "daily_price_files",
            "table": "daily_prices",
            "synced_records": 1234,
            "message": "daily_price_files 已同步 SQLite",
        }
    )

    assert "SQLite 同步：完成" in rendered
    assert "來源 daily_price_files" in view.sqlite_sync_status_label.text()
    assert "table daily_prices" in view.sqlite_sync_status_label.text()
    assert "1,234 筆" in view.sqlite_sync_status_label.text()


def test_update_view_cancel_control_requests_cooperative_write_shutdown():
    view = make_view()
    worker = DeferredTaskWorker(lambda: None)
    worker.cancel_calls = []

    def cancel(*, cooperative=True, wait=False):
        worker.cancel_calls.append((cooperative, wait))

    worker.cancel = cancel
    view._start_worker(worker, operation_kind="write")

    assert view.cancel_update_btn.isHidden() is False
    view._request_current_worker_cancel()
    assert worker.cancel_calls == [(True, False)]
    assert view.cancel_update_btn.isEnabled() is False

    worker._running = False
    worker.cancelled.emit()

    assert view.cancel_update_btn.isHidden() is True
    assert view._worker_coordinator.has_active("write") is False


def test_source_detail_check_renders_daily_status_inside_source_page():
    view = make_view()

    view._on_source_detail_checked({
        "source": "daily",
        "status": {
            "daily_data": {
                "latest_date": "2026-06-22",
                "total_records": 123456,
                "status": "ok",
                "csv_file_count": 2890,
                "missing_dates": ["2026-06-18"],
                "warnings": ["TWSE 休市日已略過"],
            }
        },
    })

    text = view.daily_detail_status_label.text()
    assert "最新日期：2026-06-22" in text
    assert "SQLite 筆數：123,456" in text
    assert "CSV 日檔數：2,890" in text
    assert "缺漏日期：2026-06-18" in text


def test_source_detail_check_renders_broker_branch_status_inside_source_page():
    view = make_view()

    view._on_source_detail_checked({
        "source": "broker_branch",
        "status": {
            "broker_branch": {
                "latest_date": "2026-06-22",
                "total_records": 98765,
                "date_count": 120,
                "dual_count": 55,
                "e_only_count": 10,
                "b_only_count": 5,
                "status": "warning",
            }
        },
    })

    text = view.broker_branch_detail_status_label.text()
    assert "最新日期：2026-06-22" in text
    assert "SQLite 筆數：98,765" in text
    assert "實際天數：120" in text
    assert "雙榜紀錄：55" in text


def test_force_merge_confirmation_uses_explicit_buttons_and_raw_csv_safety_copy(monkeypatch):
    view = make_view()
    captured = {}

    class CapturingMessageBox(QMessageBox):
        def exec(self):
            captured["text"] = self.text()
            captured["informative"] = self.informativeText()
            captured["buttons"] = [button.text() for button in self.buttons()]
            self._clicked_button = next(button for button in self.buttons() if "取消" in button.text())
            return QMessageBox.Cancel

        def clickedButton(self):
            return self._clicked_button

    monkeypatch.setattr("ui_qt.views.update_view.QMessageBox", CapturingMessageBox)

    view._execute_force_merge()

    assert "確認強制合併" in captured["buttons"]
    assert "取消" in captured["buttons"]
    assert "不會修改或刪除" in captured["informative"]
    assert "raw CSV 原始檔案" in captured["informative"]
    assert ("merge_daily_data", True) not in view.update_service.calls


def test_force_merge_confirmation_runs_merge_only_after_explicit_confirm(monkeypatch):
    view = make_view()
    calls = []
    monkeypatch.setattr(view, "_do_merge", lambda force_all=False: calls.append(force_all))

    class ConfirmingMessageBox(QMessageBox):
        def exec(self):
            self._clicked_button = next(button for button in self.buttons() if "確認強制合併" in button.text())
            return QMessageBox.Accepted

        def clickedButton(self):
            return self._clicked_button

    monkeypatch.setattr("ui_qt.views.update_view.QMessageBox", ConfirmingMessageBox)

    view._execute_force_merge()

    assert calls == [True]


def test_daily_merge_ui_surfaces_progress_callback(monkeypatch):
    from ui_qt.views import update_view

    class ProgressMergeService(FakeUpdateService):
        def merge_daily_data(self, force_all=False, progress_callback=None, cancel_callback=None):
            self.calls.append(("merge_daily_data", force_all))
            if progress_callback is not None:
                progress_callback("寫入每日整合檔", 42)
            return {"success": True, "message": "merge daily ok", "total_records": 2}

    class ProgressSynchronousTaskWorker(SynchronousTaskWorker):
        def start(self):
            self.started.emit()
            result = self.task_function(
                progress_callback=lambda message, percentage: self.progress.emit(message, percentage),
                cancel_callback=lambda: False,
            )
            self.finished.emit(result)

    monkeypatch.setattr(update_view, "ProgressTaskWorker", ProgressSynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)

    service = ProgressMergeService()
    view = make_view_with_service(service)
    view._do_merge(force_all=False)

    assert ("merge_daily_data", False) in service.calls
    assert "[每日合併 42%] 寫入每日整合檔" in view.log_text.toPlainText()
    assert view.progress_bar.maximum() == 100


def test_daily_merge_ui_distinguishes_no_op_from_completed_merge(monkeypatch):
    service = FakeUpdateService()
    view = make_view_with_service(service)
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, message: captured.update(title=title, message=message),
    )

    view._on_merge_finished(
        {
            "success": True,
            "no_op": True,
            "message": "沒有新資料需要合併；目前整合檔已是最新（最新日期：20260618）",
            "total_records": 1,
            "merged_files": 0,
        }
    )

    assert captured["title"] == "資料已是最新"
    assert "沒有新資料需要合併" in captured["message"]
    assert "未建立新的整合檔備份" in captured["message"]
    assert "無需合併" in view.log_text.toPlainText()
    assert "未建立新的整合檔備份" in view.log_text.toPlainText()


class StaleTechnicalUpdateService(FakeUpdateService):
    def check_data_overview(self):
        self.calls.append(("check_data_overview",))
        return {
            "daily_data": {"latest_date": "2026-05-20", "total_records": 100, "status": "ok"},
            "market_index": {"latest_date": "2026-05-19", "total_records": 10, "status": "ok"},
            "industry_index": {"latest_date": "2026-05-19", "total_records": 20, "status": "ok"},
            "broker_branch": {"latest_date": "2026-05-19", "total_records": 30, "status": "ok"},
            "technical_indicators": {"latest_date": "2026-05-19", "total_records": 40, "status": "ok"},
            "monthly_revenue": {"latest_date": "2026-05", "total_records": 244499, "status": "ok"},
        }


def make_view_with_service(service):
    app()
    return _TestableUpdateView(service)


def test_update_view_does_not_auto_scan_status_on_open():
    app()
    service = FakeUpdateService()

    view = UpdateView(service)

    assert service.calls == []
    assert view.check_status_btn.isEnabled()


def test_scheduler_page_explains_artifact_scope_and_disabled_production_write():
    view = make_view()
    labels = [label.text() for label in view.findChildren(QLabel)]
    joined = "\n".join(labels)

    assert "只讀取明確的 scheduled artifacts" in joined
    assert "production_scheduler_allowed=false" in joined
    assert "單一工作；非整體 Scheduler 狀態" in joined
    assert "Simulated/Waiting for time" not in joined


def test_update_view_uses_workbench_navigation():
    view = make_view()

    assert isinstance(view.nav_list, QListWidget)
    assert isinstance(view.content_stack, QStackedWidget)
    assert [key for key, _label in view._nav_items] == [
        "all",
        "daily",
        "market",
        "industry",
        "broker_branch",
        "technical",
        "monthly_revenue",
        "institutional_flow",
        "credit_transaction",
        "tdcc_shareholding",
        "scheduler_status",
        "db_inspector",
    ]
    assert view.content_stack.count() == 12
    assert view.nav_list.currentRow() == 0


def test_update_view_reflows_for_narrow_viewport_without_changing_navigation():
    view = make_view()
    view.show()
    view.resize(390, 844)
    app().processEvents()

    assert view.workbench_layout.direction().name == "TopToBottom"
    assert view.nav_list.width() >= view.content_stack.width() - 2
    assert view.nav_list.maximumHeight() == 190
    assert view._actions_layout.direction().name == "TopToBottom"
    assert view._cards_layout.getItemPosition(0)[:2] == (0, 0)
    assert view._cards_layout.getItemPosition(1)[:2] == (0, 1)
    assert view._cards_layout.getItemPosition(2)[:2] == (1, 0)
    assert view._candidate_layout.getItemPosition(0)[:2] == (0, 0)
    assert view._candidate_layout.getItemPosition(1)[:2] == (1, 0)
    assert view.content_scroll.verticalScrollBar().maximum() > 0

    view.resize(900, 844)
    app().processEvents()

    assert view.workbench_layout.direction().name == "LeftToRight"
    assert view.nav_list.width() == 160
    assert view.nav_list.maximumHeight() > 190
    assert view._actions_layout.direction().name == "LeftToRight"
    assert view._cards_layout.getItemPosition(0)[:2] == (0, 0)
    assert view._cards_layout.getItemPosition(5)[:2] == (0, 5)
    assert view._candidate_layout.getItemPosition(2)[:2] == (0, 2)


def test_tdcc_governance_page_exposes_latest_snapshot_candidate_command():
    view = make_view()

    tdcc_page = view.content_stack.widget(9)
    command_boxes = tdcc_page.findChildren(QTextEdit)

    assert any("--include-latest-tdcc" in box.toPlainText() for box in command_boxes)
    assert any("--sources tdcc" in box.toPlainText() for box in command_boxes)


def test_all_data_view_has_safe_update_primary_button():
    view = make_view()

    assert isinstance(view.quick_update_all_btn, QPushButton)
    assert view.quick_update_all_btn.text() == "快速更新 (跳過大型合併)"
    assert isinstance(view.safe_update_all_btn, QPushButton)
    assert view.safe_update_all_btn.text() == "安全更新 (完整 CSV + SQLite)"


def test_all_data_view_has_monthly_revenue_status_card():
    view = make_view()

    assert hasattr(view, "monthly_revenue_status_text")

    view._on_status_checked({
        "monthly_revenue": {
            "latest_date": "2026-06-30",
            "latest_period": "2026-06",
            "latest_available_period": "2026-05",
            "latest_available_date": "2026-06-17",
            "next_available_date": "2026-07-15",
            "pending_period_count": 1,
            "total_records": 246331,
            "status": "ok",
        }
    })

    text = view.monthly_revenue_status_text.toPlainText()
    assert "已匯入期別：2026-06" in text
    assert "目前可用期別：2026-05" in text
    assert "2026-07-15 起可用" in text
    assert "246,331" in text
    assert "月月營收資料" not in view.monthly_revenue_status_text.title_label.text()
    assert "月營收資料" in view.monthly_revenue_status_text.title_label.text()
    assert "最新可用日：" in view.monthly_revenue_status_text.date_label.text()
    assert "2026-06-17" in view.monthly_revenue_status_text.date_label.text()
    assert "2026-06" in view.monthly_revenue_status_text.extra_label.text()
    assert "目前可用期別：2026-05" in view.monthly_revenue_status_text.extra_label.text()
    assert "待生效：1 個期別（2026-07-15 起可用）" in view.monthly_revenue_status_text.extra_label.text()
    assert "最新" in view.monthly_revenue_status_text.indicator_label.text()


def test_status_card_explains_lagging_source_freshness():
    view = make_view()

    view._on_status_checked({
        "daily_data": {
            "latest_date": "2026-08-28",
            "total_records": 100,
            "status": "ok",
            "freshness_status": "reference",
            "freshness_reference_date": "2026-08-28",
        },
        "technical_indicators": {
            "latest_date": "2026-08-27",
            "total_records": 90,
            "status": "lagging",
            "freshness_status": "lagging",
            "freshness_reference_date": "2026-08-28",
        },
    })

    text = view.technical_status_text.toPlainText()
    assert "狀態：待更新" in text
    assert "新鮮度基準日：2026-08-28（資料最新日：2026-08-27）" in text
    assert "待更新" in view.technical_status_text.indicator_label.text()


def test_status_card_does_not_turn_green_for_latest_text_when_status_is_error():
    app()
    card = StatusCard("測試")

    card.setPlainText("最新可用日：2026-06-17\n狀態：error: no such table")

    assert "異常" in card.indicator_label.text()
    assert "#ef4444" in card.indicator_label.text()
    assert "#22c55e" not in card.indicator_label.text()


def test_status_card_marks_localized_unavailable_as_abnormal():
    app()
    card = StatusCard("測試")

    card.setPlainText("最新日期：未知\n狀態：不可用")

    assert "異常" in card.indicator_label.text()
    assert "#ef4444" in card.indicator_label.text()
    assert "待更新" not in card.indicator_label.text()


def test_global_status_error_clears_every_source_detail(monkeypatch):
    view = make_view()
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    sources = ("daily", "market", "industry", "broker_branch", "technical", "monthly_revenue")
    for source in sources:
        getattr(view, f"{source}_detail_status_label").setText("上一輪成功資料")

    view._on_status_error("SQLite 不可用")

    for source in sources:
        label_text = getattr(view, f"{source}_detail_status_label").text()
        assert "異常" in label_text
        assert "SQLite 不可用" in label_text
        assert "上一輪成功資料" not in label_text


def test_status_card_surfaces_immutable_snapshot_as_needs_confirmation():
    app()
    card = StatusCard("測試")

    card.setPlainText(
        "最新日期：2026-08-26\n"
        "總記錄數：10\n"
        "狀態：ok\n"
        "讀取模式：immutable_fallback\n"
        "提醒：可能只反映最後已提交內容"
    )

    assert "待更新" in card.indicator_label.text()
    assert "#eab308" in card.indicator_label.text()
    assert "immutable_fallback" in card.extra_label.text()
    assert "可能只反映" in card.extra_label.text()


def test_status_card_surfaces_parser_ratio_in_extra_summary():
    app()
    card = StatusCard("P0")

    card.setPlainText(
        "最新日期：2026-08-28\n"
        "總記錄數：10\n"
        "解析通過率：100%（accepted/observed）\n"
        "狀態：candidate_available"
    )

    assert "解析通過率：100%（accepted/observed）" in card.extra_label.text()


def test_status_card_placeholder_remains_unchecked_not_needs_update():
    app()
    card = StatusCard("測試")

    card.setPlainText("點擊「檢查數據狀態」以查看數據狀態")

    assert "未檢查" in card.indicator_label.text()
    assert "#94a3b8" in card.indicator_label.text()
    assert "待更新" not in card.indicator_label.text()


def test_update_view_progress_never_moves_backwards():
    view = make_view()

    view._reset_progress()
    view._on_update_progress("外層流程", 88)
    view._on_update_progress("子流程回報", 5)

    assert view.progress_bar.value() == 88
    assert view._last_progress == 88


def test_partial_status_payload_clears_stale_cards_instead_of_reusing_old_values():
    view = make_view()

    view._on_status_checked({
        "daily_data": {
            "latest_date": "2026-06-22",
            "total_records": 123,
            "status": "ok",
        }
    })

    assert "2026-06-22" in view.daily_status_text.toPlainText()
    assert "尚未檢查" in view.market_status_text.toPlainText()
    assert "#94a3b8" in view.market_status_text.indicator_label.text()
    assert view.market_detail_status_label.text() == "尚未檢查此資料源狀態"


def test_global_status_refresh_updates_inline_source_summaries_too():
    view = make_view()

    view._on_status_checked({
        "daily_data": {
            "latest_date": "2026-06-22",
            "total_records": 123,
            "status": "ok",
        },
        "broker_branch": {
            "latest_date": "2026-06-21",
            "total_records": 456,
            "date_count": 2,
            "status": "ok",
        },
    })

    assert "2026-06-22" in view.daily_detail_status_label.text()
    assert "2026-06-21" in view.broker_branch_detail_status_label.text()


def test_global_status_refresh_updates_all_core_source_inline_summaries():
    view = make_view()

    view._on_status_checked({
        "daily_data": {"latest_date": "2026-06-22", "total_records": 123, "status": "ok"},
        "market_index": {"latest_date": "2026-06-22", "total_records": 456, "status": "ok"},
        "industry_index": {"latest_date": "2026-06-21", "total_records": 789, "status": "lagging"},
        "broker_branch": {"latest_date": "2026-06-22", "total_records": 12, "status": "ok"},
        "technical_indicators": {
            "latest_date": "2026-06-22",
            "total_records": 345,
            "file_count": 6,
            "status": "ok",
        },
        "monthly_revenue": {
            "latest_date": "2026-06-30",
            "latest_period": "2026-06",
            "latest_available_period": "2026-05",
            "latest_available_date": "2026-06-17",
            "next_available_date": "2026-07-15",
            "pending_period_count": 1,
            "total_records": 246331,
            "status": "ok",
        },
    })

    assert "最新日期：2026-06-22" in view.market_detail_status_label.text()
    assert "狀態：待更新" in view.industry_detail_status_label.text()
    assert "指標檔數：6" in view.technical_detail_status_label.text()
    assert "目前可用期別：2026-05" in view.monthly_revenue_detail_status_label.text()
    assert "待生效：1 個期別（2026-07-15 起可用）" in view.monthly_revenue_detail_status_label.text()


def test_candidate_source_pages_render_global_status_inline():
    view = make_view()

    assert hasattr(view, "institutional_flow_detail_status_label")
    assert hasattr(view, "credit_transaction_detail_status_label")
    assert hasattr(view, "tdcc_shareholding_detail_status_label")

    view._on_status_checked({
        "institutional_flow": {
            "latest_date": "2026-06-22",
            "total_records": 321,
            "status": "candidate_available",
            "disclaimer": "候選研究資料，不參與評分",
        },
        "credit_transaction": {
            "latest_date": "2026-06-21",
            "total_records": 123,
            "status": "MISSING",
        },
        "tdcc_shareholding": {
            "latest_date": "2026-06-20",
            "total_records": 45,
            "status": "unavailable",
        },
    })

    assert "最新日期：2026-06-22" in view.institutional_flow_detail_status_label.text()
    assert "狀態：候選可用" in view.institutional_flow_detail_status_label.text()
    assert "狀態：缺漏" in view.credit_transaction_detail_status_label.text()
    assert "狀態：不可用" in view.tdcc_shareholding_detail_status_label.text()


def test_global_status_error_clears_candidate_source_inline_summaries(monkeypatch):
    view = make_view()
    view._on_status_checked({
        "institutional_flow": {
            "latest_date": "2026-06-22",
            "total_records": 321,
            "status": "candidate_available",
        },
        "credit_transaction": {
            "latest_date": "2026-06-21",
            "total_records": 123,
            "status": "candidate_available",
        },
        "tdcc_shareholding": {
            "latest_date": "2026-06-20",
            "total_records": 45,
            "status": "candidate_available",
        },
    })
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    view._on_status_error("candidate status timeout")

    for source in ("institutional_flow", "credit_transaction", "tdcc_shareholding"):
        label = getattr(view, f"{source}_detail_status_label")
        assert "狀態：異常" in label.text()
        assert "candidate status timeout" in label.text()


def test_source_detail_error_only_marks_the_requested_source(monkeypatch):
    view = make_view()
    view._on_status_checked({
        "daily_data": {
            "latest_date": "2026-06-22",
            "total_records": 123,
            "status": "ok",
        },
        "market_index": {
            "latest_date": "2026-06-22",
            "total_records": 456,
            "status": "ok",
        },
    })
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    view._on_source_detail_error("market", "network timeout")

    assert "2026-06-22" in view.daily_status_text.toPlainText()
    assert "最新" in view.daily_status_text.indicator_label.text()
    assert "error: network timeout" in view.market_status_text.toPlainText()
    assert "異常" in view.market_status_text.indicator_label.text()


def test_selected_date_range_uses_recent_ten_business_days_for_auto_updates():
    view = make_view()
    view.end_date.setDate(QDate(2026, 6, 30))
    view.lookback_days.setValue(10)

    assert view._get_selected_date_range() == ("2026-06-17", "2026-06-30")


def test_quick_update_all_uses_ten_business_day_window_for_daily_tpex_and_broker():
    view = make_view()
    view.update_service.config.use_sqlite = True
    view.end_date.setDate(QDate(2026, 6, 30))
    view.lookback_days.setValue(10)

    result = view._run_update_all(mode="quick", progress_callback=lambda message, pct: None)

    assert result["success"] is True
    assert ("update_daily", "2026-06-17", "2026-06-30") in view.update_service.calls
    assert any(
        call[:3] == ("update_tpex_daily_price_range", "2026-06-17", "2026-06-30")
        for call in view.update_service.calls
    )
    assert ("sync_source_to_sqlite", "daily_price_files", "2026-06-17", "2026-06-30") in view.update_service.calls
    assert ("update_broker_branch", "2026-06-17", "2026-06-30") in view.update_service.calls
    assert (
        "sync_source_to_sqlite",
        "broker_branch_files",
        "2026-06-17",
        "2026-06-30",
    ) in view.update_service.calls


def test_safe_update_all_uses_ten_business_day_window_for_core_sources():
    view = make_view()
    view.update_service.config.use_sqlite = True
    view.end_date.setDate(QDate(2026, 6, 30))
    view.lookback_days.setValue(10)

    result = view._run_update_all(mode="safe", progress_callback=lambda message, pct: None)

    assert result["success"] is True
    assert ("update_daily", "2026-06-17", "2026-06-30") in view.update_service.calls
    assert ("update_market", "2026-06-17", "2026-06-30") in view.update_service.calls
    assert ("update_industry", "2026-06-17", "2026-06-30") in view.update_service.calls
    assert ("update_broker_branch", "2026-06-17", "2026-06-30") in view.update_service.calls


def test_safe_update_all_skips_technical_when_current():
    view = make_view()
    progress = []

    result = view._run_safe_update_all(
        progress_callback=lambda message, pct: progress.append((message, pct))
    )

    assert result["success"] is True
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_overview",
        "update_daily",
        "update_tpex_daily_price_range",
        "sync_source_to_sqlite",
        "update_market",
        "sync_source_to_sqlite",
        "update_industry",
        "sync_source_to_sqlite",
        "update_broker_branch",
        "merge_daily_data",
        "sync_source_to_sqlite",
        "merge_broker_branch_data",
        "sync_source_to_sqlite",
        "check_data_overview",
        "check_data_overview",
    ]
    daily_call = next(call for call in view.update_service.calls if call[0] == "update_daily")
    assert any(
        call[:3] == ("update_tpex_daily_price_range", daily_call[1], daily_call[2])
        for call in view.update_service.calls
    )
    assert ("sync_source_to_sqlite", "daily_price_files", daily_call[1], daily_call[2]) in view.update_service.calls
    assert ("sync_source_to_sqlite", "market_index", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "industry_index", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "daily_data", None, None) in view.update_service.calls
    assert ("sync_source_to_sqlite", "broker_branch", None, None) in view.update_service.calls
    assert not any(call[0] == "calculate_technical_indicators" for call in view.update_service.calls)
    assert result["completed_steps"][-2]["result"]["skipped"] is True
    assert progress[0][1] == 0
    assert progress[-1][1] == 100


def test_safe_update_all_calculates_technical_when_stale():
    view = make_view_with_service(StaleTechnicalUpdateService())

    result = view._run_safe_update_all(progress_callback=lambda message, pct: None)

    assert result["success"] is True
    assert (
        "calculate_technical_indicators",
        None,
        False,
        None,
        120,
    ) in view.update_service.calls


def test_overview_check_uses_lightweight_service_contract():
    view = make_view()

    status = view._get_overview_status()

    assert status["daily_data"]["latest_date"] == "2026-05-19"
    assert view.update_service.calls == [("check_data_overview",)]


def test_source_detail_check_uses_detail_service_contract():
    view = make_view()

    detail = view._get_source_detail("broker_branch")

    assert detail == {"broker_branch": {"latest_date": "2026-05-19", "total_records": 1, "status": "ok"}}
    assert view.update_service.calls == [("check_source_detail", "broker_branch")]


def test_scheduler_detail_projection_updates_summary_and_raw_status_panel():
    view = make_view()

    view._render_source_detail_status(
        "scheduler_status",
        {
            "scheduler_status": {
                "status": "attention",
                "scheduler_state": "attention",
                "latest_date": "2026-08-28T12:00:00+00:00",
                "operation_count": 9,
                "core_ready_count": 2,
                "core_job_count": 6,
                "operational_count": 2,
                "guarded_count": 1,
                "attention_count": 5,
                "unavailable_count": 1,
                "scheduled_root": "C:/output/scheduled",
                "read_only": True,
                "operations": [],
            }
        },
    )

    summary = view.scheduler_status_detail_status_label.text()
    assert "排程狀態：需處理（attention）" in summary
    assert "核心工作就緒：2/6" in summary
    assert "邊界：唯讀" in summary
    assert "operation_count" in view.scheduler_status_log_box.toPlainText()


def test_source_tabs_have_operational_content():
    view = make_view()

    # 排除最後一個 db_inspector 頁面，因為它的 layout 與 widgets 結構不同
    for row in range(1, view.content_stack.count() - 1):
        page = view.content_stack.widget(row)
        labels = page.findChildren(QLabel)
        buttons = page.findChildren(QPushButton)

        assert len(labels) >= 2
        assert buttons


def test_source_date_controls_use_clear_calendar_buttons():
    view = make_view()

    for key in ("daily", "market", "industry", "broker_branch"):
        date_edit = getattr(view, f"{key}_end_date")
        assert isinstance(date_edit, QDateEdit)
        assert not date_edit.calendarPopup()

    buttons = [button.text() for button in view.findChildren(QPushButton)]
    assert buttons.count("日曆") >= 4


class FailingMarketService(FakeUpdateService):
    def update_market(self, start_date, end_date):
        self.calls.append(("update_market", start_date, end_date))
        return {"success": False, "message": "market failed"}


def test_safe_update_all_stops_after_failed_core_step():
    app()
    view = _TestableUpdateView(FailingMarketService())

    result = view._run_safe_update_all(progress_callback=lambda message, pct: None)

    assert result["success"] is False
    assert result["failed_step"] == "大盤指數更新"
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_overview",
        "update_daily",
        "update_tpex_daily_price_range",
        "sync_source_to_sqlite",
        "update_market",
    ]


class FailingTpexService(FakeUpdateService):
    def update_tpex_daily_price(self, target_date):
        self.calls.append(("update_tpex_daily_price", target_date))
        return {"success": False, "message": "tpex failed", "tpex_rows": 0}

    def update_tpex_daily_price_range(
        self,
        start_date,
        end_date,
        delay_seconds=1.0,
        sync_to_sqlite=False,
        force_refresh=False,
        break_on_repeated_source_date=False,
        twse_no_data_dates=None,
    ):
        self.calls.append((
            "update_tpex_daily_price_range",
            start_date,
            end_date,
            delay_seconds,
            sync_to_sqlite,
            force_refresh,
            break_on_repeated_source_date,
        ))
        return {"success": False, "message": "tpex failed", "tpex_rows": 0}


def test_safe_update_all_continues_but_reports_failure_when_tpex_fails_after_twse_success():
    app()
    view = _TestableUpdateView(FailingTpexService())

    result = view._run_safe_update_all(progress_callback=lambda message, pct: None)

    assert result["success"] is False
    assert result["failed_step"] == "TPEX 每日股價更新"
    assert result["warnings"] == ["TPEX 每日股價更新: tpex failed"]
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_overview",
        "update_daily",
        "update_tpex_daily_price_range",
        "sync_source_to_sqlite",
        "update_market",
        "sync_source_to_sqlite",
        "update_industry",
        "sync_source_to_sqlite",
        "update_broker_branch",
        "merge_daily_data",
        "sync_source_to_sqlite",
        "merge_broker_branch_data",
        "sync_source_to_sqlite",
        "check_data_overview",
        "check_data_overview",
    ]


def test_manual_daily_update_also_fetches_tpex_daily_price(monkeypatch):
    from ui_qt.views import update_view

    monkeypatch.setattr(update_view, "ProgressTaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view.daily_radio.setChecked(True)
    view.end_date.setDate(QDate(2026, 6, 16))
    view.lookback_days.setValue(10)

    view._execute_update()

    assert ("update_daily", "2026-06-06", "2026-06-16") in view.update_service.calls
    assert any(
        call[:3] == ("update_tpex_daily_price_range", "2026-06-06", "2026-06-16")
        for call in view.update_service.calls
    )


def test_update_view_with_config_instantiates_inspector_widget(tmp_path):
    from data_module.config import TWStockConfig
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    # 建立臨時路徑
    data_root = tmp_path / "data"
    output_root = tmp_path / "output"
    data_root.mkdir()
    output_root.mkdir()

    # 建立隔離的 config
    config = TWStockConfig(
        data_root=data_root,
        output_root=output_root,
        profile="test"
    )
    config.use_sqlite = True

    # 注入到 FakeUpdateService
    service = FakeUpdateService()
    service.config = config

    # 實例化 view
    app()
    view = _TestableUpdateView(service)

    # 驗證 sqlite_inspector_widget 是否被成功建立
    assert view.nav_list.count() == 12
    # 最後一頁應該是 SqliteInspectorWidget 的實例
    last_widget = view.content_stack.widget(11)
    assert isinstance(last_widget, SqliteInspectorWidget)


def test_background_tpex_refresh_does_not_force_technical_all(monkeypatch):
    from ui_qt.views import update_view

    captured = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            self.pid = 12345

        def poll(self):
            return None

    monkeypatch.setattr(update_view.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view._execute_background_tpex_refresh()

    assert "--sync-sqlite" in captured["cmd"]
    assert "--technical-force-all" not in captured["cmd"]


def test_background_tpex_status_is_visible_and_write_failure_is_fail_closed(monkeypatch, tmp_path):
    from ui_qt.views import update_view

    view = make_view()
    view.tpex_refresh_state_file = tmp_path / "state.json"
    view._write_tpex_background_status({"status": "running", "message": "fetching"})

    assert "執行中" in view.tpex_background_status_label.text()
    assert "fetching" in view.tpex_background_status_label.text()

    started = {"value": False}

    def fake_popen(*args, **kwargs):
        started["value"] = True
        raise AssertionError("狀態檔失敗時不應啟動背景程序")

    monkeypatch.setattr(update_view.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(view, "_write_tpex_background_status", lambda payload: False)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    view._execute_background_tpex_refresh()

    assert started["value"] is False
    assert view.tpex_background_btn.isEnabled()


def test_monthly_revenue_tab_runs_mops_dry_run(monkeypatch):
    from ui_qt.views import update_view

    monkeypatch.setattr(update_view, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view.monthly_revenue_snapshot_input.setText("snapshot.csv")
    view.monthly_revenue_availability_input.setText("availability.csv")

    view._execute_monthly_revenue_backfill(apply=False)

    assert view.update_service.calls[-1] == (
        "dry_run_mops_monthly_revenue_backfill",
        "snapshot.csv",
        "availability.csv",
        "mops-static-snapshot-monthly-revenue-2026-06-16",
    )


def test_monthly_revenue_tab_uses_user_facing_chinese_labels():
    view = make_view()

    labels = [label.text() for label in view.content_stack.widget(6).findChildren(QLabel)]
    buttons = [button.text() for button in view.content_stack.widget(6).findChildren(QPushButton)]

    assert "MOPS 月營收快照檔：" in labels
    assert "正式可得日對照檔：" in labels
    assert "本次寫入版本名稱：" in labels
    assert "先檢查，不寫入" in buttons
    assert "確認後寫入月營收" in buttons
    assert all("Dry-run" not in text for text in labels + buttons)
    assert all("SQLite" not in text for text in labels + buttons)
    assert all("source_version" not in text for text in labels + buttons)


def test_monthly_revenue_tab_requires_confirmation_before_apply(monkeypatch):
    from ui_qt.views import update_view

    monkeypatch.setattr(update_view, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view.monthly_revenue_snapshot_input.setText("snapshot.csv")
    view.monthly_revenue_availability_input.setText("availability.csv")

    view._execute_monthly_revenue_backfill(apply=True)

    assert any(call[0] == "apply_mops_monthly_revenue_backfill" for call in view.update_service.calls)

def test_safe_update_all_runs_conservative_sequence_sqlite():
    view = make_view()
    view.update_service.config.use_sqlite = True
    progress = []

    result = view._run_safe_update_all(
        progress_callback=lambda message, pct: progress.append((message, pct))
    )

    assert result["success"] is True
    assert [call[0] for call in view.update_service.calls] == [
        "check_data_overview",
        "update_daily",
        "update_tpex_daily_price_range",
        "sync_source_to_sqlite",
        "update_market",
        "sync_source_to_sqlite",
        "update_industry",
        "sync_source_to_sqlite",
        "update_broker_branch",
        "sync_source_to_sqlite",  # broker_branch_files 同步
        "check_data_overview",
        "check_data_overview",
    ]
    # 驗證同步的來源為 broker_branch_files
    assert ("sync_source_to_sqlite", "broker_branch_files", "2026-05-23", "2026-06-02") in view.update_service.calls or any(
        call[0] == "sync_source_to_sqlite" and call[1] == "broker_branch_files" for call in view.update_service.calls
    )


class FakeInspectorService:
    def __init__(self, total=250):
        self.total = total
        self.last_query = {}

    def is_enabled(self):
        return True

    def get_tables(self):
        return ["daily_prices", "broker_flows"]

    def get_distinct_column_values(self, table_name, column_name, limit=500):
        if table_name == "broker_flows" and column_name == "分點名稱":
            return ["凱基台北", "美商高盛"]
        return []

    def get_table_info(self, table_name):
        return {
            "success": True,
            "table_name": table_name,
            "total_records": self.total,
            "columns_count": 5,
            "earliest_date": "2026-05-01",
            "latest_date": "2026-05-30"
        }

    def get_table_schema(self, table_name):
        return pd.DataFrame([{"cid": 0, "name": "日期", "type": "TEXT"}])

    def query_table_data_count(self, **kwargs):
        return self.total

    def query_table_data(self, table_name, **kwargs):
        self.last_query = kwargs
        limit = kwargs.get("limit", 100)
        return pd.DataFrame([{"日期": f"2026-05-{i:02d}", "證券代號": "2330"} for i in range(min(limit, 10))])


class SynchronousTaskWorker:
    def __init__(self, task_function, *args, **kwargs):
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs

        class DummySignal:
            def __init__(self, name):
                self.name = name
                self.slots = []
            def connect(self, slot):
                self.slots.append(slot)
            def emit(self, *args):
                print(f"[DummySignal] emitting {self.name}")
                for slot in self.slots:
                    slot(*args)

        self.started = DummySignal("started")
        self.finished = DummySignal("finished")
        self.error = DummySignal("error")
        self.progress = DummySignal("progress")
        self.cancelled = DummySignal("cancelled")

    def start(self):
        try:
            print("[SynchronousTaskWorker] start called")
            self.started.emit()
            print("[SynchronousTaskWorker] calling task_function")
            result = self.task_function(*self.args, **self.kwargs)
            print("[SynchronousTaskWorker] task_function finished, emitting finished")
            self.finished.emit(result)
            print("[SynchronousTaskWorker] finished emitted successfully")
        except Exception as e:
            print(f"[SynchronousTaskWorker] error: {e}")
            self.error.emit(str(e))

    def isRunning(self):
        return False

    def disconnect(self):
        pass

    def wait(self):
        pass


class DeferredTaskWorker:
    instances = []

    def __init__(self, task_function, *args, **kwargs):
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs

        class DummySignal:
            def __init__(self):
                self.slots = []

            def connect(self, slot):
                self.slots.append(slot)

            def emit(self, *args):
                for slot in list(self.slots):
                    slot(*args)

        self.finished = DummySignal()
        self.error = DummySignal()
        self.cancelled = DummySignal()
        self._running = False
        DeferredTaskWorker.instances.append(self)

    def start(self):
        self._running = True

    def isRunning(self):
        return self._running

    def wait(self):
        self._running = False

    def disconnect(self):
        raise AssertionError("running workers must not be disconnected")


def test_update_view_detail_refresh_does_not_cancel_running_merge(monkeypatch):
    from ui_qt.views import update_view

    DeferredTaskWorker.instances = []
    monkeypatch.setattr(update_view, "ProgressTaskWorker", DeferredTaskWorker)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    view = make_view()
    view._execute_merge()
    merge_worker = DeferredTaskWorker.instances[-1]

    view._check_source_detail("market", force=True)

    assert merge_worker.isRunning()
    assert len(view._active_workers) == 2


def test_update_view_rejects_second_write_while_merge_is_running(monkeypatch):
    from ui_qt.views import update_view

    DeferredTaskWorker.instances = []
    monkeypatch.setattr(update_view, "ProgressTaskWorker", DeferredTaskWorker)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)

    view = make_view()
    view._execute_merge()
    first_worker = DeferredTaskWorker.instances[-1]

    view._execute_merge()

    assert len(DeferredTaskWorker.instances) == 1
    assert first_worker.isRunning()
    assert view._worker_coordinator.has_active("write") is True

    first_worker._running = False
    first_worker.finished.emit({"success": True, "message": "merge ok"})
    assert view._worker_coordinator.has_active("write") is False


def test_sqlite_inspector_rapid_requests_keep_running_workers_alive(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget

    DeferredTaskWorker.instances = []
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", DeferredTaskWorker)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    widget = SqliteInspectorWidget(FakeInspectorService(total=250))
    widget.current_table = "daily_prices"

    widget._request_page(load_schema=False)
    widget._request_page(load_schema=False)

    assert len(DeferredTaskWorker.instances) == 2
    assert len(widget._active_workers) == 2


def test_sqlite_inspector_next_page_uses_offset(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    app()
    print("[Test] app() initialized")
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None
    widget.current_table = "daily_prices"
    widget.page_size = 100
    widget.current_page = 2
    print("[Test] calling _request_page")
    widget._request_page(load_schema=False)
    print("[Test] _request_page returned")

    assert service.last_query.get("offset") == 100



def test_filter_reload_resets_to_first_page(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None
    widget.current_table = "daily_prices"
    widget.current_page = 4
    widget.stock_code_input.setText("2330")
    widget._load_current_table_data()

    assert widget.current_page == 1


def test_sqlite_inspector_uses_calendar_date_filters(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None
    widget.current_table = "daily_prices"

    assert isinstance(widget.date_input, QDateEdit)
    assert not widget.date_input.calendarPopup()
    assert widget.date_input.text().strip() == ""

    widget._request_page(load_schema=False)
    assert service.last_query.get("date_str") is None

    widget._set_single_date_today()
    widget._request_page(load_schema=False)
    assert service.last_query.get("date_str") == QDate.currentDate().toString("yyyy-MM-dd")

    widget.date_input.setDate(QDate(2026, 5, 29))
    widget._request_page(load_schema=False)
    assert service.last_query.get("date_str") == "2026-05-29"


def test_sqlite_inspector_date_pickers_default_blank_but_calendar_opens_today():
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    today = QDate.currentDate()

    assert widget._date_filter_value(widget.date_input) == ""
    assert widget._date_filter_value(widget.start_date_input) == ""
    assert widget._date_filter_value(widget.end_date_input) == ""
    assert widget.date_input.text().strip() == ""
    assert widget._calendar_page_date(widget.date_input) == today
    assert widget._calendar_page_date(widget.start_date_input) == today
    assert widget._calendar_page_date(widget.end_date_input) == today

    widget._set_single_date_today()
    widget.start_date_input.setDate(QDate(2026, 5, 1))
    widget.end_date_input.setDate(QDate(2026, 5, 29))
    widget._clear_all_dates()

    assert widget._date_filter_value(widget.date_input) == ""
    assert widget._date_filter_value(widget.start_date_input) == ""
    assert widget._date_filter_value(widget.end_date_input) == ""


def test_sqlite_inspector_date_pickers_have_enough_width_for_full_dates():
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    widget = SqliteInspectorWidget(FakeInspectorService(total=250))

    assert widget.date_input.minimumWidth() >= 122
    assert widget.start_date_input.minimumWidth() >= 122
    assert widget.end_date_input.minimumWidth() >= 122
    assert widget.date_input.maximumWidth() <= 132
    assert widget.start_date_input.maximumWidth() <= 132
    assert widget.end_date_input.maximumWidth() <= 132
    calendar_button_texts = [button.text() for button in widget.findChildren(QPushButton)]
    assert calendar_button_texts.count("日曆") >= 3


def test_sqlite_inspector_stock_filters_are_wide_enough_for_placeholders():
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget

    widget = SqliteInspectorWidget(FakeInspectorService(total=250))

    assert widget.stock_code_input.minimumWidth() >= 112
    assert widget.stock_code_input.maximumWidth() >= 112
    assert widget.stock_name_input.minimumWidth() >= 145
    assert widget.stock_name_input.maximumWidth() >= 145


def test_sqlite_inspector_broker_branch_filter_uses_dropdown(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None

    widget._on_table_changed("broker_flows")
    assert widget.broker_branch_combo.findText("凱基台北") >= 0
    assert widget.broker_branch_combo.maxVisibleItems() >= 20
    assert widget.broker_branch_dropdown_btn.text() == "展開"
    assert "#f8fafc" in widget.broker_branch_dropdown_btn.styleSheet()
    assert widget.broker_branch_dropdown_btn.minimumHeight() >= 26

    widget.broker_branch_combo.setCurrentText("凱基台北")
    widget._request_page(load_schema=False)

    assert service.last_query.get("broker_branch") == "凱基台北"


def test_sqlite_inspector_header_sort_requests_server_order(monkeypatch):
    from ui_qt.widgets import sqlite_inspector_widget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(sqlite_inspector_widget, "TaskWorker", SynchronousTaskWorker)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.Ok)

    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._adjust_table_header = lambda *args, **kwargs: None
    widget.current_table = "daily_prices"
    widget._request_page(load_schema=False)

    widget._on_preview_header_clicked(0)

    assert service.last_query.get("sort_column") == "日期"
    assert service.last_query.get("sort_order") == "asc"
    assert widget.current_page == 1





def test_pandas_table_model_handles_duplicate_display_columns_without_series_error():
    from ui_qt.models.pandas_table_model import PandasTableModel

    df = pd.DataFrame([[1, 2]], columns=["漲跌", "漲跌"])
    model = PandasTableModel(df)

    assert model.data(model.index(0, 0)) == "1"
    assert model.data(model.index(0, 1)) == "2"


def test_stale_worker_result_is_ignored():
    app()
    from ui_qt.widgets.sqlite_inspector_widget import SqliteInspectorWidget
    import pandas as pd
    service = FakeInspectorService(total=250)
    widget = SqliteInspectorWidget(service)
    widget._active_request_id = 2
    widget._on_table_data_loaded(
        {
            "request_id": 1,
            "table_name": "daily_prices",
            "load_schema": False,
            "info": None,
            "schema": None,
            "filtered_count": 0,
            "preview": pd.DataFrame(),
        }
    )
    assert widget.preview_model is None


