"""BacktestView 的純文字呈現規則。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app_module.dtos import BacktestReportDTO, ValidationStatus


def build_portfolio_promotion_success_message(version_id: str, run_id: str) -> str:
    return (
        "推薦回放已升級為策略版本。\n\n"
        f"版本 ID: {version_id}\n"
        f"來源 run: {run_id}\n\n"
        "後續可到推薦分析的 Profile / 策略版本來源查看；"
        "若清單尚未更新，請重新整理或重新開啟推薦分析頁。"
    )


def choice_display_text(param_name: str, value: Any) -> str:
    value_text = str(value)
    display_map = {
        "threshold_mode": {
            "fixed": "固定門檻",
            "quantile": "百分位排名",
        },
        "quantile_method": {
            "nearest_rank": "最近名次法",
        },
    }
    return display_map.get(param_name, {}).get(value_text, value_text)


def format_backtest_summary(report: BacktestReportDTO) -> str:
    """格式化績效摘要，維持 Primary/SOP 指標優先順序。"""
    details = report.details
    actual_start = details.get("start_date", "未知")
    actual_end = details.get("end_date", "未知")
    requested_start = details.get("requested_start_date", actual_start)
    requested_end = details.get("requested_end_date", actual_end)
    lines = ["=== 績效摘要 ===", f"回測日期範圍: {actual_start} 至 {actual_end}"]
    if details.get("date_adjusted"):
        lines.append(
            f"注意: 請求範圍 {requested_start}~{requested_end} 已調整為實際數據範圍"
        )

    score_diag = details.get("score_diagnostics")
    if score_diag:
        lines.extend(
            [
                "",
                "--- 策略分數診斷 (Scoring Diagnostics) ---",
                f"最高得分: {score_diag['max_score']:.1f} | 最低得分: {score_diag['min_score']:.1f} | 平均得分: {score_diag['avg_score']:.1f}",
            ]
        )
        total_days = score_diag.get("total_days", 0)
        buy_hit_days = score_diag.get("buy_hit_days", 0)
        sell_hit_days = score_diag.get("sell_hit_days", 0)
        if score_diag.get("threshold_mode", "fixed") == "quantile":
            ready_days = score_diag.get("warmup_ready_days", 0)
            buy_pct = buy_hit_days / ready_days * 100.0 if ready_days > 0 else 0.0
            sell_pct = sell_hit_days / ready_days * 100.0 if ready_days > 0 else 0.0
            buy_bp = score_diag.get("buy_quantile_bp", 8000)
            sell_bp = score_diag.get("sell_quantile_bp", 4000)
            lines.extend(
                [
                    f"門檻模式: 分位數 (暖機完成日數: {ready_days} 天 / 總日數: {total_days} 天)",
                    f"動態買進分位數 ({buy_bp/100:.1f}%) 命中天數: {buy_hit_days} 天 / 已暖機 {ready_days} 天 ({buy_pct:.1f}%)",
                    f"動態賣出分位數 ({sell_bp/100:.1f}%) 命中天數: {sell_hit_days} 天 / 已暖機 {ready_days} 天 ({sell_pct:.1f}%)",
                ]
            )
        else:
            buy_pct = buy_hit_days / total_days * 100.0 if total_days > 0 else 0.0
            sell_pct = sell_hit_days / total_days * 100.0 if total_days > 0 else 0.0
            lines.extend(
                [
                    f"買進門檻 ({score_diag.get('buy_score', 0.0):.1f}) 命中天數: {buy_hit_days} 天 / {total_days} 天 ({buy_pct:.1f}%)",
                    f"賣出門檻 ({score_diag.get('sell_score', 0.0):.1f}) 命中天數: {sell_hit_days} 天 / {total_days} 天 ({sell_pct:.1f}%)",
                ]
            )

    lines.extend(
        [
            "",
            "╔════════════════════════════════════════╗",
            "║  Phase 3.5 SOP 驗證（必須優先查看）     ║",
            "╚════════════════════════════════════════╝",
        ]
    )
    status_text = {
        ValidationStatus.PASS: "[PASS]",
        ValidationStatus.WARNING: "[WARN]",
        ValidationStatus.FAIL: "[FAIL]",
    }.get(report.validation_status, "[UNKNOWN]")
    lines.append(f"驗證狀態: {status_text} {report.validation_status.value}")
    if report.validation_messages:
        lines.append("")
        lines.extend(report.validation_messages)
    lines.extend(["", "--- Primary 指標（行為健康） ---", f"總交易次數: {report.total_trades}"])
    trade_list = details.get("trade_list")
    if isinstance(trade_list, pd.DataFrame) and len(trade_list) > 0 and "持有天數" in trade_list.columns:
        lines.append(f"平均持有天數: {trade_list['持有天數'].mean():.1f} 天")

    if report.baseline_comparison:
        lines.extend(["", "--- Baseline 對比 ---"])
        better_text = (
            "[PASS] 優於 Buy & Hold"
            if report.baseline_comparison.get("is_better", False)
            else "[FAIL] 不如 Buy & Hold"
        )
        lines.append(f"策略表現: {better_text}")
        if "excess_return" in report.baseline_comparison:
            lines.append(
                f"超額報酬率: {report.baseline_comparison['excess_return'] * 100:+.2f}%"
            )
    if report.overfitting_risk:
        lines.extend(["", "--- 穩健性（過擬合風險） ---"])
        risk_level = report.overfitting_risk.get("risk_level", "unknown")
        risk_token = {"low": "[LOW]", "medium": "[MEDIUM]", "high": "[HIGH]"}.get(
            risk_level, "[UNKNOWN]"
        )
        lines.append(f"過擬合風險等級: {risk_token} {risk_level.upper()}")
        degradation = report.overfitting_risk.get("degradation")
        if degradation is not None:
            lines.append(f"退化程度: {degradation * 100:.1f}%")

    lines.extend(
        [
            "",
            "╔════════════════════════════════════════╗",
            "║  Secondary 指標（輔助參考）            ║",
            "╚════════════════════════════════════════╝",
            "",
            f"總報酬率: {report.total_return * 100:.2f}%",
            f"年化報酬率 (CAGR): {report.annual_return * 100:.2f}%",
            f"夏普比率: {report.sharpe_ratio:.2f}",
            f"最大回撤: {report.max_drawdown * 100:.2f}%",
            f"勝率: {report.win_rate * 100:.2f}%",
            f"期望值: {report.expectancy * 100:.2f}%",
            "",
            "=== 詳細統計 ===",
        ]
    )
    detail_formats = (
        ("profit_factor", "獲利因子: {:.2f}"),
        ("avg_win", "平均獲利: ${:.2f}"),
        ("avg_loss", "平均虧損: ${:.2f}"),
        ("largest_win", "最大獲利: ${:.2f}"),
        ("largest_loss", "最大虧損: ${:.2f}"),
        ("final_equity", "最終權益: ${:,.2f}"),
    )
    for key, template in detail_formats:
        if key in details:
            lines.append(template.format(details[key]))
    if "error" in details:
        lines.append(f"\n錯誤: {details['error']}")
    return "\n".join(lines)
