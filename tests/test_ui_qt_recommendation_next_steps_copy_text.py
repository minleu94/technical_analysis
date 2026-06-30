from pathlib import Path


def test_recommendation_view_names_next_steps_as_research_workflow():
    text = Path("ui_qt/views/recommendation_view.py").read_text(encoding="utf-8")

    assert "加入觀察清單" in text
    assert "送 Research Lab 批次回測" in text
    assert "送 Research Lab 推薦回放" in text
    assert "記錄到持倉管理" in text
