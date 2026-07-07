from __future__ import annotations

import ast
from pathlib import Path


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _assert_no_forbidden_imports(path: Path, forbidden_prefixes: tuple[str, ...]) -> None:
    modules = _imported_modules(path)
    forbidden = {
        module
        for module in modules
        if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden_prefixes)
    }
    assert forbidden == set()


def test_workbench_composer_stays_dto_only_without_direct_db_replay_scheduler_or_lifecycle_imports() -> None:
    _assert_no_forbidden_imports(
        Path("app_module/workbench_read_only_composer.py"),
        (
            "sqlite3",
            "data_module",
            "app_module.workbench_source_service",
            "app_module.historical_evidence_replay",
            "app_module.evidence_pipeline_runner",
            "app_module.strategy_lifecycle_service",
            "app_module.strategy_lifecycle_repository",
            "app_module.portfolio_service",
            "app_module.backtest_service",
            "portfolio_module",
            "backtest_module",
            "decision_module",
            "runtime",
        ),
    )


def test_workbench_dtos_stay_pure_payload_without_db_replay_scheduler_or_lifecycle_imports() -> None:
    _assert_no_forbidden_imports(
        Path("app_module/workbench_dtos.py"),
        (
            "sqlite3",
            "data_module",
            "app_module.workbench_source_service",
            "app_module.historical_evidence_replay",
            "app_module.evidence_pipeline_runner",
            "app_module.strategy_lifecycle_service",
            "app_module.strategy_lifecycle_repository",
            "app_module.portfolio_service",
            "app_module.backtest_service",
            "portfolio_module",
            "backtest_module",
            "decision_module",
            "runtime",
        ),
    )


def test_workbench_qt_view_and_models_keep_db_replay_scheduler_lifecycle_out_of_ui_boundary() -> None:
    forbidden = (
        "sqlite3",
        "data_module.db_manager",
        "app_module.historical_evidence_replay",
        "app_module.evidence_pipeline_runner",
        "app_module.strategy_lifecycle_service",
        "app_module.strategy_lifecycle_repository",
        "app_module.portfolio_service",
        "app_module.backtest_service",
        "app_module.recommendation_service",
        "portfolio_module",
        "backtest_module",
        "decision_module.scoring_engine",
        "decision_module.stock_screener",
        "runtime",
    )
    for path in (
        Path("ui_qt/views/workbench_view.py"),
        Path("ui_qt/models/workbench_table_models.py"),
    ):
        _assert_no_forbidden_imports(path, forbidden)
