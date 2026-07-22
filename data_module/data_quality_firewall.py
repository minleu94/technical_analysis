"""Data Quality Firewall & PIT Safety Inspector for TWStock.

Non-destructive data quality governance:
1. Audits daily_prices for NULL stock_code, suspicious weekend dates, duplicate PKs, and invalid price bounds.
2. Audits market_indices for missing index names, classifying state as degraded rather than healthy.
3. Enforces PIT (Point-In-Time) availability safety on fundamental and valuation datasets to eliminate look-ahead bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Sequence

import pandas as pd


@dataclass(frozen=True)
class AnomalyItem:
    table_name: str
    primary_key: Dict[str, Any]
    anomaly_type: str
    severity: str  # BLOCKING, WARNING, ADVISORY
    row_hash: str
    cause_description: str
    recommended_action: str  # QUARANTINE_REJECT, QUARANTINE_ISOLATE, LOG_WARNING


@dataclass(frozen=True)
class DataQualityReport:
    audited_at: str
    total_records_checked: int
    anomalies_found: int
    blocking_anomalies_count: int
    warning_anomalies_count: int
    anomalies: Tuple[AnomalyItem, ...]
    status: str  # HEALTHY, DEGRADED, CRITICAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audited_at": self.audited_at,
            "total_records_checked": self.total_records_checked,
            "anomalies_found": self.anomalies_found,
            "blocking_anomalies_count": self.blocking_anomalies_count,
            "warning_anomalies_count": self.warning_anomalies_count,
            "status": self.status,
            "anomalies": [
                {
                    "table_name": item.table_name,
                    "primary_key": item.primary_key,
                    "anomaly_type": item.anomaly_type,
                    "severity": item.severity,
                    "row_hash": item.row_hash,
                    "cause_description": item.cause_description,
                    "recommended_action": item.recommended_action,
                }
                for item in self.anomalies
            ],
        }


@dataclass(frozen=True)
class PITEvaluationResult:
    is_usable: bool
    quality_status: str  # SAFE, DEGRADED, REJECTED
    reason_code: str
    ui_display_text: str
    decision_date: str
    available_date: Optional[str]
    announced_date: Optional[str]


class DataQualityFirewall:
    """Non-destructive data quality & PIT safety inspector."""

    def inspect_daily_prices(self, df: pd.DataFrame) -> DataQualityReport:
        """Inspect daily_prices DataFrame for data quality anomalies without modifying source data."""
        audited_at = datetime.now().isoformat()
        anomalies: List[AnomalyItem] = []

        if df.empty:
            return DataQualityReport(
                audited_at=audited_at,
                total_records_checked=0,
                anomalies_found=0,
                blocking_anomalies_count=0,
                warning_anomalies_count=0,
                anomalies=(),
                status="HEALTHY",
            )

        total_records = len(df)
        stock_col = "證券代號" if "證券代號" in df.columns else ("stock_code" if "stock_code" in df.columns else None)
        date_col = "日期" if "日期" in df.columns else ("date" if "date" in df.columns else None)

        if not stock_col or not date_col:
            anomaly = AnomalyItem(
                table_name="daily_prices",
                primary_key={},
                anomaly_type="MISSING_KEY_COLUMNS",
                severity="BLOCKING",
                row_hash="",
                cause_description=f"DataFrame missing essential stock/date columns. Found: {list(df.columns)}",
                recommended_action="QUARANTINE_REJECT",
            )
            return DataQualityReport(
                audited_at=audited_at,
                total_records_checked=total_records,
                anomalies_found=1,
                blocking_anomalies_count=1,
                warning_anomalies_count=0,
                anomalies=(anomaly,),
                status="CRITICAL",
            )

        # 1. NULL / Blank Stock Codes
        null_mask = df[stock_col].isna() | (df[stock_col].astype(str).str.strip() == "") | (df[stock_col].astype(str).str.lower() == "nan")
        null_indices = df[null_mask].index.tolist()
        for idx in null_indices[:100]:  # Cap sample
            row = df.loc[idx]
            d_val = str(row[date_col]) if date_col in row else ""
            row_hash = sha256(f"daily_prices_{idx}_{d_val}".encode("utf-8")).hexdigest()[:16]
            anomalies.append(
                AnomalyItem(
                    table_name="daily_prices",
                    primary_key={"index": idx, "date": d_val},
                    anomaly_type="NULL_STOCK_CODE",
                    severity="BLOCKING",
                    row_hash=row_hash,
                    cause_description="Stock code field is NULL, blank, or invalid",
                    recommended_action="QUARANTINE_REJECT",
                )
            )

        # 2. Duplicate Primary Keys (stock_code, date)
        valid_df = df[~null_mask].copy()
        dups = valid_df[valid_df.duplicated(subset=[stock_col, date_col], keep=False)]
        if not dups.empty:
            dup_keys = dups[[stock_col, date_col]].drop_duplicates()
            for _, r in dup_keys.iloc[:50].iterrows():
                scode = str(r[stock_col])
                dval = str(r[date_col])
                row_hash = sha256(f"dup_{scode}_{dval}".encode("utf-8")).hexdigest()[:16]
                anomalies.append(
                    AnomalyItem(
                        table_name="daily_prices",
                        primary_key={stock_col: scode, date_col: dval},
                        anomaly_type="DUPLICATE_PRIMARY_KEY",
                        severity="BLOCKING",
                        row_hash=row_hash,
                        cause_description=f"Duplicate primary key ({scode}, {dval}) found in daily_prices",
                        recommended_action="QUARANTINE_ISOLATE",
                    )
                )

        # 3. Weekend dates check
        for idx, row in valid_df.iterrows():
            d_str = str(row[date_col]).replace("-", "").strip()
            if len(d_str) == 8 and d_str.isdigit():
                try:
                    dt = datetime.strptime(d_str, "%Y%m%d")
                    if dt.weekday() in (5, 6):
                        scode = str(row[stock_col])
                        row_hash = sha256(f"weekend_{scode}_{d_str}".encode("utf-8")).hexdigest()[:16]
                        anomalies.append(
                            AnomalyItem(
                                table_name="daily_prices",
                                primary_key={stock_col: scode, date_col: d_str},
                                anomaly_type="SUSPICIOUS_WEEKEND_DATE",
                                severity="WARNING",
                                row_hash=row_hash,
                                cause_description=f"Trading date {d_str} falls on a weekend (Saturday/Sunday)",
                                recommended_action="LOG_WARNING",
                            )
                        )
                except ValueError:
                    pass

        # 4. Invalid price bounds check (Decimal hardened comparison)
        close_col = "收盤價" if "收盤價" in df.columns else ("close" if "close" in df.columns else None)
        high_col = "最高價" if "最高價" in df.columns else ("high" if "high" in df.columns else None)
        low_col = "最低價" if "最低價" in df.columns else ("low" if "low" in df.columns else None)

        if close_col and high_col and low_col:
            for idx, row in valid_df.iterrows():
                try:
                    c = Decimal(str(row[close_col]).strip())
                    h = Decimal(str(row[high_col]).strip())
                    l = Decimal(str(row[low_col]).strip())
                    if c <= Decimal("0") or h < l or c > h or c < l:
                        scode = str(row[stock_col])
                        dval = str(row[date_col])
                        row_hash = sha256(f"bounds_{scode}_{dval}".encode("utf-8")).hexdigest()[:16]
                        anomalies.append(
                            AnomalyItem(
                                table_name="daily_prices",
                                primary_key={stock_col: scode, date_col: dval},
                                anomaly_type="INVALID_PRICE_BOUNDS",
                                severity="BLOCKING",
                                row_hash=row_hash,
                                cause_description=f"Price boundary violation (Close: {c}, High: {h}, Low: {l})",
                                recommended_action="QUARANTINE_ISOLATE",
                            )
                        )
                except (ValueError, TypeError, InvalidOperation):
                    pass

        blocking_count = sum(1 for a in anomalies if a.severity == "BLOCKING")
        warning_count = sum(1 for a in anomalies if a.severity == "WARNING")
        status = "CRITICAL" if blocking_count > 0 else ("DEGRADED" if warning_count > 0 else "HEALTHY")

        return DataQualityReport(
            audited_at=audited_at,
            total_records_checked=total_records,
            anomalies_found=len(anomalies),
            blocking_anomalies_count=blocking_count,
            warning_anomalies_count=warning_count,
            anomalies=tuple(anomalies),
            status=status,
        )

    def inspect_market_indices(self, df: pd.DataFrame) -> Tuple[str, str, Dict[str, Any]]:
        """Audit market_indices table columns and rows, returning (status, description, details)."""
        if df.empty:
            return "DEGRADED", "market_indices table is empty", {"row_count": 0}

        cols = list(df.columns)
        has_canonical_name = "指數名稱" in cols
        close_col = "收盤指數" if "收盤指數" in cols else ("收盤價" if "收盤價" in cols else None)

        if not close_col:
            return "CRITICAL", "market_indices missing OHLC price columns", {"columns": cols}

        if not has_canonical_name:
            return "DEGRADED", "market_indices missing canonical '指數名稱' column, using legacy fallback", {
                "columns": cols,
                "fallback_column": close_col,
            }

        null_names = df["指數名稱"].isna() | (df["指數名稱"].astype(str).str.strip() == "")
        null_count = int(null_names.sum())

        if null_count > 0:
            return "DEGRADED", f"market_indices has {null_count}/{len(df)} rows with missing index names (OHLC usable via fallback)", {
                "null_name_count": null_count,
                "total_rows": len(df),
                "fallback_column": close_col,
            }

        return "HEALTHY", "market_indices fully canonical and complete", {"total_rows": len(df)}

    def evaluate_pit_availability(
        self,
        decision_date: str,
        available_date: Optional[str],
        announced_date: Optional[str] = None,
        *,
        require_announced_date: bool = False,
    ) -> PITEvaluationResult:
        """Evaluate whether a fundamental or corporate record is usable at decision_date without look-ahead bias."""
        dec_clean = decision_date.replace("-", "").strip()

        if not available_date or not str(available_date).strip() or str(available_date).lower() == "none":
            return PITEvaluationResult(
                is_usable=False,
                quality_status="REJECTED",
                reason_code="PIT_AVAILABLE_DATE_MISSING",
                ui_display_text="拒絕使用：未具備明確可得日 (available_date 缺失)",
                decision_date=decision_date,
                available_date=available_date,
                announced_date=announced_date,
            )

        avail_clean = str(available_date).replace("-", "").strip()

        if len(avail_clean) != 8 or not avail_clean.isdigit():
            return PITEvaluationResult(
                is_usable=False,
                quality_status="REJECTED",
                reason_code="PIT_INVALID_DATE_FORMAT",
                ui_display_text="拒絕使用：可得日格式無效",
                decision_date=decision_date,
                available_date=available_date,
                announced_date=announced_date,
            )

        if avail_clean > dec_clean:
            return PITEvaluationResult(
                is_usable=False,
                quality_status="REJECTED",
                reason_code="PIT_FUTURE_LOOK_AHEAD",
                ui_display_text=f"拒絕使用：未來資料偏誤 (可得日 {avail_clean} > 決策日 {dec_clean})",
                decision_date=decision_date,
                available_date=available_date,
                announced_date=announced_date,
            )

        if require_announced_date and not announced_date:
            return PITEvaluationResult(
                is_usable=False,
                quality_status="REJECTED",
                reason_code="PIT_ANNOUNCED_DATE_MISSING",
                ui_display_text="拒絕使用：此基本面資料缺少可驗證的公告日 provenance",
                decision_date=decision_date,
                available_date=available_date,
                announced_date=announced_date,
            )

        if announced_date:
            ann_clean = str(announced_date).replace("-", "").strip()
            if len(ann_clean) != 8 or not ann_clean.isdigit():
                return PITEvaluationResult(
                    is_usable=False,
                    quality_status="REJECTED",
                    reason_code="PIT_ANNOUNCED_DATE_INVALID",
                    ui_display_text="拒絕使用：公告日格式無效，無法驗證資料在決策日可得",
                    decision_date=decision_date,
                    available_date=available_date,
                    announced_date=announced_date,
                )
            if ann_clean > dec_clean:
                return PITEvaluationResult(
                    is_usable=False,
                    quality_status="REJECTED",
                    reason_code="PIT_POST_HOC_ANNOUNCEMENT",
                    ui_display_text=f"拒絕使用：公告日偏誤 (公告日 {ann_clean} > 決策日 {dec_clean})",
                    decision_date=decision_date,
                    available_date=available_date,
                    announced_date=announced_date,
                )
            if ann_clean > avail_clean:
                return PITEvaluationResult(
                    is_usable=False,
                    quality_status="REJECTED",
                    reason_code="PIT_AVAILABLE_BEFORE_ANNOUNCEMENT",
                    ui_display_text="拒絕使用：可得日早於公告日，來源時間線不一致",
                    decision_date=decision_date,
                    available_date=available_date,
                    announced_date=announced_date,
                )

        return PITEvaluationResult(
            is_usable=True,
            quality_status="SAFE",
            reason_code="PIT_VERIFIED_SAFE",
            ui_display_text="通過 PIT 安全檢查：可得日早於或等於決策日",
            decision_date=decision_date,
            available_date=available_date,
            announced_date=announced_date,
        )
