import os
from pathlib import Path

from qa.full_app_healthcheck.test_inventory import (
    BRIDGE_REJECTED_CATEGORIES,
    PYTEST_COLLECTED_FILES,
    PYTEST_NOT_COLLECTED_FILES,
    PYTEST_SUPPORT_FILES,
    TEST_INVENTORY,
    get_bridge_rejected_files,
    get_candidate_bridge_files,
    get_category,
    get_direct_bridge_files,
    get_files_by_category,
    get_pytest_collection_status,
    get_reject_reason,
    is_collected_by_default_pytest,
    is_allowed_in_bridge,
)


def test_all_python_files_in_tests_are_registered_exactly_once():
    tests_dir = Path(__file__).resolve().parent.parent / "tests"

    found_files = []
    for root, dirs, files in os.walk(str(tests_dir)):
        if "__pycache__" in root or ".pytest_cache" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                full_path = Path(root) / file
                # Compute path relative to project root (technical_analysis/)
                rel_path = full_path.relative_to(tests_dir.parent).as_posix()
                found_files.append(rel_path)

    # Check for missing files in registry
    missing = [f for f in found_files if f not in TEST_INVENTORY]
    assert not missing, f"下列 Python 檔案未在 test_inventory.py 中註冊分類：\n" + "\n".join(missing)

    # Check for extra files in registry that do not exist on disk
    extra = []
    for f in TEST_INVENTORY:
        full_p = tests_dir.parent / f
        if not full_p.exists():
            extra.append(f)
    assert not extra, f"test_inventory.py 中有已註冊但實際不存在的檔案：\n" + "\n".join(extra)


def test_legacy_diagnostics_relocated_paths_exist_and_classified():
    moved_candidates = (
        "tests/manual/legacy_diagnostics/run_market_index_test.py",
        "tests/manual/legacy_diagnostics/run_technical_calc_test.py",
        "tests/manual/legacy_diagnostics/run_tests.py",
        "tests/manual/legacy_diagnostics/check_columns.py",
        "tests/manual/legacy_diagnostics/check_processed_file.py",
        "tests/manual/legacy_diagnostics/check_saved_file.py",
        "tests/manual/legacy_diagnostics/check_signals_file.py",
    )
    for path in moved_candidates:
        assert path in TEST_INVENTORY
        assert get_category(path) == "legacy-or-low-priority"
        assert not is_allowed_in_bridge(path)
        assert get_reject_reason(path) is not None


def test_safety_guardrails_reject_unauthorized_categories():
    # manual, scripts, write-risk, manual-only, legacy diagnostics should all be rejected
    rejected_paths = (
        "tests/manual/legacy_advanced_patterns_check.py",
        "tests/scripts/test_all_branches_one_day.py",
        "tests/test_fundamental_migration.py",
        "tests/e2e/test_data_path_isolation.py",
    )
    for path in rejected_paths:
        assert not is_allowed_in_bridge(path)
        assert get_reject_reason(path) is not None


def test_direct_bridge_only_allows_the_six_ui_tests():
    allowed_ui_tests = {
        "tests/test_ui_qt_decision_desk_view.py",
        "tests/test_ui_qt_market_regime_view.py",
        "tests/test_ui_qt_research_workflow.py",
        "tests/test_ui_qt_run_registry_compare.py",
        "tests/test_ui_qt_smart_money_flow_view.py",
        "tests/test_ui_qt_update_view_workbench.py",
    }

    # Verify allowed ones
    for path in allowed_ui_tests:
        assert is_allowed_in_bridge(path)
        assert get_reject_reason(path) is None

    # Verify no other files are allowed
    for path, category in TEST_INVENTORY.items():
        if path not in allowed_ui_tests:
            assert not is_allowed_in_bridge(path), f"測試檔 {path} 不應被允許進入 direct bridge，其分類為：{category}"

def test_inventory_exposes_bridge_candidate_and_reject_sets():
    assert get_direct_bridge_files() == {
        "tests/test_ui_qt_decision_desk_view.py",
        "tests/test_ui_qt_market_regime_view.py",
        "tests/test_ui_qt_research_workflow.py",
        "tests/test_ui_qt_run_registry_compare.py",
        "tests/test_ui_qt_smart_money_flow_view.py",
        "tests/test_ui_qt_update_view_workbench.py",
    }
    assert "tests/test_ui_qt_portfolio_view.py" in get_candidate_bridge_files()
    assert "tests/manual/legacy_diagnostics/run_tests.py" in get_bridge_rejected_files()
    assert "write-risk-dry-run-required" in BRIDGE_REJECTED_CATEGORIES


def test_inventory_exposes_pytest_collection_statuses():
    assert len(PYTEST_COLLECTED_FILES) == 166
    assert len(PYTEST_SUPPORT_FILES) == 1
    assert len(PYTEST_NOT_COLLECTED_FILES) == 30

    assert is_collected_by_default_pytest("tests/test_full_app_healthcheck_test_inventory.py")
    assert get_pytest_collection_status("tests/test_full_app_healthcheck_test_inventory.py") == "collected"
    assert get_pytest_collection_status("tests/conftest.py") == "support"
    assert get_pytest_collection_status("tests/manual/legacy_diagnostics/run_tests.py") == "not-collected"
    assert get_pytest_collection_status("tests/does_not_exist.py") == "unknown"


def test_inventory_can_query_category_groups():
    assert len(get_files_by_category("healthcheck-runner-owned")) == 17
    assert len(get_files_by_category("legacy-or-low-priority")) == 9



    assert "tests/test_pattern_analysis/test_flag_pattern_robustness.py" in get_files_by_category(
        "service-oracle-research-backtest"
    )
