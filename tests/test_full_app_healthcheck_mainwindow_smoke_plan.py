from __future__ import annotations

from pathlib import Path

import pytest

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.mainwindow_smoke_plan import (
    FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS,
    MainWindowSmokePlanStep,
    get_mainwindow_smoke_plan,
    get_mainwindow_smoke_plan_for_feature,
    render_mainwindow_smoke_plan_markdown,
)
from qa.full_app_healthcheck.mainwindow_smoke import (
    EXPECTED_MAINWINDOW_TAB_LABELS,
    ViewportSize,
    build_mainwindow_smoke_evidence,
    collect_mainwindow_smoke_evidence,
    parse_viewport_spec,
)
from qa.full_app_healthcheck.test_suite_bridge import build_existing_suite_registry


def test_mainwindow_smoke_plan_integrity_and_boundaries():
    plans = get_mainwindow_smoke_plan()
    assert plans

    bridge_suite_ids = {suite.id for suite in build_existing_suite_registry()}

    for step in plans:
        assert isinstance(step, MainWindowSmokePlanStep)
        assert step.feature_id in FEATURE_ROUTES
        assert step.non_destructive is True
        assert step.requires_explicit_user_confirmation is True
        assert step.requires_main_window is True
        assert step.allowed_observations
        assert step.forbidden_actions
        assert step.step_id not in bridge_suite_ids

        forbidden_text = " ".join(step.forbidden_actions).lower()
        for forbidden_action in FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS:
            assert forbidden_action in forbidden_text

        observation_text = " ".join(step.allowed_observations).lower()
        assert "write" not in observation_text
        assert "migration" not in observation_text
        assert "backfill apply" not in observation_text
        assert "external fetch" not in observation_text
        assert "high-risk dry-run" not in observation_text


def test_mainwindow_smoke_plan_does_not_import_qt_or_runner_execution():
    module_source = Path("qa/full_app_healthcheck/mainwindow_smoke_plan.py").read_text(encoding="utf-8")

    assert "PySide6" not in module_source
    assert "QApplication" not in module_source
    assert "QTest." not in module_source
    assert "run_full_app_healthcheck" not in module_source


def test_mainwindow_smoke_plan_rejects_unsafe_metadata():
    with pytest.raises(ValueError, match="Unknown feature_id"):
        MainWindowSmokePlanStep(
            step_id="bad_feature",
            feature_id="does_not_exist",
            purpose="Plan only",
            allowed_observations=("Window shell visible",),
            forbidden_actions=tuple(sorted(FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS)),
            non_destructive=True,
        )

    with pytest.raises(ValueError, match="non-destructive"):
        MainWindowSmokePlanStep(
            step_id="destructive",
            feature_id="update_view",
            purpose="Plan only",
            allowed_observations=("Window shell visible",),
            forbidden_actions=tuple(sorted(FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS)),
            non_destructive=False,
        )

    with pytest.raises(ValueError, match="explicit user confirmation"):
        MainWindowSmokePlanStep(
            step_id="no_confirmation",
            feature_id="update_view",
            purpose="Plan only",
            allowed_observations=("Window shell visible",),
            forbidden_actions=tuple(sorted(FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS)),
            non_destructive=True,
            requires_explicit_user_confirmation=False,
        )

    missing_one_forbidden = tuple(
        action for action in sorted(FORBIDDEN_MAINWINDOW_SMOKE_ACTIONS) if action != "external fetch"
    )
    with pytest.raises(ValueError, match="external fetch"):
        MainWindowSmokePlanStep(
            step_id="missing_forbidden_action",
            feature_id="update_view",
            purpose="Plan only",
            allowed_observations=("Window shell visible",),
            forbidden_actions=missing_one_forbidden,
            non_destructive=True,
        )


def test_get_mainwindow_smoke_plan_for_feature():
    update_steps = get_mainwindow_smoke_plan_for_feature("update_view")
    assert update_steps
    for step in update_steps:
        assert step.feature_id == "update_view"

    assert get_mainwindow_smoke_plan_for_feature("non_existent_feature") == ()


def test_render_mainwindow_smoke_plan_markdown():
    markdown = render_mainwindow_smoke_plan_markdown(get_mainwindow_smoke_plan_for_feature("update_view"))

    assert "D-2 is plan-only metadata" in markdown
    assert "Requires Explicit Confirmation" in markdown
    assert "database write" in markdown
    assert "mainwindow_startup_shell_observation" in markdown

    assert render_mainwindow_smoke_plan_markdown([]) == "- (None)"


class FakeTabWidget:
    def __init__(self, labels):
        self.labels = list(labels)
        self.current_index = 0

    def count(self):
        return len(self.labels)

    def tabText(self, index):
        return self.labels[index]

    def setCurrentIndex(self, index):
        self.current_index = index


class FakeMainWindow:
    def __init__(self, tab_widget):
        self.tab_widget = tab_widget

    def windowTitle(self):
        return "baldr"

    def findChildren(self, widget_type):
        return [self.tab_widget]


def test_collect_mainwindow_smoke_evidence_with_injected_window():
    window = FakeMainWindow(FakeTabWidget(EXPECTED_MAINWINDOW_TAB_LABELS))

    evidence = collect_mainwindow_smoke_evidence(window, switch_tabs=True)

    assert evidence["window_title"] == "baldr"
    assert evidence["tab_labels"] == list(EXPECTED_MAINWINDOW_TAB_LABELS)
    assert evidence["missing_tabs"] == []
    assert evidence["switched_tabs"] == list(EXPECTED_MAINWINDOW_TAB_LABELS)
    assert evidence["forbidden_actions_invoked"] == []


def test_collect_mainwindow_smoke_evidence_reports_missing_tabs():
    labels = tuple(label for label in EXPECTED_MAINWINDOW_TAB_LABELS if label != "持倉管理")
    window = FakeMainWindow(FakeTabWidget(labels))

    evidence = collect_mainwindow_smoke_evidence(window, switch_tabs=False)

    assert evidence["missing_tabs"] == ["持倉管理"]
    assert evidence["switched_tabs"] == []


def test_parse_viewport_spec_accepts_width_by_height():
    viewport = parse_viewport_spec("390x844")

    assert viewport == ViewportSize(width=390, height=844)
    assert viewport.label == "390x844"


def test_parse_viewport_spec_rejects_invalid_values():
    invalid_specs = ("", "390", "390*844", "0x844", "390x0", "abcx844")

    for spec in invalid_specs:
        with pytest.raises(ValueError):
            parse_viewport_spec(spec)


def test_build_mainwindow_smoke_evidence_preserves_operation_sections():
    evidence = build_mainwindow_smoke_evidence(
        window_title="baldr",
        tab_labels=list(EXPECTED_MAINWINDOW_TAB_LABELS),
        missing_tabs=[],
        switched_tabs=list(EXPECTED_MAINWINDOW_TAB_LABELS),
        screenshots=[{"label": "startup", "path": "screenshots/startup.png"}],
        resize_evidence=[{"viewport": "390x844", "actual_size": "390x844"}],
        dialog_cancel_evidence=[{"dialog": "force_merge_daily_price", "cancelled": True}],
        forbidden_actions_invoked=[],
    )

    assert evidence["window_title"] == "baldr"
    assert evidence["screenshots"][0]["label"] == "startup"
    assert evidence["resize_evidence"][0]["viewport"] == "390x844"
    assert evidence["dialog_cancel_evidence"][0]["cancelled"] is True
    assert evidence["forbidden_actions_invoked"] == []
