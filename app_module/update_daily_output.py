"""Daily update subprocess output 的純解析步驟。"""

import json
import re
from typing import Any, Dict, Iterable


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def parse_daily_update_output(
    output: str, missing_dates: list[str]
) -> Dict[str, Any]:
    summary = re.search(
        r"\[UPDATE_SUMMARY\]\s*SUCCESS[：:]\s*(\d+)\s*days?"
        r"(?:[，,]\s*SKIPPED_NO_DATA[：:]\s*(\d+)\s*days?)?"
        r"[，,]\s*FAILED[：:]\s*(\d+)\s*days?",
        output,
    )
    success_match = re.search(r"成功[：:]\s*(\d+)\s*天", output) or re.search(
        r"成功\s+(\d+)\s*天", output
    )
    fail_match = re.search(r"失敗[：:]\s*(\d+)\s*天", output) or re.search(
        r"失敗\s+(\d+)\s*天", output
    )
    updated: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []
    no_data_skipped: list[str] = []
    diagnostics: list[str] = []
    source_diagnostics: list[dict[str, Any]] = []
    for line in output.splitlines():
        if line.startswith("UPDATE_DIAGNOSTIC "):
            try:
                source_diagnostics.append(json.loads(line.removeprefix("UPDATE_DIAGNOSTIC ")))
            except (json.JSONDecodeError, TypeError):
                diagnostics.append("source_diagnostic_unparseable")
            continue
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", line)
        if date_match is None:
            continue
        date = date_match.group(1)
        if "SKIPPED_NO_DATA" in line:
            no_data_skipped.append(date)
        elif "更新成功" in line or "✓" in line or ("成功" in line and "筆記錄" in line):
            updated.append(date)
        elif "已存在" in line or "⚠" in line or "跳過" in line:
            skipped.append(date)
            updated.append(date)
        elif "更新失敗" in line or "✗" in line or ("失敗" in line and "無法獲取" in line):
            failed.append(date)

    updated = _unique(updated)
    failed = _unique(failed)
    skipped = _unique(skipped)
    no_data_skipped = _unique(no_data_skipped)
    if not summary and not success_match and not fail_match and not updated and not failed:
        failed = list(missing_dates)
        diagnostics.append("batch_output_missing" if not output.strip() else "batch_output_unparseable")

    if summary:
        success_count = int(summary.group(1))
        fail_count = int(summary.group(3))
    elif success_match and fail_match:
        success_count = int(success_match.group(1))
        fail_count = int(fail_match.group(1))
    else:
        success_count, fail_count = len(updated), len(failed)

    if fail_count and not failed:
        resolved_dates = set(updated) | set(skipped) | set(no_data_skipped)
        unresolved_dates = [date for date in missing_dates if date not in resolved_dates]
        if len(unresolved_dates) == fail_count:
            failed = unresolved_dates
        else:
            diagnostics.append("failed_date_unresolved")

    if fail_count and not failed:
        failed = [f"失敗_{index + 1}" for index in range(fail_count)]
    if no_data_skipped:
        message_parts = [f"更新完成：成功 {success_count} 天"]
        message_parts.append(f"上游查無資料，已跳過 {len(no_data_skipped)} 天")
        if skipped:
            message_parts.append(f"其中 {len(skipped)} 天已存在並跳過")
        message_parts.append(f"失敗 {fail_count} 天")
        message = "，".join(message_parts)
    elif skipped:
        message = (
            f"更新完成：成功 {success_count} 天（其中 {len(skipped)} 天已存在並跳過），"
            f"失敗 {fail_count} 天"
        )
    else:
        message = f"更新完成：成功 {success_count} 天，失敗 {fail_count} 天"
    result: Dict[str, Any] = {
        "success": fail_count == 0,
        "message": message,
        "updated_dates": updated,
        "failed_dates": failed,
        "skipped_dates": _unique([*skipped, *no_data_skipped]),
        "no_data_skipped_dates": no_data_skipped,
        "source_diagnostics": source_diagnostics,
    }
    if fail_count or diagnostics:
        result["diagnostic_codes"] = diagnostics
    return result
