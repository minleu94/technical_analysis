"""Inspect Scheduler Health & Observability Report Generator.

Read-only script to run SchedulerHealthService and generate JSON and Markdown reports.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Sequence, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_module.config import TWStockConfig
from data_module.scheduler_health_observability import SchedulerHealthService


DEFAULT_DATA_ROOT = Path(r"D:\Min\Python\Project\FA_Data")
DEFAULT_OUTPUT_ROOT = DEFAULT_DATA_ROOT / "output"


@dataclass(frozen=True)
class _ReadOnlyConfigView:
    """SchedulerHealthService 所需的最小、無副作用設定視圖。

    ``TWStockConfig`` 的建構子會建立資料夾並初始化 logging；健康檢查只
    需要兩個根目錄，因此不能為了唯讀稽核呼叫完整設定初始化。
    """

    data_root: Path
    output_root: Path


def _configured_root(env_name: str, fallback: Path) -> Path:
    """依現行 TWStockConfig 的環境覆寫規則解析路徑，不產生任何 I/O。"""

    return Path(os.environ.get(env_name, str(fallback))).expanduser()


def _resolve_roots(
    data_root: str | Path | None,
    output_root: str | Path | None,
) -> tuple[Path, Path]:
    """Resolve roots with the same data-root/output-root relationship as config."""

    resolved_data_root = (
        Path(data_root).expanduser()
        if data_root is not None
        else _configured_root("DATA_ROOT", DEFAULT_DATA_ROOT)
    )
    if output_root is not None:
        resolved_output_root = Path(output_root).expanduser()
    elif os.environ.get("OUTPUT_ROOT"):
        resolved_output_root = _configured_root("OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT)
    else:
        # Keep an explicit --data-root self-contained instead of silently
        # inspecting the default D: output tree.
        resolved_output_root = resolved_data_root / "output"
    return resolved_data_root, resolved_output_root


def run_scheduler_health_inspection(
    *,
    data_root: str | Path | None = None,
    output_root: str | Path | None = None,
    output: str | Path | None = None,
    markdown_output: str | Path | None = None,
) -> dict[str, object]:
    """稽核排程健康狀態，預設只讀並把報告回傳給 caller。

    ``TWStockConfig`` 初始化時會建立資料目錄並嘗試建立 ``config.log``，
    因此這個健康檢查的唯讀邊界使用只含必要欄位的 config view；只有 caller
    明確指定 ``output`` 或 ``markdown_output`` 時才會寫檔。
    """

    resolved_data_root, resolved_output_root = _resolve_roots(data_root, output_root)
    config = _ReadOnlyConfigView(
        data_root=resolved_data_root,
        output_root=resolved_output_root,
    )
    # SchedulerHealthService only accesses data_root/output_root. The explicit
    # cast keeps that structural, side-effect-free view visible to mypy while
    # retaining compatibility with the legacy TWStockConfig annotation.
    service = SchedulerHealthService(cast(TWStockConfig, config))
    report = service.audit_scheduler_health()

    data = report.to_dict()
    json_path = Path(output).expanduser() if output is not None else None
    md_path = Path(markdown_output).expanduser() if markdown_output is not None else None

    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    md_lines = [
        "# 排程與日常證據可觀測性健康報告 (Scheduler Health & Observability Report)",
        "",
        f"*報告生成時間: {report.audited_at}*",
        "",
        "> [!IMPORTANT]",
        "> 本報告為唯讀排程健康與可觀測性稽核報告，**不改動 Windows Task 或 Codex 自動化任務本身**。",
        "> **`production_scheduler_allowed=false` 為正式 DB Evidence 寫入限制，不代表禁止每日市場價格資料更新。**",
        "",
        "## 1. 排程整體健康總覽",
        f"- **整體健康狀態 (Overall Health)**: `{report.overall_health}`",
        f"- **正式排程寫入許可 (Production Scheduler Allowed)**: `{report.production_scheduler_allowed}`",
        f"- **執行順序相依性驗證 (Ordering Valid)**: `{report.ordering_valid}`",
        "",
        "## 2. 5 個邏輯排程單元狀態矩陣",
        "",
        "> Windows Task Scheduler 的完整註冊清冊另由 `scripts/inspect_scheduled_task_registration.py` 檢查；目前是 17 個每日 task 加 1 個 weekly task，共 18 個。此報告的 5 個單元是證據 read-model，不代表 Windows task 總數。",
        "| 順序 | 任務名稱 | 上次執行時間 | 狀態 | 寫入意圖 (Write Intent) | 狀態檔路徑 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for item in report.tasks:
        last_ts = item.last_run_timestamp or "無執行紀錄"
        md_lines.append(
            f"| #{item.expected_order_index+1} | `{item.task_name}` | `{last_ts}` | `{item.status}` | `{item.write_intent}` | `{item.status_json_path}` |"
        )

    md_lines.extend([
        "",
        "## 3. 建議事項與運作提示 (Advisory Notes)",
    ])
    for adv in report.advisory_notes:
        md_lines.append(f"- {adv}")

    if md_path is not None:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        with md_path.open("w", encoding="utf-8") as f:
            f.write("\n".join(md_lines) + "\n")

    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "唯讀稽核排程健康與證據狀態。預設只輸出 JSON，不建立任何檔案；"
            "需要保存報告時請明確指定輸出路徑。"
        )
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="明確指定 JSON 報告輸出路徑；省略時不寫檔。",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="明確指定 Markdown 報告輸出路徑；省略時不寫檔。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    data = run_scheduler_health_inspection(
        data_root=args.data_root,
        output_root=args.output_root,
        output=args.output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _configure_utf8_stdio() -> None:
    """讓 Windows 非 UTF-8 主控台也能安全顯示繁中 help/JSON。"""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
