"""Backtest report 的純 factor 與 DTO 組裝。"""
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
import pandas as pd
from app_module.dtos import BacktestReportDTO, ValidationStatus
from decision_module.factors.factor_adapters import build_technical_total_score_factor
from decision_module.factors.factor_dtos import FactorRecord

def date_from_index(value: Any) -> date | None:
    timestamp = pd.Timestamp(value)
    return None if pd.isna(timestamp) else timestamp.date()

def factor_decision_date(signal_frame: pd.DataFrame) -> date | None:
    return None if signal_frame.empty else date_from_index(signal_frame.index.max())

def score_factor_records(stock_code: str, score_series: pd.Series) -> list[FactorRecord]:
    records=[]
    for index, score in score_series.items():
        if pd.isna(score): continue
        try: value=Decimal(str(score))
        except (InvalidOperation, ValueError): continue
        as_of=date_from_index(index)
        if as_of is not None: records.append(build_technical_total_score_factor(stock_code=stock_code, as_of_date=as_of, available_date=as_of, total_score=value))
    return records

def create_empty_report(error_message: str) -> BacktestReportDTO:
    return BacktestReportDTO(total_return=0.0, annual_return=0.0, sharpe_ratio=0.0, max_drawdown=0.0, win_rate=0.0, total_trades=0, expectancy=0.0, baseline_comparison=None, overfitting_risk=None, changed_layers=[], validation_status=ValidationStatus.FAIL, sample_insufficient_flags={"error": True}, validation_messages=[f"❌ 錯誤：{error_message}"], details={"error": error_message, "equity_curve": pd.DataFrame(), "trade_list": pd.DataFrame(), "can_promote": False})
