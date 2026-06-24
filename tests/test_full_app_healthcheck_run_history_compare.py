import inspect
import pytest

from qa.full_app_healthcheck.run_history_compare import (
    FeatureStatusChange,
    compare_run_history_manifests,
    render_run_history_comparison_markdown,
)
from qa.full_app_healthcheck.run_history_manifest import (
    FeatureRunRecord,
    SuiteRunRecord,
    build_run_history_manifest,
)


def _manifest(
    *,
    run_id: str,
    suite_results: tuple[SuiteRunRecord, ...],
    feature_results: tuple[FeatureRunRecord, ...],
    manual_gaps: tuple[str, ...] = (),
):
    return build_run_history_manifest(
        run_id=run_id,
        commit=f"{run_id}-commit",
        mode="quick",
        viewport=None,
        suite_results=suite_results,
        feature_results=feature_results,
        manual_gaps=manual_gaps,
        generated_at="2026-06-23T22:30:00Z",
    )


def test_compare_run_history_manifests_detects_suite_and_gap_deltas():
    baseline = _manifest(
        run_id="baseline",
        suite_results=(
            SuiteRunRecord("suite_fixed", "failed", "pytest fixed", 1.0, None),
            SuiteRunRecord("suite_regressed", "passed", "pytest regressed", 1.0, None),
            SuiteRunRecord("suite_removed", "passed", "pytest removed", 1.0, None),
            SuiteRunRecord("suite_still_failed", "failed", "pytest still", 1.0, None),
        ),
        feature_results=(),
        manual_gaps=("old gap",),
    )
    candidate = _manifest(
        run_id="candidate",
        suite_results=(
            SuiteRunRecord("suite_fixed", "passed", "pytest fixed", 1.0, None),
            SuiteRunRecord("suite_regressed", "failed", "pytest regressed", 1.0, None),
            SuiteRunRecord("suite_added", "passed", "pytest added", 1.0, None),
            SuiteRunRecord("suite_still_failed", "failed", "pytest still", 1.0, None),
        ),
        feature_results=(),
        manual_gaps=("new gap",),
    )

    comparison = compare_run_history_manifests(baseline, candidate)

    assert comparison.baseline_run_id == "baseline"
    assert comparison.candidate_run_id == "candidate"
    assert comparison.added_suite_ids == ("suite_added",)
    assert comparison.removed_suite_ids == ("suite_removed",)
    assert comparison.fixed_suite_ids == ("suite_fixed",)
    assert comparison.regressed_suite_ids == ("suite_regressed",)
    assert comparison.unchanged_failing_suite_ids == ("suite_still_failed",)
    assert comparison.new_manual_gaps == ("new gap",)
    assert comparison.resolved_manual_gaps == ("old gap",)


def test_compare_run_history_manifests_detects_feature_status_changes():
    baseline = _manifest(
        run_id="baseline",
        suite_results=(),
        feature_results=(
            FeatureRunRecord("update_view", "passed", "quick", "baseline ok"),
            FeatureRunRecord("decision_desk", "manual-gap", "quick", "needs copy"),
        ),
    )
    candidate = _manifest(
        run_id="candidate",
        suite_results=(),
        feature_results=(
            FeatureRunRecord("update_view", "passed", "quick", "candidate ok"),
            FeatureRunRecord("decision_desk", "passed", "full", "gap closed"),
        ),
    )

    comparison = compare_run_history_manifests(baseline, candidate)

    assert comparison.feature_status_changes == (
        FeatureStatusChange(
            feature_id="decision_desk",
            baseline_status="manual-gap",
            candidate_status="passed",
            baseline_route_mode="quick",
            candidate_route_mode="full",
            summary="decision_desk changed from manual-gap to passed.",
        ),
    )


def test_render_run_history_comparison_markdown_is_readable():
    baseline = _manifest(
        run_id="baseline",
        suite_results=(SuiteRunRecord("suite_fixed", "failed", "pytest fixed", 1.0, None),),
        feature_results=(FeatureRunRecord("update_view", "manual-gap", "quick", "baseline gap"),),
        manual_gaps=("old gap",),
    )
    candidate = _manifest(
        run_id="candidate",
        suite_results=(SuiteRunRecord("suite_fixed", "passed", "pytest fixed", 1.0, None),),
        feature_results=(FeatureRunRecord("update_view", "passed", "quick", "candidate ok"),),
        manual_gaps=(),
    )

    markdown = render_run_history_comparison_markdown(compare_run_history_manifests(baseline, candidate))

    assert "# Run History Comparison" in markdown
    assert "`baseline`" in markdown
    assert "`candidate`" in markdown
    assert "Fixed suites" in markdown
    assert "`suite_fixed`" in markdown
    assert "Resolved manual gaps" in markdown
    assert "old gap" in markdown
    assert "| `update_view` | `manual-gap` | `passed` | `quick` |" in markdown


def test_compare_run_history_manifests_rejects_non_manifest_inputs():
    manifest = _manifest(run_id="baseline", suite_results=(), feature_results=())

    with pytest.raises(TypeError, match="baseline must be"):
        compare_run_history_manifests(object(), manifest)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="candidate must be"):
        compare_run_history_manifests(manifest, object())  # type: ignore[arg-type]


def test_feature_status_change_rejects_invalid_values():
    with pytest.raises(ValueError, match="Invalid baseline_status"):
        FeatureStatusChange(
            feature_id="update_view",
            baseline_status="unknown",
            candidate_status="passed",
            baseline_route_mode="quick",
            candidate_route_mode="quick",
            summary="invalid",
        )


def test_run_history_compare_has_no_execution_or_write_side_effects():
    import qa.full_app_healthcheck.run_history_compare as module

    module_source = inspect.getsource(module)

    assert "Path(" not in module_source
    assert "write_text" not in module_source
    assert "write_bytes" not in module_source
    assert "open(" not in module_source
    assert ".write(" not in module_source
    assert "run_full_app_healthcheck" not in module_source
    assert "PySide6" not in module_source
    assert "QApplication" not in module_source
    assert "MainWindow" not in module_source
