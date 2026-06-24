from __future__ import annotations

import pytest

from qa.full_app_healthcheck.ux_gap_mapping import (
    ALLOWED_UX_GAP_CATEGORIES,
    get_all_ux_gaps,
    get_ux_gaps_for_feature,
    get_ux_gaps_for_flow,
    render_ux_gap_mapping_markdown,
    KnownUXGap,
)
from qa.full_app_healthcheck.flow_diagnostics import generate_flow_diagnostics, render_flow_diagnostics_markdown
from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.flow_model import FLOWS


def test_get_all_ux_gaps():
    """驗證 get_all_ux_gaps() 回傳所有內建 KnownUXGap 且欄位完整與合規"""
    gaps = get_all_ux_gaps()
    assert len(gaps) > 0
    assert {gap.category for gap in gaps} == ALLOWED_UX_GAP_CATEGORIES
    for gap in gaps:
        assert isinstance(gap, KnownUXGap)
        assert gap.gap_id.startswith("ux_gap_")
        assert gap.category in ALLOWED_UX_GAP_CATEGORIES
        assert gap.title
        assert gap.feature_id in FEATURE_ROUTES
        assert gap.flow_id is None or gap.flow_id in FLOWS
        assert gap.likely_owner in {"execution", "testing_qa", "data_audit"}
        assert isinstance(gap.evidence_sources, tuple)
        assert gap.recommended_next_step


def test_get_ux_gaps_for_feature():
    """驗證 get_ux_gaps_for_feature() 篩選特定 feature_id 正確"""
    update_gaps = get_ux_gaps_for_feature("update_view")
    assert len(update_gaps) > 0
    for gap in update_gaps:
        assert gap.feature_id == "update_view"

    none_gaps = get_ux_gaps_for_feature("non_existent_feature")
    assert len(none_gaps) == 0


def test_get_ux_gaps_for_flow():
    """驗證 get_ux_gaps_for_flow() 篩選特定 flow_id 正確"""
    dm_gaps = get_ux_gaps_for_flow("data_market_loop")
    assert len(dm_gaps) > 0
    for gap in dm_gaps:
        assert gap.flow_id == "data_market_loop"

    none_gaps = get_ux_gaps_for_flow("non_existent_flow")
    assert len(none_gaps) == 0


def test_render_ux_gap_mapping_markdown():
    """驗證 render_ux_gap_mapping_markdown() 產出格式正確"""
    gaps = get_ux_gaps_for_flow("data_market_loop")
    markdown = render_ux_gap_mapping_markdown(gaps)

    assert "data_market_loop" in markdown
    assert "TWSE/TPEX real API fetch progress bar indication" in markdown
    assert "Implement explicit progress bar widget for Twstock daily fetch." in markdown

    empty_markdown = render_ux_gap_mapping_markdown([])
    assert empty_markdown == "- (None)"


def test_invalid_category_error():
    """驗證 KnownUXGap 初始化時傳入無效 category 會拋出 ValueError"""
    with pytest.raises(ValueError) as excinfo:
        KnownUXGap(
            gap_id="ux_gap_test",
            category="invalid_category_name",
            title="Test Title",
            feature_id="update_view",
            flow_id=None,
            likely_owner="execution",
            evidence_sources=(),
            recommended_next_step="Fix it",
        )
    assert "Invalid category 'invalid_category_name'" in str(excinfo.value)


def test_invalid_feature_or_flow_error():
    with pytest.raises(ValueError, match="Unknown feature_id"):
        KnownUXGap(
            gap_id="ux_gap_bad_feature",
            category="unclear_copy",
            title="Bad feature",
            feature_id="does_not_exist",
            flow_id=None,
            likely_owner="testing_qa",
            evidence_sources=(),
            recommended_next_step="Fix metadata",
        )

    with pytest.raises(ValueError, match="Unknown flow_id"):
        KnownUXGap(
            gap_id="ux_gap_bad_flow",
            category="unclear_copy",
            title="Bad flow",
            feature_id="update_view",
            flow_id="does_not_exist",
            likely_owner="testing_qa",
            evidence_sources=(),
            recommended_next_step="Fix metadata",
        )


def test_flow_diagnostics_exposes_ux_gaps_without_runner_commands():
    report = generate_flow_diagnostics()
    data_market = next(item for item in report.diagnostics if item.flow_id == "data_market_loop")

    assert data_market.ux_gaps
    assert any(gap.category == "missing_entrypoint" for gap in data_market.ux_gaps)
    command_text = "\n".join(data_market.recommended_commands)
    assert not any(gap.title in command_text for gap in data_market.ux_gaps)
    assert not any(gap.recommended_next_step in command_text for gap in data_market.ux_gaps)


def test_flow_diagnostics_markdown_includes_ux_gaps():
    markdown = render_flow_diagnostics_markdown(generate_flow_diagnostics())

    assert "#### UX Gaps" in markdown
    assert "`[unclear_copy]` TWSE/TPEX real API fetch progress bar indication" in markdown
    assert "Recommended Next Step: Implement explicit progress bar widget" in markdown
