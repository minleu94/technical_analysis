from __future__ import annotations

from pathlib import Path

import pytest

from qa.full_app_healthcheck.feature_router import FEATURE_ROUTES
from qa.full_app_healthcheck.viewport_resize_evidence_plan import (
    FORBIDDEN_VIEWPORT_RESIZE_ACTIONS,
    VALID_VIEWPORT_SIZES,
    ViewportResizeEvidencePlan,
    get_viewport_resize_evidence_plan,
    get_viewport_resize_evidence_plan_for_feature,
    render_viewport_resize_evidence_plan_markdown,
)
from qa.full_app_healthcheck.test_suite_bridge import build_existing_suite_registry


def test_viewport_resize_evidence_plan_integrity_and_boundaries():
    plans = get_viewport_resize_evidence_plan()
    assert plans

    bridge_suite_ids = {suite.id for suite in build_existing_suite_registry()}

    for plan in plans:
        assert isinstance(plan, ViewportResizeEvidencePlan)
        assert plan.feature_id in FEATURE_ROUTES
        assert plan.non_destructive is True
        assert plan.requires_explicit_user_confirmation is True
        assert plan.allowed_observations
        assert plan.forbidden_actions
        assert plan.evidence_id not in bridge_suite_ids

        # Ensure all valid sizes are used
        for size in plan.viewport_sizes:
            assert size in VALID_VIEWPORT_SIZES

        forbidden_text = " ".join(plan.forbidden_actions).lower()
        for forbidden_action in FORBIDDEN_VIEWPORT_RESIZE_ACTIONS:
            assert forbidden_action in forbidden_text

        observation_text = " ".join(plan.allowed_observations).lower()
        assert "write" not in observation_text
        assert "migration" not in observation_text
        assert "backfill apply" not in observation_text
        assert "external fetch" not in observation_text
        assert "high-risk dry-run" not in observation_text


def test_viewport_resize_evidence_plan_does_not_import_qt_or_runner_execution():
    module_source = Path("qa/full_app_healthcheck/viewport_resize_evidence_plan.py").read_text(encoding="utf-8")

    assert "PySide6" not in module_source
    assert "QApplication" not in module_source
    assert "QTest." not in module_source
    assert "run_full_app_healthcheck" not in module_source


def test_viewport_resize_evidence_plan_rejects_unsafe_metadata():
    with pytest.raises(ValueError, match="Unknown feature_id"):
        ViewportResizeEvidencePlan(
            evidence_id="bad_feature",
            feature_id="does_not_exist",
            purpose="Plan only",
            viewport_sizes=("1366x768",),
            allowed_observations=("Observations",),
            forbidden_actions=tuple(sorted(FORBIDDEN_VIEWPORT_RESIZE_ACTIONS)),
            non_destructive=True,
        )

    with pytest.raises(ValueError, match="non-destructive"):
        ViewportResizeEvidencePlan(
            evidence_id="destructive",
            feature_id="update_view",
            purpose="Plan only",
            viewport_sizes=("1366x768",),
            allowed_observations=("Observations",),
            forbidden_actions=tuple(sorted(FORBIDDEN_VIEWPORT_RESIZE_ACTIONS)),
            non_destructive=False,
        )

    with pytest.raises(ValueError, match="explicit user confirmation"):
        ViewportResizeEvidencePlan(
            evidence_id="no_confirmation",
            feature_id="update_view",
            purpose="Plan only",
            viewport_sizes=("1366x768",),
            allowed_observations=("Observations",),
            forbidden_actions=tuple(sorted(FORBIDDEN_VIEWPORT_RESIZE_ACTIONS)),
            non_destructive=True,
            requires_explicit_user_confirmation=False,
        )

    with pytest.raises(ValueError, match="Invalid viewport size"):
        ViewportResizeEvidencePlan(
            evidence_id="invalid_size",
            feature_id="update_view",
            purpose="Plan only",
            viewport_sizes=("800x600",),
            allowed_observations=("Observations",),
            forbidden_actions=tuple(sorted(FORBIDDEN_VIEWPORT_RESIZE_ACTIONS)),
            non_destructive=True,
        )

    missing_one_forbidden = tuple(
        action for action in sorted(FORBIDDEN_VIEWPORT_RESIZE_ACTIONS) if action != "external fetch"
    )
    with pytest.raises(ValueError, match="external fetch"):
        ViewportResizeEvidencePlan(
            evidence_id="missing_forbidden_action",
            feature_id="update_view",
            purpose="Plan only",
            viewport_sizes=("1366x768",),
            allowed_observations=("Observations",),
            forbidden_actions=missing_one_forbidden,
            non_destructive=True,
        )


def test_get_viewport_resize_evidence_plan_for_feature():
    update_plans = get_viewport_resize_evidence_plan_for_feature("update_view")
    assert update_plans
    for plan in update_plans:
        assert plan.feature_id == "update_view"

    assert get_viewport_resize_evidence_plan_for_feature("non_existent_feature") == ()


def test_render_viewport_resize_evidence_plan_markdown():
    markdown = render_viewport_resize_evidence_plan_markdown(get_viewport_resize_evidence_plan_for_feature("update_view"))

    assert "D-3 is plan-only metadata" in markdown
    assert "Requires Explicit Confirmation" in markdown
    assert "database write" in markdown
    assert "update_view_viewport_evidence" in markdown

    assert render_viewport_resize_evidence_plan_markdown([]) == "- (None)"
