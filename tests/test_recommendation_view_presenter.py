from ui_qt.views.recommendation.presenter import (
    format_profile_filter_value,
    format_profile_weight,
    format_recommendation_reason,
    generate_explain_panel,
    generate_why_not,
    format_regime_names,
    profile_advanced_summary,
)
from ui_qt.views.recommendation.recommendation_metadata import (
    PATTERN_DESCRIPTIONS,
    TECHNICAL_DESCRIPTIONS,
)
from app_module.dtos import RecommendationDTO


def test_format_regime_names_golden_contract() -> None:
    assert format_regime_names(["Trend", "Reversion", "Breakout"]) == (
        "Trend / 趨勢追蹤、Reversion / 均值回歸、Breakout / 突破準備"
    )
    assert format_regime_names(["Custom", None]) == "Custom"
    assert format_regime_names([]) == "未指定"


def test_profile_advanced_summary_golden_contract() -> None:
    config = {
        "signals": {
            "weights": {"pattern": "0.4", "technical": 35, "volume": 2500},
            "technical_indicators": ["trend", "momentum"],
        },
        "patterns": {"selected": ["W底", "旗形"]},
        "filters": {"price_change_min": "2.5", "price_change_max": 8, "industry": "半導體"},
    }

    assert profile_advanced_summary(config) == (
        "權重 型態 40% / 技術 35 / 量能 2500bp；"
        "技術分類 trend、momentum；型態 W底、旗形（共 2 種）；"
        "主要篩選 漲幅 2.5% ~ 8%、產業 半導體"
    )


def test_profile_numeric_formatters_do_not_require_binary_float() -> None:
    assert format_profile_weight("0.125") == "12%"
    assert format_profile_weight(None) == "N/A"
    assert format_profile_filter_value("2.50") == "2.5"


def test_recommendation_reason_presenter_preserves_highlights_and_trace() -> None:
    html = format_recommendation_reason(
        "MACD金叉、W底反轉、成交量增加",
        technical_descriptions=TECHNICAL_DESCRIPTIONS,
        pattern_descriptions=PATTERN_DESCRIPTIONS,
    )

    assert "推薦理由" in html
    assert "觸發來源" in html
    assert "技術指標" in html
    assert "圖形訊號" in html
    assert "#2563eb" in html
    assert "#16a34a" in html


def test_recommendation_reason_presenter_handles_empty_and_single_reason() -> None:
    assert format_recommendation_reason(
        "", technical_descriptions={}, pattern_descriptions={}
    ) == "無推薦理由"
    assert "推薦理由：</b>單一理由" in format_recommendation_reason(
        "單一理由", technical_descriptions={}, pattern_descriptions={}
    )


def test_explain_panel_preserves_ranking_trace_and_risk_points() -> None:
    recommendation = RecommendationDTO(
        stock_code="2330",
        stock_name="台積電",
        close_price=100,
        price_change=-2,
        total_score=48,
        indicator_score=45,
        pattern_score=35,
        volume_score=40,
        recommendation_reasons="",
        industry="半導體",
        regime_match=False,
        score_percentile_bp=8750,
        eligible_universe_size=120,
        ranking_method="nearest_rank",
        threshold_mode="quantile",
    )

    html = generate_explain_panel(recommendation)

    assert "分數拆解" in html
    assert "百分位排名" in html
    assert "最近名次法" in html
    assert "87.5%" in html
    assert "合格母體數：120 檔" in html
    assert "市場狀態不匹配" in html
    assert "價格下跌（-2.0%）" in html


def test_why_not_presenter_preserves_score_filter_and_regime_gaps() -> None:
    recommendation = RecommendationDTO(
        stock_code="2330",
        stock_name="台積電",
        close_price=100,
        price_change=-2,
        total_score=45,
        indicator_score=35,
        pattern_score=50,
        volume_score=40,
        recommendation_reasons="",
        industry="半導體",
        regime_match=False,
    )

    html = generate_why_not(
        recommendation,
        {"filters": {"price_change_min": 1, "price_change_max": 10}},
    )

    assert "技術指標分數" in html
    assert "漲幅篩選" in html
    assert "市場狀態匹配" in html
    assert "總分偏低" in html
    assert "#dc2626" in html


def test_why_not_presenter_has_explicit_all_conditions_passed_path() -> None:
    recommendation = RecommendationDTO(
        stock_code="2330",
        stock_name="台積電",
        close_price=100,
        price_change=5,
        total_score=80,
        indicator_score=80,
        pattern_score=80,
        volume_score=80,
        recommendation_reasons="",
        industry="半導體",
        regime_match=True,
    )

    assert "所有條件均符合" in generate_why_not(
        recommendation, {"filters": {"price_change_min": 1, "price_change_max": 10}}
    )
