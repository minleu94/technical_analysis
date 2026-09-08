"""真 MainWindow 的 offscreen Qt 鍵盤／縮放回歸。

測試以子程序設定 Qt scale，避免同一 QApplication 生命週期無法更換
devicePixelRatio。這不是 Windows 前景互動或螢幕閱讀器測試。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_real_mainwindow_keyboard_and_long_table_at_150_and_200_percent(tmp_path: Path) -> None:
    script = Path("scripts/qa_validate_ui_scaling_keyboard.py").resolve()
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--output-dir",
            str(tmp_path),
            "--scale",
            "1.5",
            "--scale",
            "2.0",
        ],
        cwd=str(script.parents[1]),
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="backslashreplace",
        timeout=480,
        check=False,
    )
    assert completed.returncode == 0, (
        f"UI scaling runner failed: stdout={completed.stdout[-2000:]!r}, "
        f"stderr={completed.stderr[-2000:]!r}"
    )
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["evidence_kind"] == "offscreen_qtest"
    assert summary["native_windows_interaction"] == "unavailable_without_cua_trusted_rpc"
    assert summary["screenreader"] == "not_tested"
    assert [item["scale_factor_observed"] for item in summary["scales"]] == [1.5, 2.0]
    for item in summary["scales"]:
        assert item["status_projection"]["workspace_visible"] is True
        assert item["status_projection"]["status_label_visible"] is True
        assert item["long_table"]["row_count"] == 600
        assert item["long_table"]["after_page_down"] > item["long_table"]["initial_scroll"]
        assert item["long_table"]["after_home"] == 0
        assert all(step["focus_retained"] for step in item["keyboard_navigation"])
        assert all(Path(path).exists() for path in item["screenshots"])
        assert item["window_size_logical"] == {"width": 1366, "height": 768}
        assert item["device_pixel_ratio"] == item["scale_factor_observed"]
        pages = {page["page_key"]: page for page in item["embedded_pages"]}
        assert set(pages) == {"recommendation", "portfolio"}
        for page in pages.values():
            assert page["row_count"] == 600
            assert page["page_visible"] is True
            assert page["viewport_visible"] is True
            assert page["viewport_size_logical"]["width"] > 0
            assert page["viewport_size_logical"]["height"] > 0
            assert page["after_page_down"] > page["initial_scroll"]
            assert page["after_home"] == 0
            assert page["keyboard_focus_retained"] is True
            assert Path(page["screenshot"]).exists()
