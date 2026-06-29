import os
import sys
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget, QTabWidget, QLabel

from qa.full_app_healthcheck.manifest import HealthcheckStep, HealthcheckMode, RiskLevel
from qa.full_app_healthcheck.actions import (
    collect_mainwindow_smoke_evidence,
    find_child_by_object_name,
    assert_widget_visible,
    assert_tab_exists,
    assert_text_contains,
    assert_viewport_declared,
)
from qa.full_app_healthcheck.mainwindow_smoke import EXPECTED_MAINWINDOW_TAB_LABELS


def ensure_qapp():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_find_child_by_object_name():
    ensure_qapp()
    parent = QWidget()
    child = QWidget(parent)
    child.setObjectName("my_target")

    assert find_child_by_object_name(parent, "my_target") is child

    with pytest.raises(AssertionError, match="找不到 objectName 為 'non_existent' 的元件"):
        find_child_by_object_name(parent, "non_existent")


def test_assert_widget_visible():
    ensure_qapp()
    parent = QWidget()
    child = QWidget(parent)
    child.setObjectName("my_widget")

    step = HealthcheckStep(
        id="my_widget",
        title="測試元件可見",
        mode=HealthcheckMode.QUICK,
        workspace="測試",
        action="assert_widget_visible",
        risk=RiskLevel.UI_ONLY,
    )

    # Initially child is invisible because parent is not shown
    context = {"window": parent}
    with pytest.raises(AssertionError, match="元件 'my_widget' 目前為不可見狀態"):
        assert_widget_visible(context, step)

    # Force visible
    parent.show()
    child.show()
    res = assert_widget_visible(context, step)
    assert res["visible"] is True


def test_assert_tab_exists():
    ensure_qapp()
    parent = QWidget()
    tabs = QTabWidget(parent)
    tabs.addTab(QWidget(), "數據更新")
    tabs.addTab(QWidget(), "市場觀察")

    step = HealthcheckStep(
        id="test_tab",
        title="分頁存在測試",
        mode=HealthcheckMode.QUICK,
        workspace="測試",
        action="assert_tab_exists",
        risk=RiskLevel.UI_ONLY,
        expected="市場觀察",
    )

    context = {"window": parent}
    res = assert_tab_exists(context, step)
    assert res["found"] is True
    assert res["tab_title"] == "市場觀察"

    # Tab not found
    step_fail = HealthcheckStep(
        id="test_tab",
        title="分頁存在測試",
        mode=HealthcheckMode.QUICK,
        workspace="測試",
        action="assert_tab_exists",
        risk=RiskLevel.UI_ONLY,
        expected="不存在的分頁",
    )
    with pytest.raises(AssertionError, match="找不到標題為 '不存在的分頁' 的分頁"):
        assert_tab_exists(context, step_fail)


def test_assert_text_contains():
    ensure_qapp()
    parent = QWidget()
    label = QLabel("整體品質：卓越", parent)

    step = HealthcheckStep(
        id="test_text",
        title="文字包含測試",
        mode=HealthcheckMode.QUICK,
        workspace="測試",
        action="assert_text_contains",
        risk=RiskLevel.UI_ONLY,
        expected="整體品質",
    )

    context = {"window": parent}
    res = assert_text_contains(context, step)
    assert res["contains"] is True

    # Failed match
    step_fail = HealthcheckStep(
        id="test_text",
        title="文字包含測試",
        mode=HealthcheckMode.QUICK,
        workspace="測試",
        action="assert_text_contains",
        risk=RiskLevel.UI_ONLY,
        expected="垃圾資料",
    )
    with pytest.raises(AssertionError, match="找不到包含文字 '垃圾資料' 的元件"):
        assert_text_contains(context, step_fail)


def test_assert_viewport_declared():
    step = HealthcheckStep(
        id="test_viewport",
        title="Viewport 測試",
        mode=HealthcheckMode.QUICK,
        workspace="測試",
        action="assert_viewport_declared",
        risk=RiskLevel.UI_ONLY,
    )

    # Valid format
    context = {"viewport": "1366x768"}
    res = assert_viewport_declared(context, step)
    assert res["width"] == 1366
    assert res["height"] == 768

    # Invalid format
    context_fail = {"viewport": "invalid_viewport"}
    with pytest.raises(AssertionError, match="宣告的 viewport 格式不合法"):
        assert_viewport_declared(context_fail, step)

    # Missing viewport
    context_missing = {}
    with pytest.raises(AssertionError, match="未宣告 viewport"):
        assert_viewport_declared(context_missing, step)


class FakeTabWidget:
    def __init__(self, labels):
        self.labels = list(labels)
        self.current_index = 0

    def count(self):
        return len(self.labels)

    def tabText(self, index):
        return self.labels[index]

    def setCurrentIndex(self, index):
        self.current_index = index


class FakeMainWindow:
    def __init__(self, labels):
        self.tab_widget = FakeTabWidget(labels)

    def windowTitle(self):
        return "baldr"


def test_collect_mainwindow_smoke_evidence():
    step = HealthcheckStep(
        id="mainwindow_smoke",
        title="主視窗 smoke",
        mode=HealthcheckMode.FULL,
        workspace="主視窗",
        action="collect_mainwindow_smoke_evidence",
        risk=RiskLevel.UI_ONLY,
    )
    context = {
        "window": FakeMainWindow(EXPECTED_MAINWINDOW_TAB_LABELS),
        "switch_mainwindow_tabs": True,
    }

    evidence = collect_mainwindow_smoke_evidence(context, step)

    assert evidence["window_title"] == "baldr"
    assert evidence["missing_tabs"] == []
    assert evidence["switched_tabs"] == list(EXPECTED_MAINWINDOW_TAB_LABELS)
    assert evidence["forbidden_actions_invoked"] == []


def test_run_existing_suites_for_mode():
    from unittest.mock import patch, MagicMock
    from scripts.run_full_app_healthcheck import run_existing_suites_for_mode

    context = {"mode": HealthcheckMode.QUICK}
    step = HealthcheckStep(
        id="test_step",
        title="test",
        mode=HealthcheckMode.QUICK,
        workspace="test",
        action="run_existing_suites_for_mode",
    )

    # Success case
    mock_completed = MagicMock()
    mock_completed.returncode = 0
    mock_completed.stdout = "some output"
    mock_completed.stderr = ""
    with patch("subprocess.run", return_value=mock_completed) as mock_run:
        res = run_existing_suites_for_mode(context, step)
        assert "suites" in res
        assert mock_run.call_count > 0

    # Failure case
    mock_failed = MagicMock()
    mock_failed.returncode = 1
    mock_failed.stdout = ""
    mock_failed.stderr = "some error"
    with patch("subprocess.run", return_value=mock_failed) as mock_run:
        with pytest.raises(AssertionError, match="既有測試失敗"):
            run_existing_suites_for_mode(context, step)
