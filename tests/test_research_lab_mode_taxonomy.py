from ui_qt.views.backtest_view import RESEARCH_LAB_MODES


def test_research_lab_modes_are_distinct_and_named_for_user_intent():
    mode_ids = [mode["id"] for mode in RESEARCH_LAB_MODES]

    assert mode_ids == [
        "single_stock",
        "batch_stock",
        "fixed_basket",
        "recommendation_replay",
        "strategy_research",
    ]
    assert len(mode_ids) == len(set(mode_ids))


def test_research_lab_modes_include_visible_guidance_fields():
    for mode in RESEARCH_LAB_MODES:
        assert mode["label"]
        assert mode["description"]
        assert mode["primary_input"]
