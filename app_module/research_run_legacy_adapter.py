"""Legacy research run adapters for controlled backfill into Research Run Registry."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import hashlib
from typing import Any

import pandas as pd

from app_module.research_run_dtos import ResearchRunMetadataDTO, canonical_json


class ResearchRunLegacyAdapter:
    """將舊 repository run 轉成 ResearchRunMetadataDTO。

    Adapter 不偽造缺失 metadata；無法從舊格式得知的策略版本、契約版本、
    資料 fingerprint 與成交細節會明確標示為 unknown。
    """

    UNKNOWN = "unknown"

    def from_backtest_run(
        self,
        legacy_run: Any,
        legacy_data: dict[str, Any] | None = None,
    ) -> tuple[ResearchRunMetadataDTO, pd.DataFrame, pd.DataFrame]:
        run_dict = self._to_dict(legacy_run)
        legacy_data = legacy_data or {}
        equity = self._frame_or_empty(legacy_data.get("equity_curve"))
        trades = self._frame_or_empty(legacy_data.get("trade_list"))
        legacy_run_id = str(run_dict.get("run_id", ""))
        original_input = {
            "source_repository": "BacktestRunRepository",
            "legacy_run_id": legacy_run_id,
            "stock_code": run_dict.get("stock_code", ""),
        }
        normalized_params = self._dict_or_empty(run_dict.get("strategy_params"))
        metrics = {
            "total_return": run_dict.get("total_return"),
            "annual_return": run_dict.get("annual_return"),
            "sharpe_ratio": run_dict.get("sharpe_ratio"),
            "max_drawdown": run_dict.get("max_drawdown"),
            "total_trades": run_dict.get("total_trades"),
        }
        payload_hash = self._payload_hash(
            {
                "source": "backtest",
                "legacy_run_id": legacy_run_id,
                "normalized_params": normalized_params,
                "metrics": metrics,
            }
        )
        metadata = ResearchRunMetadataDTO(
            run_id=f"legacy-backtest:{legacy_run_id}",
            run_name=str(run_dict.get("run_name", legacy_run_id)),
            run_type="legacy_backtest",
            strategy_id=str(run_dict.get("strategy_id", "")),
            strategy_version=self.UNKNOWN,
            parameter_contract_version=self.UNKNOWN,
            original_input=original_input,
            normalized_params=normalized_params,
            fallback_reason=self._missing_metadata_reason(
                [
                    "strategy_version",
                    "parameter_contract_version",
                    "data_fingerprint",
                    "data_manifest",
                ]
            ),
            universe=[run_dict["stock_code"]] if run_dict.get("stock_code") else [],
            start_date=str(run_dict.get("start_date", "")),
            end_date=str(run_dict.get("end_date", "")),
            data_cutoff_date=self.UNKNOWN,
            data_fingerprint=self.UNKNOWN,
            fingerprint_algorithm=self.UNKNOWN,
            data_manifest={},
            capital_cents=self._money_to_cents(run_dict.get("capital")),
            fee_bp_x100=self._bps_to_bp_x100(run_dict.get("fee_bps")),
            slippage_bp_x100=self._bps_to_bp_x100(run_dict.get("slippage_bps")),
            stop_loss_bp=self._pct_to_bp(run_dict.get("stop_loss_pct")),
            take_profit_bp=self._pct_to_bp(run_dict.get("take_profit_pct")),
            execution_price=self.UNKNOWN,
            sizing_mode=self.UNKNOWN,
            metrics=metrics,
            regime_breakdown={},
            benchmark_results={},
            payload_hash=payload_hash,
            created_at=str(run_dict.get("created_at", "")),
        )
        return metadata, equity, trades

    def from_recommendation_portfolio_run(
        self,
        legacy_run: dict[str, Any],
    ) -> tuple[ResearchRunMetadataDTO, pd.DataFrame, pd.DataFrame]:
        config = self._dict_or_empty(legacy_run.get("config"))
        result = self._dict_or_empty(legacy_run.get("result"))
        legacy_run_id = str(legacy_run.get("run_id", ""))
        summary = self._dict_or_empty(result.get("summary"))
        payload_hash = self._payload_hash(
            {
                "source": "recommendation_portfolio",
                "legacy_run_id": legacy_run_id,
                "config": config,
                "summary": summary,
            }
        )
        metadata = ResearchRunMetadataDTO(
            run_id=f"legacy-recommendation-portfolio:{legacy_run_id}",
            run_name=str(legacy_run.get("run_name", legacy_run_id)),
            run_type="legacy_recommendation_portfolio",
            strategy_id=str(config.get("profile_id", "")),
            strategy_version=self.UNKNOWN,
            parameter_contract_version=self.UNKNOWN,
            original_input={
                "source_repository": "RecommendationPortfolioRunRepository",
                "legacy_run_id": legacy_run_id,
            },
            normalized_params=config,
            fallback_reason=self._missing_metadata_reason(
                ["strategy_version", "parameter_contract_version", "data_fingerprint"]
            ),
            start_date=str(config.get("start_date", "")),
            end_date=str(config.get("end_date", "")),
            data_cutoff_date=self.UNKNOWN,
            data_fingerprint=self.UNKNOWN,
            fingerprint_algorithm=self.UNKNOWN,
            capital_cents=self._money_to_cents(config.get("initial_capital")),
            stop_loss_bp=self._pct_to_bp(config.get("stop_loss_pct")),
            take_profit_bp=self._pct_to_bp(config.get("take_profit_pct")),
            execution_price=self.UNKNOWN,
            sizing_mode=str(config.get("allocation_method", self.UNKNOWN)),
            metrics=summary,
            payload_hash=payload_hash,
            created_at=str(legacy_run.get("created_at", "")),
        )
        return metadata, pd.DataFrame(), pd.DataFrame()

    def _to_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return dict(vars(value))

    def _frame_or_empty(self, value: Any) -> pd.DataFrame:
        if isinstance(value, pd.DataFrame):
            return value.copy()
        return pd.DataFrame()

    def _dict_or_empty(self, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    def _missing_metadata_reason(self, fields: list[str]) -> dict[str, Any]:
        return {
            "source": "legacy_backfill",
            "missing_metadata": fields,
            "policy": "preserve_unknown_without_fabrication",
        }

    def _payload_hash(self, payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _money_to_cents(self, value: Any) -> int:
        if value is None:
            return 0
        return int((Decimal(str(value)) * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))

    def _bps_to_bp_x100(self, value: Any) -> int:
        if value is None:
            return 0
        return int((Decimal(str(value)) * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))

    def _pct_to_bp(self, value: Any) -> int | None:
        if value is None:
            return None
        return int((Decimal(str(value)) * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))
