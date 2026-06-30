from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EXPECTED_MAINWINDOW_TAB_LABELS = (
    "數據更新",
    "市場觀察",
    "每日決策",
    "策略回測",
    "推薦分析",
    "觀察清單",
    "持倉管理",
    "Runtime Observatory",
)


@dataclass(frozen=True)
class ViewportSize:
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.width}x{self.height}"


def parse_viewport_spec(spec: str) -> ViewportSize:
    try:
        width_text, height_text = spec.lower().split("x", 1)
        width = int(width_text)
        height = int(height_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid viewport spec: {spec!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid viewport spec: {spec!r}")
    return ViewportSize(width=width, height=height)


def build_mainwindow_smoke_evidence(
    *,
    window_title: str,
    tab_labels: list[str],
    missing_tabs: list[str],
    switched_tabs: list[str],
    screenshots: list[dict[str, Any]] | None = None,
    resize_evidence: list[dict[str, Any]] | None = None,
    dialog_cancel_evidence: list[dict[str, Any]] | None = None,
    forbidden_actions_invoked: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "window_title": window_title,
        "tab_labels": tab_labels,
        "expected_tabs": list(EXPECTED_MAINWINDOW_TAB_LABELS),
        "missing_tabs": missing_tabs,
        "switched_tabs": switched_tabs,
        "screenshots": list(screenshots or []),
        "resize_evidence": list(resize_evidence or []),
        "dialog_cancel_evidence": list(dialog_cancel_evidence or []),
        "forbidden_actions_invoked": list(forbidden_actions_invoked or []),
    }


def collect_mainwindow_smoke_evidence(
    window: Any,
    *,
    switch_tabs: bool = False,
) -> dict[str, Any]:
    """收集主視窗唯讀 smoke evidence；呼叫端負責提供已建立的 window。"""
    tab_widget = _find_primary_tab_widget(window)
    tab_labels = [str(tab_widget.tabText(index)) for index in range(tab_widget.count())]
    missing_tabs = [label for label in EXPECTED_MAINWINDOW_TAB_LABELS if label not in tab_labels]

    switched_tabs: list[str] = []
    if switch_tabs:
        for label in EXPECTED_MAINWINDOW_TAB_LABELS:
            if label not in tab_labels:
                continue
            index = tab_labels.index(label)
            tab_widget.setCurrentIndex(index)
            switched_tabs.append(label)

    return build_mainwindow_smoke_evidence(
        window_title=_window_title(window),
        tab_labels=tab_labels,
        missing_tabs=missing_tabs,
        switched_tabs=switched_tabs,
        forbidden_actions_invoked=[],
    )


def _window_title(window: Any) -> str:
    title = getattr(window, "windowTitle", None)
    if callable(title):
        return str(title())
    return ""


def _find_primary_tab_widget(window: Any) -> Any:
    direct_tab_widget = getattr(window, "tab_widget", None)
    if direct_tab_widget is not None:
        return direct_tab_widget

    find_children = getattr(window, "findChildren", None)
    if callable(find_children):
        for candidate in find_children(object):
            if _looks_like_tab_widget(candidate):
                return candidate

    raise AssertionError("找不到主視窗分頁容器")


def _looks_like_tab_widget(candidate: Any) -> bool:
    return all(
        callable(getattr(candidate, method_name, None))
        for method_name in ("count", "tabText", "setCurrentIndex")
    )
