"""Phase 3C 候選資料歷史回補執行器 (三大法人、信用交易與 TDCC 治理邊界)

本模組為受控、可中斷、可續跑、可審計的 Candidate Working-Copy 回補執行器。
嚴禁寫入正式資料庫 D:/Min/Python/Project/FA_Data/sqlite/twstock.db。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterable, Optional, Sequence

import pandas as pd

from data_module.official_phase3c_fetcher import (
    fetch_credit_transactions,
    fetch_institutional_flows,
    fetch_latest_tdcc_shareholding,
)
from data_module.official_trading_calendar import OfficialTradingCalendar
from data_module.p0_candidate_repository import (
    validate_candidate_working_copy_path,
)

logger = logging.getLogger(__name__)

APPLY_CONFIRM_TOKEN = "apply-phase3c-candidate-ingestion"
SUPPORTED_SOURCES = frozenset({"institutional", "credit", "tdcc"})
CANDIDATE_DB_PATH_ENV = "PHASE3C_CANDIDATE_DB_PATH"


def configured_candidate_db_path() -> Optional[Path]:
    """回傳使用者明確設定的 candidate DB；不猜測或建立路徑。

    Windows 已執行中的父程序不會自動吸收後來寫入 HKCU 的使用者環境
    變數。process environment 缺值時，只讀取同名的持久使用者環境設定，
    讓下一個 App 子程序不必依賴登出／重啟；兩者都沒有值時仍 fail closed。
    """

    raw_path = os.environ.get(CANDIDATE_DB_PATH_ENV, "").strip()
    if not raw_path:
        raw_path = _persisted_user_environment_value(CANDIDATE_DB_PATH_ENV)
    return Path(raw_path).expanduser() if raw_path else None


def _persisted_user_environment_value(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _value_type = winreg.QueryValueEx(key, name)
    except (ImportError, OSError):
        return ""
    return value.strip() if isinstance(value, str) else ""


@dataclass
class DailyFetchResult:
    decision_date: str
    source: str
    is_trading_day: Optional[bool]
    trading_day_reason: str
    status: str  # SUCCESS, SKIPPED_NOT_TRADING_DAY, SKIPPED_ALREADY_EXISTS, BLOCKED_NO_HISTORICAL_ENDPOINT, FAILED_RETRYABLE
    http_status: Optional[int]
    row_count: int
    error_message: Optional[str]
    fetched_at: str


@dataclass
class BackfillSummary:
    start_date: str
    end_date: str
    candidate_db_path: str
    dry_run: bool
    sources: list[str]
    total_days: int
    trading_days_count: int
    non_trading_days_count: int
    unknown_days_count: int
    succeeded_days_count: int
    skipped_days_count: int
    failed_days_count: int
    total_rows_inserted: int
    tdcc_historical_status: str
    started_at: str
    finished_at: str
    daily_results: list[dict]


class Phase3CBackfillRunner:
    """Phase 3C 候選資料受控回補執行器。"""

    def __init__(
        self,
        candidate_db_path: str | Path,
        *,
        sources: Sequence[str] = ("institutional", "credit"),
        production_data_root: Optional[str | Path] = None,
        production_db_path: Optional[str | Path] = None,
        rate_limit_seconds: float = 3.0,
        allow_online_calendar_probe: bool = False,
        include_latest_tdcc_snapshot: bool = False,
    ) -> None:
        root = production_data_root or os.environ.get("DATA_ROOT", "D:/Min/Python/Project/FA_Data")
        prod_db = production_db_path or Path(root) / "sqlite" / "twstock.db"
        self.candidate_db_path = validate_candidate_working_copy_path(
            candidate_db_path,
            production_data_root=root,
            production_db_path=prod_db,
        )
        self.sources = [s.strip().lower() for s in sources if s.strip()]
        invalid_sources = sorted(set(self.sources) - SUPPORTED_SOURCES)
        if not self.sources or invalid_sources:
            raise ValueError(
                "sources 必須為 institutional、credit、tdcc；"
                f"收到: {', '.join(invalid_sources) or '空集合'}"
            )
        self.rate_limit_seconds = max(0.0, rate_limit_seconds)
        self.allow_online_calendar_probe = allow_online_calendar_probe
        self.include_latest_tdcc_snapshot = include_latest_tdcc_snapshot
        self.calendar = OfficialTradingCalendar(db_path=prod_db)

    def _ensure_candidate_tables(self, conn: sqlite3.Connection) -> None:
        """建立 candidate working-copy 中的 Phase 3C 候選資料表與 checkpoint 表。"""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS institutional_flows (
                stock_code TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                source_version TEXT NOT NULL,
                publication_at TEXT,
                first_observed_at TEXT NOT NULL,
                available_at TEXT NOT NULL,
                available_date TEXT,
                quality TEXT NOT NULL,
                foreign_investor_buy INTEGER NOT NULL,
                foreign_investor_sell INTEGER NOT NULL,
                foreign_investor_net INTEGER NOT NULL,
                investment_trust_buy INTEGER NOT NULL,
                investment_trust_sell INTEGER NOT NULL,
                investment_trust_net INTEGER NOT NULL,
                dealer_buy INTEGER NOT NULL,
                dealer_sell INTEGER NOT NULL,
                dealer_net INTEGER NOT NULL,
                PRIMARY KEY (stock_code, decision_date)
            );

            CREATE TABLE IF NOT EXISTS credit_transactions (
                stock_code TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                source_version TEXT NOT NULL,
                publication_at TEXT,
                first_observed_at TEXT NOT NULL,
                available_at TEXT NOT NULL,
                available_date TEXT,
                quality TEXT NOT NULL,
                margin_purchase INTEGER NOT NULL,
                margin_balance INTEGER NOT NULL,
                short_sale INTEGER NOT NULL,
                short_balance INTEGER NOT NULL,
                financing INTEGER,
                securities_lending INTEGER,
                PRIMARY KEY (stock_code, decision_date)
            );

            CREATE TABLE IF NOT EXISTS tdcc_shareholding (
                stock_code TEXT NOT NULL,
                decision_date TEXT NOT NULL,
                source_version TEXT NOT NULL,
                publication_at TEXT,
                first_observed_at TEXT NOT NULL,
                available_at TEXT NOT NULL,
                available_date TEXT,
                quality TEXT NOT NULL,
                shareholding_tiers TEXT NOT NULL,
                large_holder_ratio_bp INTEGER NOT NULL,
                retail_holder_ratio_bp INTEGER NOT NULL,
                dispersion_index_bp INTEGER NOT NULL,
                PRIMARY KEY (stock_code, decision_date)
            );

            CREATE TABLE IF NOT EXISTS phase3c_backfill_checkpoints (
                decision_date TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                fetched_at TEXT NOT NULL,
                error_message TEXT,
                PRIMARY KEY (decision_date, source)
            );
            """
        )

    def is_date_already_completed(
        self, conn: sqlite3.Connection, decision_date_str: str, source: str
    ) -> bool:
        """只以成功 checkpoint 判定可續跑完成，失敗日必須可重試。"""
        checkpoint = conn.execute(
            """
            SELECT status FROM phase3c_backfill_checkpoints
            WHERE decision_date = ? AND source = ?
            """,
            (decision_date_str, source),
        ).fetchone()
        if checkpoint is not None:
            return str(checkpoint[0]) == "SUCCESS"

        # 相容於早期手動建立的 candidate DB：既有資料列不可覆寫。
        table_map = {
            "institutional": "institutional_flows",
            "credit": "credit_transactions",
            "tdcc": "tdcc_shareholding",
        }
        table_name = table_map.get(source)
        if not table_name:
            return False
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE decision_date = ? LIMIT 1",
            (decision_date_str,),
        )
        row = cursor.fetchone()
        return bool(row and row[0] > 0)

    @staticmethod
    def _record_checkpoint(
        conn: sqlite3.Connection,
        result: DailyFetchResult,
    ) -> None:
        """寫入可審計 checkpoint；FAILED_RETRYABLE 不會被視為完成。"""
        if result.status == "SKIPPED_ALREADY_EXISTS":
            # 不得將原本的 SUCCESS checkpoint 覆蓋成 skip 狀態。
            return
        conn.execute(
            """
            INSERT INTO phase3c_backfill_checkpoints (
                decision_date, source, status, row_count, fetched_at, error_message
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(decision_date, source) DO UPDATE SET
                status = excluded.status,
                row_count = excluded.row_count,
                fetched_at = excluded.fetched_at,
                error_message = excluded.error_message
            """,
            (
                result.decision_date,
                result.source,
                result.status,
                result.row_count,
                result.fetched_at,
                result.error_message,
            ),
        )

    @staticmethod
    def _validate_source_frame(
        frame: pd.DataFrame, source: str, decision_date_str: str
    ) -> None:
        required_columns = {
            "institutional": {
                "stock_code", "decision_date", "source_version", "first_observed_at",
                "available_at", "quality", "foreign_investor_buy", "foreign_investor_sell",
                "foreign_investor_net", "investment_trust_buy", "investment_trust_sell",
                "investment_trust_net", "dealer_buy", "dealer_sell", "dealer_net",
            },
            "credit": {
                "stock_code", "decision_date", "source_version", "first_observed_at",
                "available_at", "quality", "margin_purchase", "margin_balance",
                "short_sale", "short_balance",
            },
            "tdcc": {
                "stock_code", "decision_date", "source_version", "first_observed_at",
                "available_at", "quality", "shareholding_tiers",
                "large_holder_ratio_bp", "retail_holder_ratio_bp",
                "dispersion_index_bp",
            },
        }[source]
        missing = sorted(required_columns - set(frame.columns))
        if missing:
            raise ValueError(f"來源資料缺少必要欄位: {', '.join(missing)}")
        if frame["stock_code"].isna().any() or (frame["stock_code"].astype(str).str.strip() == "").any():
            raise ValueError("來源資料含空白 stock_code")
        normalized_dates = frame["decision_date"].astype(str)
        if not normalized_dates.eq(decision_date_str).all():
            raise ValueError("來源資料 decision_date 與請求日期不一致")
        if frame.duplicated(subset=["stock_code", "decision_date"]).any():
            raise ValueError("來源資料含重複 stock_code + decision_date")

    def run_backfill(
        self,
        start_date: date,
        end_date: date,
        *,
        dry_run: bool = True,
        confirm_token: Optional[str] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> BackfillSummary:
        """執行 Phase 3C 受控區間回補。"""
        started_at = datetime.now(timezone.utc).isoformat()

        if not dry_run:
            if confirm_token != APPLY_CONFIRM_TOKEN:
                raise ValueError(
                    f"apply 模式必須提供正確 confirm token: {APPLY_CONFIRM_TOKEN}"
                )
            self.candidate_db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.candidate_db_path)
            self._ensure_candidate_tables(conn)
        else:
            conn = None

        try:
            days_range = self.calendar.get_trading_days_in_range(
                start_date,
                end_date,
                allow_online_probe=self.allow_online_calendar_probe,
            )
            total_days = len(days_range)

            results: list[DailyFetchResult] = []
            total_rows_inserted = 0

            def append_result(result: DailyFetchResult) -> None:
                results.append(result)
                if conn is not None:
                    self._record_checkpoint(conn, result)
                    conn.commit()

            succeeded_count = 0
            skipped_count = 0
            failed_count = 0
            tdcc_result_recorded = False
            tdcc_historical_status = (
                "LATEST_SNAPSHOT_ENABLED；歷史日期仍 BLOCKED_NO_HISTORICAL_ENDPOINT"
                if self.include_latest_tdcc_snapshot and "tdcc" in self.sources
                else "BLOCKED_NO_HISTORICAL_ENDPOINT (僅提供最新單週公開資料)"
            )

            if self.include_latest_tdcc_snapshot and "tdcc" in self.sources:
                fetched_at = datetime.now(timezone.utc).isoformat()
                try:
                    time.sleep(self.rate_limit_seconds)
                    tdcc_frame = fetch_latest_tdcc_shareholding()
                    if tdcc_frame.empty:
                        raise ValueError("TDCC 最新單週官方端點未回傳候選資料")
                    unique_dates = sorted(
                        str(value)
                        for value in tdcc_frame["decision_date"].dropna().unique()
                    )
                    if len(unique_dates) != 1:
                        raise ValueError("TDCC 最新 snapshot 必須只有一個資料日")
                    snapshot_date = date.fromisoformat(unique_dates[0])
                    if snapshot_date > date.today() or snapshot_date > end_date:
                        raise ValueError("TDCC 最新 snapshot 日期晚於本次可接受日期")
                    snapshot_date_str = snapshot_date.isoformat()
                    self._validate_source_frame(
                        tdcc_frame,
                        "tdcc",
                        snapshot_date_str,
                    )
                    if conn is not None and self.is_date_already_completed(
                        conn,
                        snapshot_date_str,
                        "tdcc",
                    ):
                        result = DailyFetchResult(
                            decision_date=snapshot_date_str,
                            source="tdcc",
                            is_trading_day=None,
                            trading_day_reason="latest_weekly_snapshot",
                            status="SKIPPED_ALREADY_EXISTS",
                            http_status=None,
                            row_count=0,
                            error_message=None,
                            fetched_at=fetched_at,
                        )
                        skipped_count += 1
                    else:
                        if not dry_run and conn is not None:
                            tdcc_frame.to_sql(
                                "tdcc_shareholding",
                                conn,
                                if_exists="append",
                                index=False,
                            )
                            conn.commit()
                            total_rows_inserted += len(tdcc_frame)
                        result = DailyFetchResult(
                            decision_date=snapshot_date_str,
                            source="tdcc",
                            is_trading_day=None,
                            trading_day_reason="latest_weekly_snapshot",
                            status="SUCCESS",
                            http_status=None,
                            row_count=len(tdcc_frame),
                            error_message=None,
                            fetched_at=fetched_at,
                        )
                        succeeded_count += 1
                    append_result(result)
                except Exception as exc:
                    append_result(
                        DailyFetchResult(
                            decision_date=end_date.isoformat(),
                            source="tdcc",
                            is_trading_day=None,
                            trading_day_reason="latest_weekly_snapshot",
                            status="FAILED_RETRYABLE",
                            http_status=None,
                            row_count=0,
                            error_message=str(exc),
                            fetched_at=fetched_at,
                        )
                    )
                    failed_count += 1
                tdcc_result_recorded = True

            trading_days_count = sum(1 for d in days_range if d["is_trading_day"] is True)
            non_trading_days_count = sum(1 for d in days_range if d["is_trading_day"] is False)
            unknown_days_count = sum(1 for d in days_range if d["is_trading_day"] is None)

            for idx, day_info in enumerate(days_range):
                d_obj = day_info["date"]
                assert isinstance(d_obj, date)
                d_str = str(day_info["date_str"])
                is_td_raw = day_info["is_trading_day"]
                is_td: Optional[bool] = bool(is_td_raw) if is_td_raw is not None else None
                td_reason = str(day_info["reason_code"])

                pct = int(((idx + 1) / total_days) * 100) if total_days > 0 else 100
                if progress_callback:
                    progress_callback(f"處理 {d_str} ({idx + 1}/{total_days})...", pct)

                for src in self.sources:
                    fetched_at = datetime.now(timezone.utc).isoformat()

                    # TDCC 歷史邊界處理 (歷史日期不論交易日與否，均明確標示不支援歷史端點)
                    if src == "tdcc":
                        if tdcc_result_recorded:
                            continue
                        append_result(
                            DailyFetchResult(
                                decision_date=d_str,
                                source=src,
                                is_trading_day=is_td,
                                trading_day_reason=td_reason,
                                status="BLOCKED_NO_HISTORICAL_ENDPOINT",
                                http_status=None,
                                row_count=0,
                                error_message="TDCC 僅提供最新單週公開資料，不對歷史日期輪詢抓取",
                                fetched_at=fetched_at,
                            )
                        )
                        skipped_count += 1
                        continue

                    # 非官方交易日直接跳過
                    if is_td is False or is_td is None:
                        append_result(
                            DailyFetchResult(
                                decision_date=d_str,
                                source=src,
                                is_trading_day=is_td,
                                trading_day_reason=td_reason,
                                status="SKIPPED_NOT_TRADING_DAY",
                                http_status=None,
                                row_count=0,
                                error_message=None,
                                fetched_at=fetched_at,
                            )
                        )
                        skipped_count += 1
                        continue

                    # 斷點續跑檢查
                    if conn is not None and self.is_date_already_completed(conn, d_str, src):
                        append_result(
                            DailyFetchResult(
                                decision_date=d_str,
                                source=src,
                                is_trading_day=True,
                                trading_day_reason=td_reason,
                                status="SKIPPED_ALREADY_EXISTS",
                                http_status=None,
                                row_count=0,
                                error_message=None,
                                fetched_at=fetched_at,
                            )
                        )
                        skipped_count += 1
                        continue

                    # 實際連線抓取
                    try:
                        time.sleep(self.rate_limit_seconds)
                        df: Optional[pd.DataFrame] = None
                        if src == "institutional":
                            df = fetch_institutional_flows(d_obj)
                        elif src == "credit":
                            df = fetch_credit_transactions(d_obj)

                        if df is None or df.empty:
                            append_result(
                                DailyFetchResult(
                                    decision_date=d_str,
                                    source=src,
                                    is_trading_day=True,
                                    trading_day_reason=td_reason,
                                    status="FAILED_RETRYABLE",
                                    http_status=None,
                                    row_count=0,
                                    error_message="官方 API 無資料或連線失敗",
                                    fetched_at=fetched_at,
                                )
                            )
                            failed_count += 1
                        else:
                            self._validate_source_frame(df, src, d_str)
                            row_cnt = len(df)
                            if not dry_run and conn is not None:
                                table_name = (
                                    "institutional_flows"
                                    if src == "institutional"
                                    else "credit_transactions"
                                )
                                df.to_sql(table_name, conn, if_exists="append", index=False)
                                conn.commit()
                                total_rows_inserted += row_cnt

                            append_result(
                                DailyFetchResult(
                                    decision_date=d_str,
                                    source=src,
                                    is_trading_day=True,
                                    trading_day_reason=td_reason,
                                    status="SUCCESS",
                                    http_status=None,
                                    row_count=row_cnt,
                                    error_message=None,
                                    fetched_at=fetched_at,
                                )
                            )
                            succeeded_count += 1

                    except Exception as exc:
                        logger.error(f"抓取 {src} ({d_str}) 失敗: {exc}")
                        append_result(
                            DailyFetchResult(
                                decision_date=d_str,
                                source=src,
                                is_trading_day=True,
                                trading_day_reason=td_reason,
                                status="FAILED_RETRYABLE",
                                http_status=None,
                                row_count=0,
                                error_message=str(exc),
                                fetched_at=fetched_at,
                            )
                        )
                        failed_count += 1

            finished_at = datetime.now(timezone.utc).isoformat()
            summary = BackfillSummary(
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                candidate_db_path=str(self.candidate_db_path),
                dry_run=dry_run,
                sources=self.sources,
                total_days=total_days,
                trading_days_count=trading_days_count,
                non_trading_days_count=non_trading_days_count,
                unknown_days_count=unknown_days_count,
                succeeded_days_count=succeeded_count,
                skipped_days_count=skipped_count,
                failed_days_count=failed_count,
                total_rows_inserted=total_rows_inserted,
                tdcc_historical_status=tdcc_historical_status,
                started_at=started_at,
                finished_at=finished_at,
                daily_results=[asdict(r) for r in results],
            )

            # 寫入 summary 報告檔至非 tracked 輸出位置
            self._write_summary_report(summary)
            return summary

        finally:
            if conn is not None:
                conn.close()

    def _write_summary_report(self, summary: BackfillSummary) -> None:
        """產出結構化摘要報告 (JSON & Markdown) 至 Candidate DB 的同層 output 目錄。"""
        out_dir = self.candidate_db_path.parent / "backfill_reports"
        out_dir.mkdir(parents=True, exist_ok=True)

        dt_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = out_dir / f"phase3c_backfill_summary_{dt_tag}.json"
        md_path = out_dir / f"phase3c_backfill_summary_{dt_tag}.md"

        summary_dict = asdict(summary)
        json_path.write_text(
            json.dumps(summary_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        md_content = f"""# Phase 3C 候選資料回補執行摘要

- **執行時間**: `{summary.started_at}` ~ `{summary.finished_at}`
- **模式**: `{'DRY-RUN (唯讀測試)' if summary.dry_run else 'APPLY (寫入 Candidate DB)'}`
- **目標 Candidate DB**: `{summary.candidate_db_path}`
- **回補區間**: `{summary.start_date}` 至 `{summary.end_date}`
- **選擇來源**: `{', '.join(summary.sources)}`

## 交易日統計
- **總天數**: {summary.total_days}
- **官方交易日數**: {summary.trading_days_count}
- **休市日數**: {summary.non_trading_days_count}
- **未知／無證據日數**: {summary.unknown_days_count}

## 回補執行結果
- **成功完成日數**: {summary.succeeded_days_count}
- **跳過日數 (非交易日/已存在/TDCC邊界)**: {summary.skipped_days_count}
- **失敗待重試日數**: {summary.failed_days_count}
- **總寫入資料列數**: {summary.total_rows_inserted}
- **TDCC 歷史狀態**: `{summary.tdcc_historical_status}`

> [!IMPORTANT]
> **資料治理免責宣告**：本資料庫及寫入數據為 Phase 3C 候選研究資料 (Candidate Data)，絕不直接參與 ScoringEngine、Recommendation、Advice、Portfolio 或任何投資交易邏輯。
"""
        md_path.write_text(md_content, encoding="utf-8")
        logger.info(f"回補摘要報告已產出: {json_path}")
