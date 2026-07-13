from app_module.engineering_closure_dashboard_service import EngineeringClosureDashboardService
from app_module.evidence_rehearsal_dtos import (
    CoverageMetric,
    EvidenceRehearsalReport,
    EvidenceRehearsalScenario,
    RehearsalArtifact,
)
from app_module.engineering_gate_registry import EngineeringGateItem
from app_module.gate_2_to_7_closeout_verifier import Gate2To7CloseoutReport


def _gate(category: str, status: str = "open") -> EngineeringGateItem:
    return EngineeringGateItem(
        item_id=f"{category}:item",
        revision=1,
        category=category,
        title=f"Review {category}",
        status=status,
        owner="owner",
        earliest_validation_date="2026-08-01",
        progress_bp=2500,
        required_artifacts=("artifact.json",),
        validation_commands=("python verify.py",),
        completion_rules=("review passes",),
        prohibited_actions=("do not auto apply",),
    )


def test_dashboard_separates_engineering_and_external_status() -> None:
    dashboard = EngineeringClosureDashboardService().build(
        closeout=Gate2To7CloseoutReport(
            engineering_package_status="complete",
            external_validation_status="pending",
            requirement_count=35,
            satisfied_count=35,
            blockers=(),
            external_gate_statuses=("open",),
        ),
        gates=(_gate("human_approval"), _gate("waiting_for_time", "waiting")),
    )

    assert dashboard.engineering_package_status == "complete"
    assert dashboard.external_validation_status == "pending"
    assert dashboard.open_gate_count == 2
    assert dashboard.category_counts == {"human_approval": 1, "waiting_for_time": 1}
    assert dashboard.read_only is True
    assert dashboard.write_actions_allowed is False


def test_dashboard_rows_expose_next_command_and_prohibited_actions() -> None:
    dashboard = EngineeringClosureDashboardService().build(
        closeout=Gate2To7CloseoutReport("complete", "pending", 1, 1, (), ("open",)),
        gates=(_gate("ml_revalidation"),),
    )

    row = dashboard.gates[0]
    assert row.next_command == "python verify.py"
    assert row.required_artifacts == ("artifact.json",)
    assert row.prohibited_actions == ("do not auto apply",)


def test_dashboard_projects_open_gates_to_read_only_workbench_actions() -> None:
    service = EngineeringClosureDashboardService()
    dashboard = service.build(
        closeout=Gate2To7CloseoutReport("complete", "pending", 1, 1, (), ("open",)),
        gates=(_gate("data_license"),),
    )

    actions = service.to_workbench_action_items(dashboard)
    assert len(actions) == 1
    assert actions[0].source_type == "engineering_closure_gate"
    assert actions[0].write_intent is False
    assert actions[0].drilldown_target == "evidence_review"


def test_completed_gate_is_not_added_to_action_queue() -> None:
    complete = EngineeringGateItem(
        item_id="done",
        revision=2,
        category="human_input",
        title="Done",
        status="complete",
        owner="owner",
        earliest_validation_date="2026-07-01",
        progress_bp=10000,
        required_artifacts=("a",),
        validation_commands=("c",),
        completion_rules=("r",),
        prohibited_actions=("p",),
        completion_evidence=("review.md",),
    )
    service = EngineeringClosureDashboardService()
    dashboard = service.build(
        closeout=Gate2To7CloseoutReport("complete", "complete", 1, 1, (), ("complete",)),
        gates=(complete,),
    )
    assert service.to_workbench_action_items(dashboard) == ()


def test_dashboard_projects_rehearsal_as_read_only_non_forward_evidence() -> None:
    rehearsal_report = EvidenceRehearsalReport(
        scenario=EvidenceRehearsalScenario(
            scenario_id="missing-source-rehearsal",
            decision_date="2026-07-13",
            source_db_path="C:/fixture/source.sqlite",
            working_copy_db_path="C:/fixture/working-copy.sqlite",
            tier="historical_replay_candidate",
        ),
        coverage_metrics=(
            CoverageMetric(
                source_id="p0_source",
                total_count=10,
                observed_count=0,
                degraded_count=0,
                missing_count=10,
                future_blocked_count=0,
                immature_label_count=0,
                coverage_bp=0,
            ),
        ),
        artifacts=(
            RehearsalArtifact(
                artifact_id="shadow-comparison",
                decision_date="2026-07-13",
                available_date="2026-07-13",
                tier="shadow_comparison",
                diagnostics=("source_outage:p0_source", "insufficient_sample"),
            ),
        ),
    )

    dashboard = EngineeringClosureDashboardService().compose(rehearsal_report)

    assert dashboard.tier == "historical_replay_candidate"
    assert dashboard.status == "blocked"
    assert dashboard.coverage == rehearsal_report.coverage_metrics
    assert "source_outage:p0_source" in dashboard.blockers
    assert "insufficient_sample" in dashboard.blockers
    assert "coverage_missing:p0_source=10" in dashboard.blockers
    assert dashboard.write_intent is False
    assert "工程／Replay／Shadow；不是 forward evidence" == dashboard.disclosure
