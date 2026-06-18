#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Background job: fetch TWSE + TPEX daily prices, sync SQLite, and recalculate technical indicators."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_module.update_service import UpdateService
from data_module.config import TWStockConfig


def _write_state(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _step(name: str, ok: bool, message: str, rows: int = 0, warnings: List[str] | None = None) -> Dict[str, Any]:
    return {
        "name": name,
        "status": "done" if ok else "failed",
        "message": message,
        "rows": rows,
        "warnings": warnings or [],
    }


def _parse_status_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _should_skip_technical_indicators(
    status: Dict[str, Any],
    *,
    force_all: bool,
) -> tuple[bool, str]:
    if force_all:
        return False, ""

    daily_latest = _parse_status_date((status.get("daily_data") or {}).get("latest_date"))
    technical_latest = _parse_status_date((status.get("technical_indicators") or {}).get("latest_date"))
    if daily_latest and technical_latest and technical_latest >= daily_latest:
        latest_text = technical_latest.strftime("%Y-%m-%d")
        return True, f"技術指標已是最新（{latest_text}），跳過增量計算"
    return False, ""


def _run_tpex_parallel(
    service: UpdateService,
    config: TWStockConfig,
    state_file: Path,
    state: Dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    workers: int,
) -> Dict[str, Any]:
    date_keys = service._iter_weekday_date_keys(start_date, end_date)
    source = service._create_tpex_daily_price_source()
    pending_dates = [
        date_key
        for date_key in date_keys
        if not (config.tpex_daily_price_dir / f"{date_key}.csv").exists()
    ]
    skipped_dates = [date_key for date_key in date_keys if date_key not in pending_dates]
    updated_dates: list[str] = []
    failed_dates: list[str] = []
    fallback_dates: list[str] = []
    total_rows = 0
    total_skipped_rows = 0
    total = len(pending_dates)

    if total == 0:
        return {
            "success": True,
            "message": "TPEX daily price CSV already complete for requested range",
            "requested_dates": date_keys,
            "updated_dates": [],
            "fallback_dates": [],
            "skipped_dates": skipped_dates,
            "failed_dates": [],
            "tpex_rows": 0,
            "skipped_rows": 0,
            "diagnostic_count": 0,
            "source_dates": [],
        }

    def fetch_one(date_key: str) -> Dict[str, Any]:
        result = source.update_for_date(date_key)
        return {
            "requested_date": date_key,
            "success": result.success,
            "source_date": result.source_date or date_key,
            "row_count": int(result.row_count),
            "skipped_count": int(result.skipped_count),
            "message": result.message,
        }

    completed = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {executor.submit(fetch_one, date_key): date_key for date_key in pending_dates}
        for future in as_completed(future_map):
            requested_date = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                failed_dates.append(requested_date)
                result = {"row_count": 0, "skipped_count": 0, "message": str(exc), "source_date": None}

            if result.get("success"):
                source_date = str(result.get("source_date") or requested_date)
                updated_dates.append(source_date)
                total_rows += int(result.get("row_count", 0))
                if source_date != requested_date:
                    fallback_dates.append(source_date)
            else:
                failed_dates.append(requested_date)
            total_skipped_rows += int(result.get("skipped_count", 0))
            completed += 1

            if completed == total or completed % 10 == 0:
                state["steps"]["tpex_daily"] = {
                    "status": "running",
                    "message": (
                        f"running {completed}/{total}; "
                        f"updated={len(set(updated_dates))}, failed={len(set(failed_dates))}, skipped={len(skipped_dates)}"
                    ),
                    "rows": len(set(updated_dates)),
                    "warnings": [],
                }
                state["tpex_progress"] = {
                    "completed": completed,
                    "total": total,
                    "workers": workers,
                    "updated": len(set(updated_dates)),
                    "failed": len(set(failed_dates)),
                    "skipped_existing": len(skipped_dates),
                }
                _write_state(state_file, state)

    unique_updated_dates = sorted(set(updated_dates))
    return {
        "success": bool(unique_updated_dates or skipped_dates),
        "message": "TPEX 每日股價區間更新完成" if unique_updated_dates or skipped_dates else "TPEX 每日股價區間更新失敗：無可寫入日期",
        "requested_dates": date_keys,
        "updated_dates": unique_updated_dates,
        "fallback_dates": sorted(set(fallback_dates)),
        "skipped_dates": sorted(set(skipped_dates)),
        "failed_dates": sorted(set(failed_dates)),
        "tpex_rows": total_rows,
        "skipped_rows": total_skipped_rows,
        "diagnostic_count": 0,
        "source_dates": unique_updated_dates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TPEX background refresh + technical indicators.")
    parser.add_argument("--start-date", required=True, help="開始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="結束日期 YYYY-MM-DD")
    parser.add_argument("--state-file", required=True, help="背景狀態 JSON 檔路徑")
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--sync-sqlite", action="store_true")
    parser.add_argument("--twse-update", action="store_true")
    parser.add_argument("--technical-force-all", action="store_true")
    parser.add_argument("--tpex-workers", type=int, default=1)
    args = parser.parse_args()

    state_file = Path(args.state_file)
    state: Dict[str, Any] = {
        "status": "running",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "tpex_full_refresh_and_technical",
        "start_date": args.start_date,
        "end_date": args.end_date,
        "steps": {
            "twse_daily": {"status": "pending", "message": "waiting", "rows": 0, "warnings": []},
            "tpex_daily": {"status": "pending", "message": "waiting", "rows": 0, "warnings": []},
            "sqlite": {"status": "pending", "message": "waiting", "rows": 0, "warnings": []},
            "technical": {"status": "pending", "message": "waiting", "rows": 0, "warnings": []},
        },
    }
    _write_state(state_file, state)

    # keep data-root stable for this job
    data_root = os.environ.get("DATA_ROOT")
    if data_root:
        os.environ["DATA_ROOT"] = data_root

    config = TWStockConfig()
    service = UpdateService(config)
    all_warnings: List[str] = []
    sync_rows = 0

    try:
        if args.twse_update:
            state["steps"]["twse_daily"] = {"status": "running", "message": "running", "rows": 0, "warnings": []}
            _write_state(state_file, state)

            twse_result = service.update_daily(args.start_date, args.end_date, delay_seconds=args.delay_seconds)
            state["steps"]["twse_daily"] = _step(
                "twse_daily",
                bool(twse_result.get("success", False)),
                twse_result.get("message", "TWSE 每日股價更新完成"),
                rows=len(twse_result.get("updated_dates", [])),
            )
            if not twse_result.get("success", False):
                all_warnings.append(f"TWSE 每日股價更新失敗：{twse_result.get('message', 'unknown')}")
            _write_state(state_file, state)
        else:
            state["steps"]["twse_daily"] = {
                "status": "skipped",
                "message": "已跳過 TWSE 更新（未指定 --twse-update）",
                "rows": 0,
                "warnings": [],
            }
            _write_state(state_file, state)

        state["steps"]["tpex_daily"] = {"status": "running", "message": "running", "rows": 0, "warnings": []}
        _write_state(state_file, state)
        if args.tpex_workers > 1:
            tpex_result = _run_tpex_parallel(
                service,
                config,
                state_file,
                state,
                start_date=args.start_date,
                end_date=args.end_date,
                workers=args.tpex_workers,
            )
        else:
            tpex_result = service.update_tpex_daily_price_range(
                args.start_date,
                args.end_date,
                delay_seconds=args.delay_seconds,
                force_refresh=False,
                break_on_repeated_source_date=False,
                sync_to_sqlite=False,
            )
        state["steps"]["tpex_daily"] = _step(
            "tpex_daily",
            bool(tpex_result.get("success", False)),
            tpex_result.get("message", "TPEX 每日股價更新完成"),
            rows=len(tpex_result.get("updated_dates", [])),
            warnings=(list(tpex_result.get("warnings", [])) if tpex_result.get("warnings") else []),
        )
        if not tpex_result.get("success", False):
            all_warnings.append(f"TPEX 每日股價更新失敗：{tpex_result.get('message', 'unknown')}")
        state["tpex_updated_dates"] = tpex_result.get("updated_dates", [])
        state["tpex_fallback_dates"] = tpex_result.get("fallback_dates", [])
        state["tpex_skipped_dates"] = tpex_result.get("skipped_dates", [])
        _write_state(state_file, state)

        if args.sync_sqlite:
            state["steps"]["sqlite"] = {"status": "running", "message": "running", "rows": 0, "warnings": []}
            _write_state(state_file, state)
            sync_result = service.sync_source_to_sqlite("daily_price_files", args.start_date, args.end_date)
            sync_rows = int(sync_result.get("synced_records", 0))
            state["steps"]["sqlite"] = _step(
                "sqlite",
                bool(sync_result.get("success", False)),
                sync_result.get("message", "SQLite 同步完成"),
                rows=sync_rows,
            )
            if not sync_result.get("success", False):
                all_warnings.append(f"SQLite 同步失敗：{sync_result.get('message', 'unknown')}")
            _write_state(state_file, state)
        else:
            state["steps"]["sqlite"] = {
                "status": "skipped",
                "message": "已跳過 SQLite 同步（未指定 --sync-sqlite）",
                "rows": 0,
                "warnings": [],
            }
            _write_state(state_file, state)

        status = service.check_data_overview() if hasattr(service, "check_data_overview") else service.check_data_status()
        should_skip_technical, skip_message = _should_skip_technical_indicators(
            status,
            force_all=args.technical_force_all,
        )
        if should_skip_technical:
            state["steps"]["technical"] = {
                "status": "skipped",
                "message": skip_message,
                "rows": 0,
                "warnings": [],
            }
            _write_state(state_file, state)
        else:
            state["steps"]["technical"] = {"status": "running", "message": "running", "rows": 0, "warnings": []}
            _write_state(state_file, state)
            tech_result = service.calculate_technical_indicators(
                target_stock=None,
                force_all=args.technical_force_all,
                start_date=None,
                progress_callback=None,
                incremental_lookback_days=120,
            )
            tech_stocks = tech_result.get("updated_stocks", [])
            tech_rows = len(tech_stocks) if isinstance(tech_stocks, list) else 0
            state["steps"]["technical"] = _step(
                "technical",
                bool(tech_result.get("success", False)),
                tech_result.get("message", "技術指標計算完成"),
                rows=tech_rows,
            )
            if not tech_result.get("success", False):
                all_warnings.append(f"技術指標計算失敗：{tech_result.get('message', 'unknown')}")
        _write_state(state_file, state)

        state["status"] = "done" if not all_warnings else "done_with_warning"
        state["warnings"] = all_warnings
        state["sqlite_synced_rows"] = sync_rows
        _write_state(state_file, state)
        return 0
    except Exception as exc:  # pragma: no cover - 防護性異常寫入
        state["status"] = "failed"
        state["message"] = f"背景任務執行失敗：{exc}"
        state["steps"] = state.get("steps", {})
        _write_state(state_file, state)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
