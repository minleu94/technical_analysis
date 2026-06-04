from pathlib import Path


def test_watchlist_view_frames_primary_surface_as_candidate_pool():
    source = Path("ui_qt/views/watchlist_view.py").read_text(encoding="utf-8")

    assert 'QLabel("候選池")' in source
    assert 'QLabel("觀察候選池")' in source
    assert 'QGroupBox("候選池操作")' in source


def test_watchlist_view_exposes_research_lab_batch_handoff_copy():
    source = Path("ui_qt/views/watchlist_view.py").read_text(encoding="utf-8")

    assert 'QPushButton("送 Research Lab 批次回測")' in source
    assert "將目前候選池作為批次股票回測的輸入。" in source
    assert "此入口將在 Research Lab 批次回測整合時啟用。" in source
