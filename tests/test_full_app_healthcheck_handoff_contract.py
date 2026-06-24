from qa.full_app_healthcheck.handoff_contract import (
    build_handoff_recommendations,
    render_handoff_markdown,
)
from qa.full_app_healthcheck.manifest import HealthcheckMode
from qa.full_app_healthcheck.result_interpreter import (
    FeatureInterpretation,
    HealthcheckInterpretation,
    render_interpretation_markdown,
)


def _feature(
    feature_id: str,
    *,
    status: str,
    owner: str,
    evidence: str,
    next_steps: str,
    matched: list[str] | None = None,
    failed: list[str] | None = None,
) -> FeatureInterpretation:
    return FeatureInterpretation(
        feature_id=feature_id,
        display_name=feature_id.replace("_", " ").title(),
        status=status,
        matched_suite_ids=matched or [],
        failed_suite_ids=failed or [],
        evidence_summary=evidence,
        likely_owner=owner,
        recommended_next_steps=next_steps,
        known_gaps=[],
    )


def test_handoff_contract_groups_actionable_features_by_likely_owner():
    interpretation = HealthcheckInterpretation(
        overall_status="failed",
        mode=HealthcheckMode.QUICK,
        feature_results={
            "update_view": _feature(
                "update_view",
                status="needs_data_audit",
                owner="data_audit",
                evidence="daily_prices available_date schema mismatch in qa-update-tab",
                next_steps="Check available_date freshness and SQLite schema.",
                matched=["qa-update-tab"],
                failed=["qa-update-tab"],
            ),
            "decision_desk": _feature(
                "decision_desk",
                status="failed",
                owner="execution",
                evidence="Button is hidden after layout refresh.",
                next_steps="Repair widget visibility binding.",
                matched=["ui-decision-desk"],
                failed=["ui-decision-desk"],
            ),
            "market_regime": _feature(
                "market_regime",
                status="not_run",
                owner="testing_qa",
                evidence="This feature is unsupported in Quick Mode.",
                next_steps="No action required; run Full Mode for this feature.",
            ),
            "smart_money": _feature(
                "smart_money",
                status="passed",
                owner="testing_qa",
                evidence="All suites passed.",
                next_steps="None.",
            ),
        },
        runner_failures=[],
        data_audit_recommendations=["Compare SQLite schema with daily price CSV integration"],
        manual_gaps=[],
    )

    handoffs = build_handoff_recommendations(interpretation)

    assert {handoff.target_owner for handoff in handoffs} == {"data_audit", "execution"}
    by_owner = {handoff.target_owner: handoff for handoff in handoffs}
    assert by_owner["data_audit"].source_feature_ids == ("update_view",)
    assert by_owner["data_audit"].source_failure_ids == ("qa-update-tab",)
    assert any("daily_prices" in item for item in by_owner["data_audit"].evidence)
    assert any("Compare SQLite schema" in item for item in by_owner["data_audit"].recommended_next_steps)
    assert by_owner["execution"].source_feature_ids == ("decision_desk",)
    assert by_owner["execution"].severity == "error"


def test_handoff_contract_adds_testing_qa_runner_failure_handoff():
    interpretation = HealthcheckInterpretation(
        overall_status="failed",
        mode=HealthcheckMode.QUICK,
        feature_results={},
        runner_failures=[
            {
                "id": "unknown-suite",
                "error": "Unmatched suite id",
                "suite": {"returncode": 1},
            }
        ],
        data_audit_recommendations=[],
        manual_gaps=[],
    )

    handoffs = build_handoff_recommendations(interpretation)

    assert len(handoffs) == 1
    handoff = handoffs[0]
    assert handoff.target_owner == "testing_qa"
    assert handoff.source_failure_ids == ("unknown-suite",)
    assert any("unknown-suite" in item for item in handoff.evidence)
    assert any("feature_router.py" in item for item in handoff.recommended_next_steps)


def test_handoff_markdown_is_paste_ready_by_owner():
    handoffs = build_handoff_recommendations(
        HealthcheckInterpretation(
            overall_status="needs_data_audit",
            mode=HealthcheckMode.QUICK,
            feature_results={
                "update_view": _feature(
                    "update_view",
                    status="needs_data_audit",
                    owner="data_audit",
                    evidence="SQLite schema changed.",
                    next_steps="Validate schema before rerun.",
                    matched=["qa-update-tab"],
                    failed=["qa-update-tab"],
                ),
            },
            runner_failures=[],
            data_audit_recommendations=[],
            manual_gaps=[],
        )
    )

    markdown = render_handoff_markdown(handoffs)

    assert "## Data Audit Agent" in markdown
    assert "- Likely Owner: `data_audit`" in markdown
    assert "- [ ] Validate schema before rerun." in markdown
    assert "qa-update-tab" in markdown


def test_interpretation_markdown_includes_handoff_recommendations_section():
    interpretation = HealthcheckInterpretation(
        overall_status="failed",
        mode=HealthcheckMode.QUICK,
        feature_results={
            "decision_desk": _feature(
                "decision_desk",
                status="failed",
                owner="execution",
                evidence="Widget visibility assertion failed.",
                next_steps="Repair Decision Desk widget binding.",
                matched=["ui-decision-desk"],
                failed=["ui-decision-desk"],
            ),
        },
        runner_failures=[],
        data_audit_recommendations=[],
        manual_gaps=[],
    )

    markdown = render_interpretation_markdown(interpretation)

    assert "## Handoff Recommendations" in markdown
    assert "## Execution Agent" in markdown
    assert "- [ ] Repair Decision Desk widget binding." in markdown
