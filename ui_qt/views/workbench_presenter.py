"""Unified Decision Workbench 的純 DTO 呈現規則。"""

from __future__ import annotations

from collections.abc import Collection
from typing import Protocol, Sequence


class ReviewItemLike(Protocol):
    item_id: object


class DashboardReviewQueueLike(Protocol):
    review_items: Sequence[ReviewItemLike]


def review_queue_state_text(
    dashboard: DashboardReviewQueueLike | None,
    viewed_review_item_ids: Collection[str],
) -> str:
    if dashboard is None:
        return "今日待判讀佇列尚未載入；等待 WorkbenchDashboardDTO。"
    count = len(dashboard.review_items)
    if count == 0:
        return (
            "今日待判讀佇列為空；這只代表目前 DTO 沒有待判讀項目，"
            "不代表 Phase gate 已完成，也不是買賣建議。"
        )
    active_ids = {str(item.item_id) for item in dashboard.review_items}
    viewed_count = len(set(viewed_review_item_ids) & active_ids)
    return (
        f"今日待判讀 {count} 筆；已查看 {viewed_count}/{count}。"
        "已查看只存在本次 UI session，不寫 DB、不標記完成。"
    )


def _is_degraded_status(status: object) -> bool:
    return str(status) in {
        "critical",
        "warning",
        "degraded",
        "missing",
        "blocked",
        "action_required",
        "waiting_for_time",
        "source_missing",
        "invalid_evidence",
        "machine_candidate",
        "machine_degraded",
        "stale",
        "unknown",
    }


def _has_degraded_reason(reason: object) -> bool:
    text = str(reason).strip()
    return bool(text and text != "none")


def evidence_feed_state_text(dashboard) -> str:
    count = len(dashboard.background_evidence_feed)
    if count == 0:
        return (
            "目前沒有背景證據列；這只代表 WorkbenchDashboardDTO payload 為空。"
            "Workbench 不讀 DB、不執行 replay、不補資料，也不代表 gate 已通過。"
        )
    degraded = any(
        _is_degraded_status(item.status) or _has_degraded_reason(item.degraded_reason)
        for item in dashboard.background_evidence_feed
    )
    human_count = sum(
        1
        for item in dashboard.background_evidence_feed
        if str(getattr(item, "status_classification", "human_review")).strip()
        == "human_review"
    )
    if degraded and human_count:
        return (
            f"背景證據流降級：{count} 筆來源中包含 missing / degraded / warning。"
            "請依來源追蹤與診斷訊號人工檢查；Workbench 不補值、不重跑 pipeline、不讀 replay DB。"
        )
    if degraded:
        return (
            f"背景證據流含 {count} 筆機器狀態：來源缺件、自然等待或降級。"
            "請依來源追蹤與診斷訊號等待或修復來源；不需人工簽核，Workbench 不補值、不重跑 pipeline、不讀 replay DB。"
        )
    return (
        f"背景證據流已載入 {count} 筆唯讀來源。"
        "這是既有 DTO / service payload 的彙整，不是交易建議。"
    )


def action_item_state_text(dashboard) -> str:
    count = len(dashboard.action_items)
    human_count = sum(
        1
        for item in dashboard.action_items
        if str(getattr(item, "status_classification", "human_review")).strip()
        == "human_review"
    )
    machine_count = count - human_count
    if count == 0:
        return (
            "目前沒有人工待處理事項；這不代表可以交易或 Phase gate 已通過。"
            "Workbench 不寫 DB、不標記完成、不套用 lifecycle，也不是買賣建議。"
        )
    degraded = any(
        _is_degraded_status(item.severity) or _has_degraded_reason(item.degraded_reason)
        for item in dashboard.action_items
    )
    if degraded:
        if human_count:
            handling = f"人工待處理 {human_count} 筆；機器狀態 {machine_count} 筆，不需人工簽核。"
        else:
            handling = f"人工待處理 0 筆；機器狀態 {machine_count} 筆，不需人工簽核。"
        return (
            f"Action Items 降級：{handling}佇列包含資料缺口、警示或等待真實時間累積項目。"
            "只有明確 human_review 項目只供人工覆盤排序；機器狀態不需人工簽核；"
            "不是買賣建議；Workbench 不寫 DB、不套用 lifecycle。"
        )
    return (
        f"Action Items 已載入 {human_count} 筆人工待處理事項；機器狀態 {machine_count} 筆。"
        "只有明確 human_review 項目供人工檢查 source trace，不會自動建立 repository 或寫入狀態。"
    )


def operating_loop_state_text(dashboard) -> str:
    count = len(dashboard.operating_loop_steps)
    if count == 0:
        return (
            "尚未有操作節奏 payload；等待 WorkbenchDashboardDTO。"
            "Workbench 維持唯讀，不寫 DB、不標記完成、不啟用排程器。"
        )
    manual_count = sum(
        1
        for item in dashboard.operating_loop_steps
        if str(item.status) in {"manual_required", "warning", "action_required"}
    )
    waiting_count = sum(
        1 for item in dashboard.operating_loop_steps if str(item.status) == "waiting_for_time"
    )
    return (
        f"操作節奏已載入 {count} 步：今天要看、人工處理與等待真實時間累積已串接；"
        f"人工處理 {manual_count} 步，等待真實時間累積 {waiting_count} 步。"
        "Workbench 只讀，不寫 DB、不標記完成、不套用 lifecycle。"
    )
