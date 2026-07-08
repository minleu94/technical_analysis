import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui_qt.widgets.left_navigation import LeftNavigationWidget, NavigationItem


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication(sys.argv)
    return instance


def test_left_navigation_renders_main_workspace_order_and_badges():
    app()
    nav = LeftNavigationWidget(
        (
            NavigationItem("workbench", "決策工作台", icon="command", badge="3"),
            NavigationItem("market_explore", "市場探索", icon="radar"),
            NavigationItem("runtime", "Runtime", icon="pulse", badge="!"),
        )
    )

    assert nav.item_keys() == ["workbench", "market_explore", "runtime"]
    assert nav.button_for_key("workbench").text() == "決策工作台  3"
    assert nav.button_for_key("market_explore").text() == "市場探索"
    assert nav.button_for_key("runtime").text() == "Runtime  !"
    assert not nav.button_for_key("workbench").icon().isNull()
    assert not nav.button_for_key("market_explore").icon().isNull()
    assert not nav.button_for_key("runtime").icon().isNull()
    assert nav.label_for_key("workbench") == "決策工作台"


def test_left_navigation_emits_key_and_tracks_active_button():
    app()
    nav = LeftNavigationWidget(
        (
            NavigationItem("workbench", "決策工作台"),
            NavigationItem("market_explore", "市場探索"),
        )
    )
    selected: list[str] = []
    nav.workspaceSelected.connect(selected.append)

    nav.button_for_key("market_explore").click()

    assert selected == ["market_explore"]
    assert nav.current_key() == "market_explore"
    assert nav.button_for_key("market_explore").property("active") is True
    assert nav.button_for_key("workbench").property("active") is False


def test_left_navigation_collapses_to_icon_only_without_breaking_selection():
    app()
    nav = LeftNavigationWidget(
        (
            NavigationItem("workbench", "決策工作台", icon="command"),
            NavigationItem("market_explore", "市場探索", icon="radar"),
        )
    )
    selected: list[str] = []
    nav.workspaceSelected.connect(selected.append)

    nav.set_current_key("workbench")
    nav.set_collapsed(True)

    assert nav.is_collapsed() is True
    assert nav.maximumWidth() <= 64
    assert nav.button_for_key("workbench").text() == ""
    assert not nav.button_for_key("workbench").icon().isNull()
    assert "決策工作台" in nav.button_for_key("workbench").toolTip()
    assert nav.button_for_key("workbench").property("active") is True

    nav.button_for_key("market_explore").click()

    assert selected == ["market_explore"]
    assert nav.current_key() == "market_explore"
    assert nav.button_for_key("market_explore").property("active") is True


def test_left_navigation_clicking_active_workspace_toggles_collapse():
    app()
    nav = LeftNavigationWidget(
        (
            NavigationItem("workbench", "決策工作台", icon="command"),
            NavigationItem("market_explore", "市場探索", icon="radar"),
        )
    )
    selected: list[str] = []
    nav.workspaceSelected.connect(selected.append)

    nav.set_current_key("workbench")
    nav.button_for_key("workbench").click()

    assert selected == []
    assert nav.is_collapsed() is True
    assert nav.button_for_key("workbench").text() == ""

    nav.button_for_key("workbench").click()

    assert selected == []
    assert nav.is_collapsed() is False
    assert nav.button_for_key("workbench").text() == "決策工作台"
