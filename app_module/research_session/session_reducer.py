"""Pure reducer for research-session events."""

from dataclasses import replace

from .session_dtos import ResearchSessionSnapshotDTO
from .session_events import (
    ActiveProfileChanged,
    ActiveRegimeChanged,
    ActiveSymbolChanged,
    CurrentRecommendationRunChanged,
    ResearchSessionEvent,
    SelectedWatchlistChanged,
    StockResearchContextChanged,
)
from .session_dtos import ResearchStockContextDTO


def reduce_session_event(
    snapshot: ResearchSessionSnapshotDTO,
    event: ResearchSessionEvent,
) -> ResearchSessionSnapshotDTO:
    """Return a new snapshot for a session event."""

    if isinstance(event, ActiveSymbolChanged):
        return replace(snapshot, active_symbol=_normalize(event.symbol))
    if isinstance(event, ActiveRegimeChanged):
        return replace(snapshot, active_regime=_normalize(event.regime))
    if isinstance(event, ActiveProfileChanged):
        return replace(snapshot, active_profile=_normalize(event.profile))
    if isinstance(event, SelectedWatchlistChanged):
        return replace(snapshot, selected_watchlist_id=_normalize(event.watchlist_id))
    if isinstance(event, CurrentRecommendationRunChanged):
        return replace(snapshot, current_recommendation_run_id=_normalize(event.run_id))
    if isinstance(event, StockResearchContextChanged):
        supplied_context = event.context
        stock_code = _normalize(
            supplied_context.stock_code if supplied_context is not None else event.stock_code
        )
        if stock_code is None:
            return replace(
                snapshot,
                active_symbol=None,
                active_stock_code=None,
                stock_context=None,
                decision_date=None,
                data_date=None,
                result_id=None,
                profile_id=None,
                profile_version=None,
                source_id=None,
                source_kind=None,
                source_label=None,
                source_workspace=None,
                active_profile=None,
            )
        context = ResearchStockContextDTO(
            stock_code=stock_code,
            stock_name=_normalize(
                supplied_context.stock_name if supplied_context is not None else event.stock_name
            ) or "",
            decision_date=_normalize(
                supplied_context.decision_date if supplied_context is not None else event.decision_date
            ) or "",
            data_date=_normalize(
                supplied_context.data_date if supplied_context is not None else event.data_date
            ) or "",
            result_id=_normalize(
                supplied_context.result_id if supplied_context is not None else event.result_id
            ) or "",
            profile_id=_normalize(
                supplied_context.profile_id if supplied_context is not None else event.profile_id
            ) or "",
            profile_version=_normalize(
                supplied_context.profile_version if supplied_context is not None else event.profile_version
            ) or "",
            source_id=_normalize(
                supplied_context.source_id if supplied_context is not None else event.source_id
            ) or "",
            source_kind=_normalize(
                supplied_context.source_kind if supplied_context is not None else event.source_kind
            ) or "",
            source_label=_normalize(
                supplied_context.source_label if supplied_context is not None else event.source_label
            ) or "",
            source_workspace=_normalize(
                supplied_context.source_workspace if supplied_context is not None else event.source_workspace
            ) or "",
        )
        return replace(
            snapshot,
            active_symbol=stock_code,
            active_stock_code=stock_code,
            active_profile=context.profile_id or None,
            current_recommendation_run_id=context.result_id or None,
            stock_context=context,
            decision_date=context.decision_date or None,
            data_date=context.data_date or None,
            result_id=context.result_id or None,
            profile_id=context.profile_id or None,
            profile_version=context.profile_version or None,
            source_id=context.source_id or None,
            source_kind=context.source_kind or None,
            source_label=context.source_label or None,
            source_workspace=context.source_workspace or None,
        )

    return snapshot


def _normalize(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None
