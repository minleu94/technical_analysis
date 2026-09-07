"""In-memory research-session store."""

from typing import Callable, List, Optional

from .session_dtos import ResearchSessionSnapshotDTO, ResearchStockContextDTO
from .session_events import ResearchSessionEvent, StockResearchContextChanged
from .session_reducer import reduce_session_event

SessionSubscriber = Callable[[ResearchSessionSnapshotDTO], None]


class ResearchSessionStore:
    """Small UI-independent store for workflow continuity.

    The store owns only current session context. It does not persist state,
    hold DataFrames, run business logic, or know about Qt widgets.
    """

    def __init__(self, initial_snapshot: Optional[ResearchSessionSnapshotDTO] = None):
        self._snapshot = initial_snapshot or ResearchSessionSnapshotDTO()
        self._subscribers: List[SessionSubscriber] = []

    def get_snapshot(self) -> ResearchSessionSnapshotDTO:
        return self._snapshot

    def dispatch(self, event: ResearchSessionEvent) -> ResearchSessionSnapshotDTO:
        next_snapshot = reduce_session_event(self._snapshot, event)
        if next_snapshot == self._snapshot:
            return self._snapshot

        self._snapshot = next_snapshot
        self._notify(next_snapshot)
        return next_snapshot

    def set_stock_context(
        self,
        context: ResearchStockContextDTO | None,
        *,
        source: str = "ui",
    ) -> ResearchSessionSnapshotDTO:
        """設定目前單股研究上下文，供頁面路由共用。

        Store 只保存識別、日期與來源 metadata；呼叫端仍須自行提供已保存
        的 context，這個方法不會觸發分析、讀取行情或重算推薦。
        """

        if context is None:
            return self.dispatch(StockResearchContextChanged(None, source=source))
        if not isinstance(context, ResearchStockContextDTO):
            raise TypeError("context 必須是 ResearchStockContextDTO 或 None")
        return self.dispatch(
            StockResearchContextChanged(
                stock_code=context.stock_code,
                stock_name=context.stock_name,
                decision_date=context.decision_date,
                data_date=context.data_date,
                result_id=context.result_id,
                profile_id=context.profile_id,
                profile_version=context.profile_version,
                source_id=context.source_id,
                source_kind=context.source_kind,
                source_label=context.source_label,
                source_workspace=context.source_workspace,
                source=source,
            )
        )

    def clear_stock_context(self, *, source: str = "ui") -> ResearchSessionSnapshotDTO:
        """清除目前單股上下文，不觸碰任何持久化資料。"""

        return self.set_stock_context(None, source=source)

    def subscribe(self, subscriber: SessionSubscriber) -> Callable[[], None]:
        self._subscribers.append(subscriber)
        subscriber(self._snapshot)

        def unsubscribe() -> None:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)

        return unsubscribe

    def _notify(self, snapshot: ResearchSessionSnapshotDTO) -> None:
        for subscriber in list(self._subscribers):
            subscriber(snapshot)
