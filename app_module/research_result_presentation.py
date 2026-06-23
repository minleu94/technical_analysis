"""Research Lab 結果呈現與可靠度提示 helper。

本模組只整理已產生的結果 DTO / dict 成為 UI 可讀文案，不重跑回測、
不重新抓取資料，也不改變任何交易或績效計算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


@dataclass(frozen=True)
class ReliabilityNotice:
    """Train-Test / Walk-forward 結果可靠度提示。"""

    level: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


def build_recommendation_replay_sections(result: Any) -> list[str]:
    """建立推薦回放結果摘要區塊。"""

    summary = dict(getattr(result, "summary", {}) or {})
    sections = [
        "【概況】",
        f"總報酬率: {_format_ratio(summary.get('total_return'))}",
        f"最大回撤: {_format_ratio(summary.get('max_drawdown'))}",
        f"交易檔數: {_to_int(summary.get('total_trades'))}",
        f"平均持有天數: {_format_decimal(summary.get('avg_holding_days'), places=1)}",
        f"資金使用: {_format_int(summary.get('capital_used'))}",
        "資金使用代表期間投入金額，不等同最終淨值；請搭配現金帳、未成交與權重曝險判讀。",
        "",
        "【交易假設與可信度】",
        "交易假設提醒: 推薦回放仍以同日收盤成交為主要研究假設，不等同實盤可成交價格。",
        "若結果含 gap_risk、liquidity_limited、cash_limited 或 lot_size_limited，需先看對應限制再判讀績效。",
        f"出場統計: 停損 {_to_int(summary.get('stop_loss_exits'))} / "
        f"停利 {_to_int(summary.get('take_profit_exits'))} / "
        f"持有到期 {_to_int(summary.get('holding_period_exits'))}",
        f"虧損交易占比: {_format_ratio(summary.get('loss_trade_ratio'))}",
        f"最拖累股票: {summary.get('worst_stock_code', '')} "
        f"{summary.get('worst_stock_name', '')} "
        f"({_format_int(summary.get('worst_stock_pnl'))})",
        "",
        "【風險與情境指標】",
        f"Sharpe Ratio: {_format_decimal(summary.get('sharpe_ratio'), places=2)}",
        f"Sortino Ratio: {_format_decimal(summary.get('sortino_ratio'), places=2)}",
        "",
        "【Monte Carlo 情境】",
        "P05 / P50 / P95 分別代表模擬分布中的偏弱、中位與偏強情境報酬，不是保證績效。",
        f"P05 / P50 / P95: "
        f"{_format_ratio(summary.get('monte_carlo_p05_return'))} / "
        f"{_format_ratio(summary.get('monte_carlo_p50_return'))} / "
        f"{_format_ratio(summary.get('monte_carlo_p95_return'))}",
    ]

    hints = list(getattr(result, "improvement_hints", []) or [])
    if hints:
        sections.extend(["", "【策略改善建議】"])
        sections.extend(str(hint) for hint in hints)

    return sections


def build_train_test_reliability_notice(
    train_report: Any,
    test_report: Any,
) -> ReliabilityNotice:
    """依 Train-Test Split 的既有結果產生樣本可靠度提示。"""

    train_trades = _to_int(getattr(train_report, "total_trades", 0))
    test_trades = _to_int(getattr(test_report, "total_trades", 0))
    test_win_rate_bp = _ratio_to_bp(getattr(test_report, "win_rate", 0))
    test_max_drawdown_bp = _ratio_to_bp(getattr(test_report, "max_drawdown", 0))

    warnings: list[str] = []
    if test_trades < 20:
        warnings.append("測試集 OOS 交易數低於 20，樣本不足，不宜作正式策略判斷。")
    if test_win_rate_bp == 10000 and abs(test_max_drawdown_bp) >= 5000:
        warnings.append("測試集勝率 100% 但最大回撤偏大，請檢查是否由少量交易或單筆劇烈波動造成。")

    if not warnings:
        warnings.append("樣本可靠度未觸發重大警示；仍需搭配資料版本、成本模型與 Registry 可比性判讀。")

    message = "\n".join(
        [
            "【樣本可靠度】",
            f"訓練集交易數: {train_trades}",
            f"OOS 交易數: {test_trades}",
            *warnings,
        ]
    )
    level = "warning" if any("不足" in item or "偏大" in item for item in warnings) else "info"
    return ReliabilityNotice(
        level=level,
        message=message,
        evidence={
            "train_trades": train_trades,
            "test_trades": test_trades,
            "test_win_rate_bp": test_win_rate_bp,
            "test_max_drawdown_bp": test_max_drawdown_bp,
        },
    )


def build_walkforward_reliability_notice(
    results: list[Any],
    summary: dict[str, Any],
) -> ReliabilityNotice:
    """依 Walk-forward fold 結果產生可靠度提示。"""

    total_folds = _to_int(summary.get("total_folds", len(results)))
    if total_folds == 0:
        total_folds = len(results)
    oos_trades = sum(
        _to_int(getattr(result, "test_metrics", {}).get("total_trades", 0))
        for result in results
    )
    consistency_bp = _ratio_to_bp(summary.get("consistency", 0))

    warnings: list[str] = []
    if total_folds < 3:
        warnings.append("Fold 數低於 3，樣本不足，不宜作正式策略判斷。")
    if oos_trades < 20:
        warnings.append("OOS 交易數低於 20，結果容易受單一交易影響。")
    if consistency_bp == 10000 and total_folds < 3:
        warnings.append("一致性 100% 來自很少 fold，不能解讀為穩定獲利證據。")

    if not warnings:
        warnings.append("Walk-forward 樣本未觸發重大可靠度警示；仍需搭配 Registry 可比性與資料品質判讀。")

    message = "\n".join(
        [
            "【Walk-forward 樣本可靠度】",
            f"Fold 數: {total_folds}",
            f"OOS 交易數: {oos_trades}",
            f"測試期正向 Sharpe 覆蓋率: {_format_bp(consistency_bp)}",
            *warnings,
        ]
    )
    level = "warning" if any("不足" in item or "低於" in item for item in warnings) else "info"
    return ReliabilityNotice(
        level=level,
        message=message,
        evidence={
            "total_folds": total_folds,
            "oos_trades": oos_trades,
            "consistency_bp": consistency_bp,
        },
    )


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _to_int(value: Any) -> int:
    return int(_to_decimal(value).to_integral_value(rounding=ROUND_HALF_UP))


def _ratio_to_bp(value: Any) -> int:
    return int(
        (_to_decimal(value) * Decimal("10000")).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )


def _format_bp(value: int) -> str:
    return f"{(Decimal(value) / Decimal('100')).quantize(Decimal('0.01'))}%"


def _format_ratio(value: Any) -> str:
    percent = (_to_decimal(value) * Decimal("100")).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    return f"{percent}%"


def _format_decimal(value: Any, *, places: int) -> str:
    quant = Decimal("1") if places == 0 else Decimal("0." + ("0" * (places - 1)) + "1")
    return str(_to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP))


def _format_int(value: Any) -> str:
    return f"{_to_int(value):,}"
