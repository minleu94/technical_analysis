"""Daily update subprocess output 的純解析步驟。"""

import re
from typing import Any, Dict, Iterable


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def parse_daily_update_output(
    output: str, missing_dates: list[str]
) -> Dict[str, Any]:
    summary = re.search(
        r"\[UPDATE_SUMMARY\]\s*SUCCESS[：:]\s*(\d+)\s*days?[，,]\s*FAILED[：:]\s*(\d+)\s*days?",
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
    diagnostics: list[str] = []
    for line in output.splitlines():
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", line)
        if date_match is None:
            continue
        date = date_match.group(1)
        if "更新成功" in line or "✓" in line or ("成功" in line and "筆記錄" in line):
            updated.append(date)
        elif "已存在" in line or "⚠" in line or "跳過" in line:
            skipped.append(date)
            updated.append(date)
        elif "更新失敗" in line or "✗" in line or ("失敗" in line and "無法獲取" in line):
            failed.append(date)

    updated = _unique(updated)
    failed = _unique(failed)
    skipped = _unique(skipped)
    if not summary and not success_match and not fail_match and not updated and not failed:
        failed = list(missing_dates)
        diagnostics.append("batch_output_missing" if not output.strip() else "batch_output_unparseable")

    if summary:
        success_count, fail_count = map(int, summary.groups())
    elif success_match and fail_match:
        success_count = int(success_match.group(1))
        fail_count = int(fail_match.group(1))
    else:
        success_count, fail_count = len(updated), len(failed)

    if fail_count and not failed:
        failed = [f"失敗_{index + 1}" for index in range(fail_count)]
    if skipped:
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
        "skipped_dates": skipped,
    }
    if fail_count or diagnostics:
        result["diagnostic_codes"] = diagnostics
    return result
