import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW_FILES = (
    ROOT / "ui_qt" / "views" / "backtest_view.py",
    ROOT / "ui_qt" / "views" / "recommendation_view.py",
    ROOT / "ui_qt" / "views" / "update_view.py",
    ROOT / "ui_qt" / "views" / "workbench_view.py",
    ROOT / "ui_qt" / "main.py",
)
FORBIDDEN_CORE_CALLS = {
    "run_backtest",
    "run_batch_backtest",
    "grid_search",
    "train_test_split",
    "walk_forward",
    "run_recommendation",
    "update_daily",
    "update_market",
    "update_industry",
    "update_broker_branch",
    "sync_source_to_sqlite",
}


def test_ui_shells_do_not_call_core_execution_entrypoints_directly() -> None:
    violations = []
    for path in VIEW_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in FORBIDDEN_CORE_CALLS:
                    violations.append(f"{path.name}:{node.lineno}:{node.func.attr}")
    assert violations == []


def test_large_presenter_and_orchestration_methods_are_thin_delegates() -> None:
    expected_limits = {
        ("backtest_view.py", "_format_summary"): 4,
        ("recommendation_view.py", "_generate_why_not"): 4,
        ("recommendation_view.py", "_format_recommendation_reason"): 9,
        ("recommendation_view.py", "_generate_explain_panel"): 4,
        ("update_view.py", "_run_update_all"): 16,
    }
    sizes = {}
    for path in VIEW_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                sizes[(path.name, node.name)] = node.end_lineno - node.lineno + 1
    assert {
        key: sizes[key] for key in expected_limits
    } == {
        key: sizes[key] for key in expected_limits if sizes[key] <= expected_limits[key]
    }
