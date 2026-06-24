from __future__ import annotations

from pathlib import Path

import pytest

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.high_risk_dry_run_dialog_plan import (
    REQUIRED_FORBIDDEN_ACTIONS,
    HighRiskDryRunDialogPlan,
    get_high_risk_dry_run_dialog_plan,
    get_high_risk_dry_run_dialog_plan_for_feature,
    render_high_risk_dry_run_dialog_plan_markdown,
)
from qa.full_app_healthcheck.test_suite_bridge import build_existing_suite_registry


def test_high_risk_dry_run_dialog_plan_integrity_and_boundaries():
    plans = get_high_risk_dry_run_dialog_plan()
    assert plans

    bridge_suite_ids = {suite.id for suite in build_existing_suite_registry()}

    for plan in plans:
        assert isinstance(plan, HighRiskDryRunDialogPlan)
        assert plan.feature_id in FEATURE_ROUTES
        assert plan.non_destructive is True
        assert plan.requires_explicit_user_confirmation is True
        assert plan.requires_cancel_path is True
        assert plan.mock_service_not_called is True
        assert plan.allowed_observations
        assert plan.cancel_path_observations
        assert plan.forbidden_actions
        assert plan.plan_id not in bridge_suite_ids

        forbidden_text = " ".join(plan.forbidden_actions).lower()
        for forbidden_action in REQUIRED_FORBIDDEN_ACTIONS:
            assert forbidden_action in forbidden_text

        observation_text = " ".join(plan.allowed_observations).lower()
        cancel_text = " ".join(plan.cancel_path_observations).lower()
        for text in (observation_text, cancel_text):
            assert "click" not in text
            assert "data write" not in text
            assert "database write" not in text
            assert "migration" not in text
            assert "backfill apply" not in text
            assert "external fetch" not in text
            assert "high-risk dry-run" not in text


def test_high_risk_dry_run_dialog_plan_does_not_import_qt_or_runner_execution():
    module_source = Path("qa/full_app_healthcheck/high_risk_dry_run_dialog_plan.py").read_text(encoding="utf-8")

    assert "PySide6" not in module_source
    assert "QApplication" not in module_source
    assert "QTest." not in module_source
    assert "run_full_app_healthcheck" not in module_source


def test_high_risk_dry_run_dialog_plan_rejects_unsafe_metadata():
    with pytest.raises(ValueError, match="Unknown feature_id"):
        HighRiskDryRunDialogPlan(
            plan_id="bad_feature",
            feature_id="does_not_exist",
            purpose="Plan only",
            target_dialog_name="FakeDialog",
            allowed_observations=("Observations",),
            cancel_path_observations=("Cancel",),
            forbidden_actions=tuple(sorted(REQUIRED_FORBIDDEN_ACTIONS)),
            non_destructive=True,
        )

    with pytest.raises(ValueError, match="non-destructive"):
        HighRiskDryRunDialogPlan(
            plan_id="destructive",
            feature_id="update_view",
            purpose="Plan only",
            target_dialog_name="FakeDialog",
            allowed_observations=("Observations",),
            cancel_path_observations=("Cancel",),
            forbidden_actions=tuple(sorted(REQUIRED_FORBIDDEN_ACTIONS)),
            non_destructive=False,
        )

    with pytest.raises(ValueError, match="explicit user confirmation"):
        HighRiskDryRunDialogPlan(
            plan_id="no_confirmation",
            feature_id="update_view",
            purpose="Plan only",
            target_dialog_name="FakeDialog",
            allowed_observations=("Observations",),
            cancel_path_observations=("Cancel",),
            forbidden_actions=tuple(sorted(REQUIRED_FORBIDDEN_ACTIONS)),
            non_destructive=True,
            requires_explicit_user_confirmation=False,
        )

    with pytest.raises(ValueError, match="require a cancel path"):
        HighRiskDryRunDialogPlan(
            plan_id="no_cancel_path",
            feature_id="update_view",
            purpose="Plan only",
            target_dialog_name="FakeDialog",
            allowed_observations=("Observations",),
            cancel_path_observations=("Cancel",),
            forbidden_actions=tuple(sorted(REQUIRED_FORBIDDEN_ACTIONS)),
            non_destructive=True,
            requires_cancel_path=False,
        )

    with pytest.raises(ValueError, match="mock_service_not_called"):
        HighRiskDryRunDialogPlan(
            plan_id="no_mock_guarantee",
            feature_id="update_view",
            purpose="Plan only",
            target_dialog_name="FakeDialog",
            allowed_observations=("Observations",),
            cancel_path_observations=("Cancel",),
            forbidden_actions=tuple(sorted(REQUIRED_FORBIDDEN_ACTIONS)),
            non_destructive=True,
            mock_service_not_called=False,
        )

    missing_one_forbidden = tuple(
        action for action in sorted(REQUIRED_FORBIDDEN_ACTIONS) if action != "external fetch"
    )
    with pytest.raises(ValueError, match="external fetch"):
        HighRiskDryRunDialogPlan(
            plan_id="missing_forbidden_action",
            feature_id="update_view",
            purpose="Plan only",
            target_dialog_name="FakeDialog",
            allowed_observations=("Observations",),
            cancel_path_observations=("Cancel",),
            forbidden_actions=missing_one_forbidden,
            non_destructive=True,
        )


def test_get_high_risk_dry_run_dialog_plan_for_feature():
    update_plans = get_high_risk_dry_run_dialog_plan_for_feature("update_view")
    assert update_plans
    for plan in update_plans:
        assert plan.feature_id == "update_view"

    assert get_high_risk_dry_run_dialog_plan_for_feature("non_existent_feature") == ()


def test_render_high_risk_dry_run_dialog_plan_markdown():
    markdown = render_high_risk_dry_run_dialog_plan_markdown(get_high_risk_dry_run_dialog_plan_for_feature("update_view"))

    assert "D-4 is plan-only metadata" in markdown
    assert "Requires Explicit Confirmation" in markdown
    assert "database write" in markdown
    assert "sqlite_sync_confirm_dialog_plan" in markdown

    assert render_high_risk_dry_run_dialog_plan_markdown([]) == "- (None)"
