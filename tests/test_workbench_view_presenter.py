from types import SimpleNamespace

from ui_qt.views.workbench_presenter import (
    action_item_state_text,
    evidence_feed_state_text,
    operating_loop_state_text,
    review_queue_state_text,
)


def test_review_queue_state_text_preserves_pending_and_session_viewed_contract() -> None:
    dashboard = SimpleNamespace(
        review_items=[SimpleNamespace(item_id="a"), SimpleNamespace(item_id="b")]
    )

    assert review_queue_state_text(None, set()) == (
        "今日待判讀佇列尚未載入；等待 WorkbenchDashboardDTO。"
    )
    assert review_queue_state_text(dashboard, {"a", "stale"}) == (
        "今日待判讀 2 筆；已查看 1/2。"
        "已查看只存在本次 UI session，不寫 DB、不標記完成。"
    )


def test_review_queue_state_text_does_not_treat_empty_queue_as_gate_completion() -> None:
    dashboard = SimpleNamespace(review_items=[])

    assert "不代表 Phase gate 已完成" in review_queue_state_text(dashboard, set())


def test_section_state_presenters_distinguish_empty_degraded_and_ready() -> None:
    empty = SimpleNamespace(
        background_evidence_feed=[], action_items=[], operating_loop_steps=[]
    )
    degraded = SimpleNamespace(
        background_evidence_feed=[SimpleNamespace(status="missing", degraded_reason="gap")],
        action_items=[SimpleNamespace(severity="warning", degraded_reason="gap")],
        operating_loop_steps=[SimpleNamespace(status="manual_required")],
    )
    ready = SimpleNamespace(
        background_evidence_feed=[SimpleNamespace(status="ready", degraded_reason="none")],
        action_items=[SimpleNamespace(severity="ready", degraded_reason="none")],
        operating_loop_steps=[SimpleNamespace(status="done")],
    )

    assert "payload 為空" in evidence_feed_state_text(empty)
    assert "Action Items 降級" in action_item_state_text(degraded)
    assert "人工處理 1 步" in operating_loop_state_text(degraded)
    assert "已載入 1 筆唯讀來源" in evidence_feed_state_text(ready)
    assert "已載入 1 筆人工待處理事項" in action_item_state_text(ready)
