from __future__ import annotations

from pathlib import Path

import pytest

from qa.full_app_healthcheck.run_history_manifest import (
    FeatureRunRecord,
    RunHistoryManifest,
    SuiteRunRecord,
    build_run_history_manifest,
    render_run_history_manifest_markdown,
)


def test_run_history_manifest_in_memory_only_and_integrity():
    # Constructing records in-memory
    suite1 = SuiteRunRecord(
        suite_id="test_suite_1",
        status="passed",
        command="pytest tests/test_1.py",
        duration_seconds=1.23,
        evidence_path="output/evidence_1.json",
    )
    feature1 = FeatureRunRecord(
        feature_id="update_view",
        status="passed",
        route_mode="quick",
        evidence_summary="Daily price sqlite sync verified.",
    )
    manifest = build_run_history_manifest(
        run_id="run_20260623_220000",
        commit="c454854",
        mode="quick",
        viewport="1920x1080",
        suite_results=(suite1,),
        feature_results=(feature1,),
        manual_gaps=("Manual verification gap on TWSE price bounds",),
        generated_at="2026-06-23T22:00:00",
    )

    assert manifest.run_id == "run_20260623_220000"
    assert manifest.commit == "c454854"
    assert manifest.mode == "quick"
    assert manifest.viewport == "1920x1080"
    assert len(manifest.suite_results) == 1
    assert manifest.suite_results[0].suite_id == "test_suite_1"
    assert len(manifest.feature_results) == 1
    assert manifest.feature_results[0].feature_id == "update_view"
    assert manifest.manual_gaps == ("Manual verification gap on TWSE price bounds",)
    assert manifest.generated_at == "2026-06-23T22:00:00"


def test_run_history_manifest_invalid_inputs():
    with pytest.raises(ValueError, match="Invalid mode"):
        RunHistoryManifest(
            run_id="run_123",
            commit="c454854",
            mode="invalid_mode",
            viewport=None,
            suite_results=(),
            feature_results=(),
            manual_gaps=(),
            generated_at="now",
        )

    with pytest.raises(ValueError, match="Invalid status"):
        SuiteRunRecord(
            suite_id="suite_1",
            status="invalid_status",
            command="cmd",
            duration_seconds=None,
            evidence_path=None,
        )

    with pytest.raises(ValueError, match="duration_seconds"):
        SuiteRunRecord(
            suite_id="suite_1",
            status="passed",
            command="cmd",
            duration_seconds=-0.1,
            evidence_path=None,
        )

    with pytest.raises(ValueError, match="Unknown feature_id"):
        FeatureRunRecord(
            feature_id="invalid_feature_id",
            status="passed",
            route_mode="quick",
            evidence_summary="ok",
        )

    with pytest.raises(ValueError, match="Invalid route_mode"):
        FeatureRunRecord(
            feature_id="update_view",
            status="passed",
            route_mode="unsafe-mode",
            evidence_summary="ok",
        )

    with pytest.raises(TypeError, match="SuiteRunRecord"):
        RunHistoryManifest(
            run_id="run_123",
            commit="c454854",
            mode="quick",
            viewport=None,
            suite_results=("not_a_record",),  # type: ignore
            feature_results=(),
            manual_gaps=(),
            generated_at="now",
        )

    with pytest.raises(TypeError, match="FeatureRunRecord"):
        RunHistoryManifest(
            run_id="run_123",
            commit="c454854",
            mode="quick",
            viewport=None,
            suite_results=(),
            feature_results=("not_a_record",),  # type: ignore
            manual_gaps=(),
            generated_at="now",
        )


def test_run_history_manifest_markdown_rendering():
    suite1 = SuiteRunRecord(
        suite_id="test_suite_1",
        status="passed",
        command="pytest tests/test_1.py",
        duration_seconds=1.23,
        evidence_path="output/evidence_1.json",
    )
    feature1 = FeatureRunRecord(
        feature_id="update_view",
        status="passed",
        route_mode="quick",
        evidence_summary="Daily price sqlite sync verified.",
    )
    manifest = RunHistoryManifest(
        run_id="run_20260623_220000",
        commit="c454854",
        mode="quick",
        viewport="1920x1080",
        suite_results=(suite1,),
        feature_results=(feature1,),
        manual_gaps=("Manual verification gap on TWSE price bounds",),
        generated_at="2026-06-23T22:00:00",
    )

    markdown = render_run_history_manifest_markdown(manifest)

    assert "Run History Manifest - `run_20260623_220000`" in markdown
    assert "c454854" in markdown
    assert "1920x1080" in markdown
    assert "quick" in markdown
    assert "test_suite_1" in markdown
    assert "update_view" in markdown
    assert "Manual verification gap on TWSE price bounds" in markdown


def test_run_history_manifest_no_side_effects():
    # Ensure run_history_manifest.py doesn't write files or import Qt
    module_source = Path("qa/full_app_healthcheck/run_history_manifest.py").read_text(encoding="utf-8")

    assert "Path(" not in module_source
    assert "write_text" not in module_source
    assert "write_bytes" not in module_source
    assert "open(" not in module_source
    assert ".write(" not in module_source
    assert "PySide6" not in module_source
    assert "QApplication" not in module_source
    assert "run_full_app_healthcheck" not in module_source
