"""Inspect Scheduler Health & Observability Report Generator.

Read-only script to run SchedulerHealthService and generate JSON and Markdown reports.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_module.config import TWStockConfig
from data_module.scheduler_health_observability import SchedulerHealthService


def run_scheduler_health_inspection() -> None:
    config = TWStockConfig()
    service = SchedulerHealthService(config)
    report = service.audit_scheduler_health()

    json_path = Path("qa/reports/scheduler_health_report.json")
    md_path = Path("docs/06_qa/SCHEDULER_HEALTH_OBSERVABILITY_REPORT.md")

    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    data = report.to_dict()

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
        "## 2. 5 大排程任務單元狀態矩陣",
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

    with md_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    print(f"Scheduler health report generated to {json_path} and {md_path}")


if __name__ == "__main__":
    run_scheduler_health_inspection()
