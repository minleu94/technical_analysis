from decimal import Decimal

from app_module.recommendation_ranking_pipeline import build_ranking_plan


def test_fixed_ranking_plan_preserves_input_order_for_score_ties() -> None:
    plan = build_ranking_plan(
        [("B", Decimal("80")), ("A", Decimal("80")), ("C", Decimal("70"))],
        mode="fixed",
        top_n=2,
        ranking_config={},
        eligible_universe_date="2026-07-10",
    )

    assert plan.ordered_codes == ("B", "A", "C")
    assert plan.selected_codes == ("B", "A")
    assert plan.percentiles_bp == {}


def test_quantile_ranking_plan_uses_stable_stock_code_tie_break_and_bp_gate() -> None:
    plan = build_ranking_plan(
        [("B", Decimal("80")), ("A", Decimal("80")), ("C", Decimal("70"))],
        mode="quantile",
        top_n=1,
        ranking_config={
            "recommendation_min_percentile_bp": 5000,
            "recommendation_min_universe_size": 3,
            "recommendation_ranking_method": "competition",
        },
        eligible_universe_date="2026-07-10",
    )

    assert plan.ordered_codes[:2] == ("A", "B")
    assert plan.selected_codes == ("A",)
    assert plan.percentiles_bp["A"] >= 5000
