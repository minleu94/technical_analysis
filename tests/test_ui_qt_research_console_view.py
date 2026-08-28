from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app_module.research_console_dtos import (
    ResearchArtifactRowDTO,
    ResearchConsoleBoundaryDTO,
    ResearchConsoleDTO,
    ResearchGateCardDTO,
    ResearchPipelineRowDTO,
    ResearchSourceRowDTO,
)
from ui_qt.views.research_console_view import ResearchConsoleView


def app() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def _console() -> ResearchConsoleDTO:
    return ResearchConsoleDTO(
        overall_status="degraded",
        source_reference="fixture:ResearchConsoleProjection.v1",
        boundary=ResearchConsoleBoundaryDTO(),
        pipeline=(
            ResearchPipelineRowDTO(
                component_id="dataset",
                label="Development Dataset V0",
                identity="dataset:g-1",
                status="research_only_degraded",
                cutoff="2025-12-31",
                feature_interval="2025-01-01..2025-12-31",
                label_maturity="2025-12-31",
                row_count=48,
                eligible_count=40,
                feature_count=20,
            ),
            ResearchPipelineRowDTO(
                component_id="rule",
                label="Rule Development Baseline",
                identity="sha256:rule",
                status="research_baseline",
            ),
            ResearchPipelineRowDTO(
                component_id="ml",
                label="ML Development Challenger",
                identity="sha256:run",
                status="development_challenger",
            ),
            ResearchPipelineRowDTO(
                component_id="e2e",
                label="Development E2E Run",
                identity="sha256:run",
                status="degraded",
                artifact_path="fixture/projection.json",
                artifact_hash="sha256:projection",
                generated_at="2026-07-13T12:00:00Z",
                blockers=("research_only_degraded",),
            ),
        ),
        gates=tuple(
            ResearchGateCardDTO(
                gate_id=f"EV{index}",
                label=f"EV{index}",
                status="missing" if index != 2 else "provisional",
                detail="Development projection only",
            )
            for index in range(1, 6)
        ),
        sources=(
            ResearchSourceRowDTO(
                source_id="institutional_flows",
                label="Institutional Flows",
                lane="p0",
                status="candidate",
                allowed_use="Development Only",
                observed_rows=12,
            ),
            ResearchSourceRowDTO(
                source_id="broker_dataset",
                label="Broker Dataset",
                lane="broker",
                status="degraded",
                allowed_use="Research Only",
            ),
        ),
        artifacts=(
            ResearchArtifactRowDTO(
                artifact_type="dataset_manifest",
                artifact_id="sha256:manifest",
                status="development_only",
                citation="projection.lineage.dataset_manifest_hash",
            ),
        ),
        frozen_metrics={"sample_count": 48, "coverage_bp": 10000},
        blockers=("research_only_degraded",),
    )


def test_missing_console_opens_and_shows_fail_closed_boundary() -> None:
    app()
    view = ResearchConsoleView(auto_refresh=False)

    text = view.visible_text()
    assert "Safety Boundary" in text
    assert "formal_oos_allowed = False" in text
    assert "production_blend_alpha_bp = 0" in text
    assert "Production ML: Disabled" in text
    assert "Missing" in text
    assert "EV1" in text and "EV5" in text
    assert "P0 Data Source Control Center" in text
    assert "Downstream eligible：0" in text
    assert view.control_center_table.rowCount() == 13
    assert view.control_center_table.horizontalHeaderItem(5).text() == "PIT / 解析通過率"


def test_fixture_renders_pipeline_gates_sources_and_separate_broker_lane() -> None:
    app()
    view = ResearchConsoleView(console=_console(), auto_refresh=False)

    text = view.visible_text()
    assert "Development Pipeline" in text
    assert "dataset:g-1" in text
    assert "Rule Development Baseline" in text
    assert "ML Development Challenger" in text
    assert "Evidence / Source Gates" in text
    assert "Institutional Flows" in text
    assert "Broker Dataset（獨立 lane）" in text
    assert "sha256:manifest" in text
    assert view.pipeline_table.rowCount() == 4
    assert view.gate_table.rowCount() == 5


def test_view_has_no_apply_promote_retrain_blend_accept_or_trade_controls() -> None:
    app()
    view = ResearchConsoleView(console=_console(), auto_refresh=False)

    forbidden = ("apply", "promote", "retrain", "blend", "accept source", "trade", "套用", "升級", "交易")
    button_texts = [button.text().lower() for button in view.findChildren(QPushButton)]
    assert button_texts == ["重新載入唯讀 projection"]
    assert not any(token in text for text in button_texts for token in forbidden)


def test_view_source_has_no_domain_or_database_imports() -> None:
    source_path = Path("ui_qt/views/research_console_view.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    forbidden_prefixes = (
        "sqlite3",
        "data_module",
        "ml_module",
        "development_module",
        "decision_module.scoring",
        "portfolio_module",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imported)
