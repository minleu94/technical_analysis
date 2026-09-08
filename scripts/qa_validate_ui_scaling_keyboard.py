"""在隔離輸出中驗證 PySide6 主視窗的縮放與鍵盤可操作性。

這個 runner 明確使用 ``offscreen`` 平台。它能驗證真實 MainWindow、Qt
鍵盤事件、狀態元件與長表格 model 的行為，但不宣稱 Windows 前景焦點、
實體顯示器縮放或螢幕閱讀器已驗證。
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


DEFAULT_SCALES = ("1.5", "2.0")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="隔離 offscreen PySide6 MainWindow 縮放／鍵盤 smoke runner"
    )
    parser.add_argument(
        "--scale",
        action="append",
        dest="scales",
        help="Qt scale factor；可重複指定，預設為 1.5 與 2.0",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path("output") / "qa" / "ui_scaling_keyboard"),
        help="隔離 evidence 輸出目錄",
    )
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args._child:
        scale = os.environ.get("QT_SCALE_FACTOR", "")
        evidence_path = output_dir / "evidence.json"
        try:
            evidence = _run_child(scale=scale, output_dir=output_dir)
            evidence_path.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"UI scaling keyboard evidence written: {evidence_path}")
            return 0
        except BaseException as exc:  # noqa: BLE001 - evidence must explain failure
            evidence_path.write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "evidence_kind": "offscreen_qtest",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"UI scaling keyboard smoke failed: {exc}", file=sys.stderr)
            return 1

    scales = tuple(args.scales or DEFAULT_SCALES)
    if not scales:
        raise ValueError("至少需要一個 --scale")
    results: list[dict[str, Any]] = []
    script_path = Path(__file__).resolve()
    for scale in scales:
        _validate_scale(scale)
        scale_dir = output_dir / f"scale_{scale.replace('.', '_')}"
        scale_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["QT_SCALE_FACTOR"] = scale
        env["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            [
                sys.executable,
                str(script_path),
                "--_child",
                "--output-dir",
                str(scale_dir),
            ],
            cwd=str(script_path.parents[1]),
            env=env,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="backslashreplace",
            timeout=240,
            check=False,
        )
        evidence_path = scale_dir / "evidence.json"
        if completed.returncode != 0 or not evidence_path.exists():
            raise RuntimeError(
                "offscreen UI child failed "
                f"scale={scale!r}, returncode={completed.returncode}, "
                f"stdout_tail={completed.stdout[-1200:]!r}, "
                f"stderr_tail={completed.stderr[-1200:]!r}"
            )
        result = json.loads(evidence_path.read_text(encoding="utf-8"))
        if result.get("status") != "passed":
            raise RuntimeError(f"offscreen UI child reported failure: {result}")
        results.append(result)

    summary = {
        "status": "passed",
        "evidence_kind": "offscreen_qtest",
        "native_windows_interaction": "unavailable_without_cua_trusted_rpc",
        "screenreader": "not_tested",
        "scales": results,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"UI scaling keyboard smoke passed: {summary_path}")
    return 0


def _validate_scale(value: str) -> None:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"scale 必須是正數：{value!r}") from exc
    if not math.isfinite(numeric) or numeric <= 0:
        raise ValueError(f"scale 必須是正數：{value!r}")


def _run_child(*, scale: str, output_dir: Path) -> dict[str, Any]:
    # 這些環境變數必須在 Qt／MainWindow import 前設定，且只指向本次隔離輸出。
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    _validate_scale(scale)
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    isolated_root = output_dir / "_isolated_app"
    os.environ["DATA_ROOT"] = str(isolated_root / "data")
    os.environ["OUTPUT_ROOT"] = str(isolated_root / "output")
    os.environ["PROFILE"] = "prod"

    import pandas as pd
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QTableView, QVBoxLayout, QWidget

    from ui_qt.main import MainWindow, apply_app_theme
    from ui_qt.models.pandas_table_model import PandasTableModel
    from ui_qt.widgets.table_style import apply_financial_table_style

    existing_app = QApplication.instance()
    app = existing_app if isinstance(existing_app, QApplication) else QApplication(sys.argv)
    apply_app_theme(app)
    window = MainWindow()
    window.resize(1366, 768)
    table_host = QWidget()
    table_layout = QVBoxLayout(table_host)
    table = QTableView(table_host)
    table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    frame = pd.DataFrame(
        {
            "證券代號": [f"{index:04d}" for index in range(600)],
            "狀態": ["observed" if index % 2 else "missing" for index in range(600)],
            "最新日期": ["2026-09-07"] * 600,
            "品質說明": ["保留原始 machine token" for _ in range(600)],
        }
    )
    model = PandasTableModel(frame)
    table.setModel(model)
    apply_financial_table_style(table)
    table.setCurrentIndex(model.index(0, 0))
    table_layout.addWidget(table)
    table_host.resize(900, 500)

    try:
        window.show()
        # MainWindow's first layout pass can grow to the largest child.  Pin
        # the logical viewport after showing so each page is measured at the
        # same reviewable desktop size.
        window.setFixedSize(1366, 768)
        table_host.show()
        window.activateWindow()
        window.raise_()
        app.processEvents()

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise AssertionError("offscreen Qt 沒有 primary screen")
        observed_scale = float(screen.devicePixelRatio())
        requested_scale = float(scale)
        if not math.isclose(observed_scale, requested_scale, rel_tol=0, abs_tol=0.01):
            raise AssertionError(
                f"Qt scale factor 不符：requested={requested_scale}, observed={observed_scale}"
            )

        navigation = window.left_navigation
        market_button = navigation.button_for_key("market_explore")
        runtime_button = navigation.button_for_key("runtime")
        if market_button is None or runtime_button is None:
            raise AssertionError("主要工作區鍵盤導覽按鈕不存在")

        keyboard_steps: list[dict[str, Any]] = []
        for key, button in (
            ("market_explore", market_button),
            ("runtime", runtime_button),
        ):
            button.activateWindow()
            button.setFocus(Qt.FocusReason.OtherFocusReason)
            if not button.hasFocus():
                raise AssertionError(f"無法把鍵盤焦點放到導覽按鈕：{key}")
            QTest.keyClick(button, Qt.Key.Key_Space)
            app.processEvents()
            if navigation.current_key() != key:
                raise AssertionError(
                    f"Space 未切換工作區：expected={key}, actual={navigation.current_key()}"
                )
            if window.workspace_stack.currentWidget() is not window.workspace_widgets[key]:
                raise AssertionError(f"工作區 stack 未切換：{key}")
            keyboard_steps.append(
                {
                    "key": key,
                    "activated_by": "Space",
                    "focus_retained": bool(button.hasFocus()),
                }
            )

        runtime_view = window.workspace_widgets["runtime"]
        status_label = getattr(runtime_view, "status_label", None)
        if status_label is None or not status_label.isVisible() or not status_label.text().strip():
            raise AssertionError("Runtime 狀態文字不可見或為空")
        status_evidence = {
            "workspace_visible": bool(runtime_view.isVisible()),
            "status_label_visible": bool(status_label.isVisible()),
            "status_text": str(status_label.text()),
        }

        table_host.activateWindow()
        table_host.raise_()
        QApplication.setActiveWindow(table_host)
        table.setFocus(Qt.FocusReason.OtherFocusReason)
        if not table.hasFocus():
            raise AssertionError("長表格無法取得鍵盤焦點")
        initial_scroll = int(table.verticalScrollBar().value())
        for _ in range(6):
            QTest.keyClick(table, Qt.Key.Key_PageDown)
        app.processEvents()
        after_page_down = int(table.verticalScrollBar().value())
        if after_page_down <= initial_scroll:
            raise AssertionError("PageDown 未推進長表格 viewport")
        bottom_row = table.indexAt(table.viewport().rect().bottomLeft()).row()
        QTest.keyClick(
            table,
            Qt.Key.Key_Home,
            Qt.KeyboardModifier.ControlModifier,
        )
        app.processEvents()
        after_home = int(table.verticalScrollBar().value())
        if after_home != 0:
            raise AssertionError("Home 未把長表格返回頂端")
        table_evidence = {
            "row_count": int(model.rowCount()),
            "column_count": int(model.columnCount()),
            "viewport_visible": bool(table.viewport().isVisible()),
            "vertical_scroll_maximum": int(table.verticalScrollBar().maximum()),
            "initial_scroll": initial_scroll,
            "after_page_down": after_page_down,
            "bottom_row_after_page_down": int(bottom_row),
            "after_home": after_home,
            "keyboard_focus_retained": bool(table.hasFocus()),
        }

        # Exercise the actual embedded recommendation and portfolio pages.
        # The models are isolated DTO projections; no source or portfolio data
        # is written.  This keeps the evidence about page geometry/focus and
        # table navigation instead of treating a detached QTableView as the
        # product page.
        embedded_pages = []
        page_frames = {
            "recommendation": (
                "results_table",
                pd.DataFrame(
                    {
                        "證券代號": [f"{index:04d}" for index in range(600)],
                        "推薦分數": [f"{80 - (index % 20) / 10:.1f}" for index in range(600)],
                        "資料日期": ["2026-09-07"] * 600,
                        "來源脈絡": ["isolated DTO projection"] * 600,
                    }
                ),
            ),
            "portfolio": (
                "positions_table",
                pd.DataFrame(
                    {
                        "證券代號": [f"{index:04d}" for index in range(600)],
                        "證券名稱": [f"隔離測試持倉 {index:04d}" for index in range(600)],
                        "持有股數": [1000 + index for index in range(600)],
                        "狀態監控": ["研究投影"] * 600,
                    }
                ),
            ),
        }
        for page_key, (table_name, page_frame) in page_frames.items():
            window._select_main_workspace(page_key)
            app.processEvents()
            page = window.workspace_widgets.get(page_key)
            if page is None:
                raise AssertionError(f"實際工作區不存在：{page_key}")
            cancel_refresh = getattr(page, "cancel_refresh", None)
            if callable(cancel_refresh):
                cancel_refresh()
                app.processEvents()
            page_table = getattr(page, table_name, None)
            if page_table is None:
                raise AssertionError(f"實際頁面缺少表格：{page_key}.{table_name}")
            page_model = PandasTableModel(page_frame)
            page_table.setModel(page_model)
            page_table.setCurrentIndex(page_model.index(0, 0))
            page_table.resizeColumnsToContents()
            app.processEvents()
            if window.workspace_stack.currentWidget() is not page:
                raise AssertionError(f"工作區未切換至實際頁面：{page_key}")
            QApplication.setActiveWindow(window)
            page_table.setFocus(Qt.FocusReason.OtherFocusReason)
            if not page_table.hasFocus():
                raise AssertionError(f"實際頁面表格無法取得焦點：{page_key}")
            page_initial_scroll = int(page_table.verticalScrollBar().value())
            for _ in range(6):
                QTest.keyClick(page_table, Qt.Key.Key_PageDown)
            app.processEvents()
            page_after_page_down = int(page_table.verticalScrollBar().value())
            if page_after_page_down <= page_initial_scroll:
                raise AssertionError(f"實際頁面 PageDown 未推進：{page_key}")
            page_bottom_row = page_table.indexAt(
                page_table.viewport().rect().bottomLeft()
            ).row()
            QTest.keyClick(
                page_table,
                Qt.Key.Key_Home,
                Qt.KeyboardModifier.ControlModifier,
            )
            app.processEvents()
            page_after_home = int(page_table.verticalScrollBar().value())
            if page_after_home != 0:
                raise AssertionError(f"實際頁面 Ctrl+Home 未回頂端：{page_key}")
            page_viewport = page_table.viewport().size()
            if page_viewport.width() <= 0 or page_viewport.height() <= 0:
                raise AssertionError(f"實際頁面 viewport 無有效尺寸：{page_key}")
            page_screenshot_path = output_dir / (
                f"{page_key}_page_scale_{scale.replace('.', '_')}.png"
            )
            page_pixmap = page.grab()
            if page_pixmap.isNull() or not page_pixmap.save(str(page_screenshot_path)):
                raise AssertionError(f"實際頁面 offscreen screenshot 保存失敗：{page_key}")
            embedded_pages.append(
                {
                    "page_key": page_key,
                    "table_name": table_name,
                    "row_count": int(page_model.rowCount()),
                    "column_count": int(page_model.columnCount()),
                    "page_visible": bool(page.isVisible()),
                    "viewport_visible": bool(page_table.viewport().isVisible()),
                    "viewport_size_logical": {
                        "width": int(page_viewport.width()),
                        "height": int(page_viewport.height()),
                    },
                    "window_size_logical": {
                        "width": int(window.size().width()),
                        "height": int(window.size().height()),
                    },
                    "device_pixel_ratio": float(page_table.devicePixelRatioF()),
                    "initial_scroll": page_initial_scroll,
                    "after_page_down": page_after_page_down,
                    "bottom_row_after_page_down": int(page_bottom_row),
                    "after_home": page_after_home,
                    "keyboard_focus_retained": bool(page_table.hasFocus()),
                    "screenshot": str(page_screenshot_path),
                }
            )

        screenshots: list[str] = []
        for label, widget in (("mainwindow", window), ("long_table", table_host)):
            screenshot_path = output_dir / f"{label}_scale_{scale.replace('.', '_')}.png"
            pixmap = widget.grab()
            if pixmap.isNull() or not pixmap.save(str(screenshot_path)):
                raise AssertionError(f"offscreen screenshot 保存失敗：{label}")
            screenshots.append(str(screenshot_path))

        return {
            "status": "passed",
            "evidence_kind": "offscreen_qtest",
            "native_windows_interaction": "not_observed",
            "screenreader": "not_tested",
            "scale_factor_requested": requested_scale,
            "scale_factor_observed": observed_scale,
            "window_size_logical": {
                "width": int(window.size().width()),
                "height": int(window.size().height()),
            },
            "device_pixel_ratio": float(window.devicePixelRatioF()),
            "keyboard_navigation": keyboard_steps,
            "status_projection": status_evidence,
            "long_table": table_evidence,
            "embedded_pages": embedded_pages,
            "screenshots": screenshots,
        }
    finally:
        table_host.close()
        window.close()
        app.processEvents()
        app.quit()


if __name__ == "__main__":
    raise SystemExit(main())
