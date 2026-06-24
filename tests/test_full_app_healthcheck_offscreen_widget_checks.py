from __future__ import annotations

import pytest

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.test_suite_bridge import build_existing_suite_registry
from qa.full_app_healthcheck.test_inventory import get_category
from qa.full_app_healthcheck.offscreen_widget_checks import (
    FORBIDDEN_EVIDENCE_CATEGORIES,
    FORBIDDEN_OFFSCREEN_TERMS,
    OffscreenWidgetCheck,
    get_all_offscreen_widget_checks,
    get_offscreen_widget_checks_for_feature,
    render_offscreen_widget_checks_markdown,
)


def test_widget_checks_integrity_and_boundaries():
    """驗證所有內建 widget check 符合安全與路由限制"""
    checks = get_all_offscreen_widget_checks()
    assert len(checks) > 0

    bridge_suite_ids = {suite.id for suite in build_existing_suite_registry()}

    for check in checks:
        assert isinstance(check, OffscreenWidgetCheck)
        assert check.feature_id in FEATURE_ROUTES
        assert check.non_destructive is True
        assert check.requires_main_window is False
        assert check.assertion_scope
        assert check.evidence_sources

        searchable = " ".join(
            (
                check.check_id,
                check.target_widget,
                check.purpose,
                *check.assertion_scope,
                *check.safe_qtest_actions,
                *check.evidence_sources,
            )
        ).lower()
        for keyword in FORBIDDEN_OFFSCREEN_TERMS:
            assert keyword not in searchable

        assert check.check_id not in bridge_suite_ids
        for source in check.evidence_sources:
            if source.startswith("tests/"):
                assert get_category(source) not in FORBIDDEN_EVIDENCE_CATEGORIES


def test_get_offscreen_widget_checks_for_feature():
    """驗證 get_offscreen_widget_checks_for_feature() 篩選正確"""
    update_checks = get_offscreen_widget_checks_for_feature("update_view")
    assert len(update_checks) > 0
    for check in update_checks:
        assert check.feature_id == "update_view"

    none_checks = get_offscreen_widget_checks_for_feature("non_existent_feature")
    assert len(none_checks) == 0


def test_render_offscreen_widget_checks_markdown():
    """驗證 render_offscreen_widget_checks_markdown() 產出格式正確"""
    checks = get_offscreen_widget_checks_for_feature("update_view")
    markdown = render_offscreen_widget_checks_markdown(checks)

    # 必須包含 target widget、assertion scope、安全 QTest actions 與 evidence
    assert "UpdateView" in markdown  # Target Widget
    assert "Label visibility check" in markdown  # Assertion Scope
    assert "QTest.mouseClick on Refresh Button" in markdown  # Safe QTest Action
    assert "tests/test_ui_qt_update_view_workbench.py" in markdown  # Evidence

    empty_markdown = render_offscreen_widget_checks_markdown([])
    assert empty_markdown == "- (None)"


def test_offscreen_widget_check_rejects_unsafe_metadata():
    with pytest.raises(ValueError, match="Unknown feature_id"):
        OffscreenWidgetCheck(
            check_id="ui_check_bad_feature",
            feature_id="does_not_exist",
            target_widget="Widget",
            purpose="Check labels",
            assertion_scope=("Label visibility",),
            safe_qtest_actions=(),
            evidence_sources=(),
            non_destructive=True,
        )

    with pytest.raises(ValueError, match="must be non-destructive"):
        OffscreenWidgetCheck(
            check_id="ui_check_destructive",
            feature_id="update_view",
            target_widget="UpdateView",
            purpose="Check labels",
            assertion_scope=("Label visibility",),
            safe_qtest_actions=(),
            evidence_sources=(),
            non_destructive=False,
        )

    with pytest.raises(ValueError, match="must not require MainWindow"):
        OffscreenWidgetCheck(
            check_id="ui_check_mainwindow",
            feature_id="update_view",
            target_widget="UpdateView",
            purpose="Check labels",
            assertion_scope=("Label visibility",),
            safe_qtest_actions=(),
            evidence_sources=(),
            non_destructive=True,
            requires_main_window=True,
        )

    with pytest.raises(ValueError, match="forbidden D-1 term"):
        OffscreenWidgetCheck(
            check_id="ui_check_write_risk_source",
            feature_id="update_view",
            target_widget="UpdateView",
            purpose="Check labels",
            assertion_scope=("Label visibility",),
            safe_qtest_actions=(),
            evidence_sources=("tests/test_tpex_daily_price_backfill.py",),
            non_destructive=True,
        )

    with pytest.raises(ValueError, match="forbidden evidence category"):
        OffscreenWidgetCheck(
            check_id="ui_check_forbidden_category_source",
            feature_id="update_view",
            target_widget="UpdateView",
            purpose="Check labels",
            assertion_scope=("Label visibility",),
            safe_qtest_actions=(),
            evidence_sources=("tests/test_tpex_daily_price_source.py",),
            non_destructive=True,
        )
