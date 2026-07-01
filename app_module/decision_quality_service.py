from __future__ import annotations

from collections import Counter
from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid5, NAMESPACE_URL

from app_module.decision_quality_dtos import (
    ITEM_IGNORED_PORTFOLIO_ALERT,
    ITEM_LARGE_LIVE_RESEARCH_GAP,
    ITEM_LOW_QUALITY_DATA_USED,
    ITEM_MANUAL_OVERRIDE_WITHOUT_EVIDENCE,
    ITEM_MISSED_HIGH_QUALITY_SIGNAL,
    ITEM_REGIME_PROFILE_MISMATCH,
    ITEM_TRADE_WITHOUT_SOURCE_TRACE,
    ITEM_UNREVIEWED_SIGNAL_DECAY,
    REVIEW_STATUS_INCOMPLETE,
    REVIEW_STATUS_NEEDS_REVIEW,
    REVIEW_STATUS_NO_DATA,
    REVIEW_STATUS_READY,
    DecisionQualityItem,
    DecisionQualityReview,
    DecisionQualitySaveResult,
)
from app_module.decision_quality_repository import DecisionQualityRepository
from app_module.evidence_event_dtos import EvidenceOutcomeStatus
from app_module.evidence_event_repository import EvidenceEventRepository
from app_module.journal_service import JournalService
from app_module.live_research_gap_repository import LiveResearchGapRepository
from app_module.portfolio_service import PortfolioService
from app_module.research_run_dtos import canonical_json
from app_module.signal_decay_dtos import SUGGESTION_DEMOTE_CANDIDATE, SUGGESTION_RETIRE_CANDIDATE
from app_module.signal_decay_repository import SignalDecayRepository
from data_module.config import TWStockConfig


SOURCE_TRACE_TYPES = {
    "recommendation",
    "recommendation_result",
    "research_run",
    "backtest_run",
    "strategy_version",
    "manual_thesis",
    "manual_override",
    "evidence_event",
}


class DecisionQualityService:
    """Read-only process review service over saved portfolio and evidence records."""

    def __init__(self, config: TWStockConfig, *, db_path: str | Path | None = None) -> None:
        self.config = config
        self.db_path = Path(db_path) if db_path is not None else Path(config.db_file)
        self.repository = DecisionQualityRepository(config, db_path=self.db_path)
        self.evidence_repository = EvidenceEventRepository(config, db_path=self.db_path)
        self.live_gap_repository = LiveResearchGapRepository(config, db_path=self.db_path)
        self.signal_decay_repository = SignalDecayRepository(config, db_path=self.db_path)
        self.portfolio_service = PortfolioService(config)
        self.journal_service = JournalService(config)

    def build_review(
        self,
        *,
        review_type: str,
        start_date: str,
        end_date: str,
        portfolio_id: str = "default",
        symbol: str | None = None,
        min_sample_size: int = 10,
    ) -> tuple[DecisionQualityReview, list[DecisionQualityItem]]:
        trades = [
            trade
            for trade in self.portfolio_service.list_trades(portfolio_id)
            if self._in_period(trade.trade_date, start_date, end_date) and self._matches_symbol(trade.stock_code, symbol)
        ]
        positions = [
            position
            for position in self.portfolio_service.list_positions(portfolio_id)
            if self._matches_symbol(position.stock_code, symbol)
        ]
        journals = [
            entry
            for entry in self.journal_service.list_journal_entries(portfolio_id=portfolio_id)
            if self._matches_symbol(entry.stock_code, symbol)
        ]
        events = [
            event
            for event in self.evidence_repository.list_events(start_date=start_date, end_date=end_date, symbol=symbol)
        ]
        live_gaps = [
            gap
            for gap in self.live_gap_repository.list_observations(symbol=symbol)
            if self._in_period(gap.observation_date, start_date, end_date)
        ]
        decay_rows = [
            row
            for row in self.signal_decay_repository.list_observations()
            if self._in_period(row.observation_date, start_date, end_date)
        ]
        review_id = self._review_id(review_type, start_date, end_date, portfolio_id, symbol)
        journal_links = {entry.linked_id for entry in journals if entry.linked_id}
        active_symbols = {position.stock_code for position in positions if position.is_holding}

        items: list[DecisionQualityItem] = []
        items.extend(self._trade_source_items(review_id, trades, journal_links))
        items.extend(self._portfolio_alert_items(review_id, events, active_symbols, journal_links))
        items.extend(self._live_gap_items(review_id, live_gaps, journal_links))
        items.extend(self._signal_decay_items(review_id, decay_rows, journal_links))
        items.extend(self._evidence_quality_items(review_id, events))
        items.extend(
            self._missed_signal_items(
                review_id,
                events,
                trades,
                journals,
                min_sample_size=max(1, int(min_sample_size)),
            )
        )
        items = self._deduplicate_items(items)

        mode_counts = Counter(str(gap.portfolio_mode or "unknown") for gap in live_gaps)
        if not mode_counts and positions:
            mode_counts["unknown"] = len(positions)
        item_counts = Counter(item.item_type for item in items)
        warnings: list[str] = []
        diagnostics: list[dict[str, Any]] = []
        if trades and not journals:
            warnings.append("journal_missing")
        if len(trades) + len(events) < int(min_sample_size):
            warnings.append("insufficient_review_sample")
            diagnostics.append({"code": "insufficient_review_sample", "severity": "warning"})
        if not trades and not events and not live_gaps and not decay_rows:
            warnings.append("no_review_source_data")
        if positions and not live_gaps:
            diagnostics.append({"code": "live_gap_data_missing", "severity": "info"})

        metrics = self._score_review(
            trades=trades,
            journals=journals,
            items=items,
            source_linked_count=sum(1 for trade in trades if self._has_source_trace(trade)),
            evidence_linked_count=sum(1 for trade in trades if self._has_evidence_link(trade)),
            manual_override_count=item_counts[ITEM_MANUAL_OVERRIDE_WITHOUT_EVIDENCE],
        )
        status = self._review_status(
            total_sources=len(trades) + len(events) + len(live_gaps) + len(decay_rows),
            item_count=len(items),
            warnings=warnings,
        )
        quality = "observed" if status == REVIEW_STATUS_READY else "degraded" if status != REVIEW_STATUS_NO_DATA else "missing"

        review_payload = {
            "review_type": review_type,
            "period": [start_date, end_date],
            "portfolio_id": portfolio_id,
            "symbol": symbol or "",
            "counts": dict(sorted(item_counts.items())),
            "warnings": sorted(set(warnings)),
        }
        review_hash = f"sha256:{hashlib.sha256(canonical_json(review_payload).encode('utf-8')).hexdigest()}"
        review = DecisionQualityReview(
            review_id=review_id,
            review_hash=review_hash,
            review_period_start=start_date,
            review_period_end=end_date,
            review_type=review_type,
            portfolio_mode_counts_json=dict(sorted(mode_counts.items())),
            evidence_event_count=len(events),
            trade_count=len(trades),
            journal_entry_count=len(journals),
            portfolio_alert_count=sum(1 for event in events if event.event_family == "portfolio"),
            ignored_alert_count=item_counts[ITEM_IGNORED_PORTFOLIO_ALERT],
            manual_override_count=item_counts[ITEM_MANUAL_OVERRIDE_WITHOUT_EVIDENCE],
            missed_high_quality_signal_count=item_counts[ITEM_MISSED_HIGH_QUALITY_SIGNAL],
            unreviewed_decay_candidate_count=item_counts[ITEM_UNREVIEWED_SIGNAL_DECAY],
            unlinked_trade_count=item_counts[ITEM_TRADE_WITHOUT_SOURCE_TRACE],
            decision_quality_score_bp=metrics["decision_quality_score_bp"],
            process_adherence_score_bp=metrics["process_adherence_score_bp"],
            evidence_usage_score_bp=metrics["evidence_usage_score_bp"],
            risk_discipline_score_bp=metrics["risk_discipline_score_bp"],
            review_completeness_score_bp=metrics["review_completeness_score_bp"],
            review_status=status,
            quality=quality,
            warnings_json=sorted(set(warnings)),
            diagnostics_json=diagnostics,
            metadata_json={
                "portfolio_id": portfolio_id,
                "symbol": symbol or "",
                "score_basis": "process_quality_bp",
                "review_scope": "evidence_and_journal_linkage_only",
            },
        )
        return review, [replace(item, review_id=review.review_id) for item in items]

    def save_review(
        self,
        review: DecisionQualityReview,
        *,
        items: list[DecisionQualityItem] | tuple[DecisionQualityItem, ...],
        confirm: bool = False,
    ) -> DecisionQualitySaveResult:
        if not confirm:
            return DecisionQualitySaveResult(review=review, saved=False, items_created=0)
        existing = self.repository.get_review_by_hash(review.review_hash)
        if existing is not None:
            return DecisionQualitySaveResult(review=existing, saved=True, skipped_duplicate=True, items_created=0)
        saved = self.repository.save_review(review, items=items)
        return DecisionQualitySaveResult(review=saved, saved=True, items_created=len(items))

    def list_reviews(self, **kwargs: Any) -> list[DecisionQualityReview]:
        return self.repository.list_reviews(**kwargs)

    def get_review(self, review_id: str) -> DecisionQualityReview | None:
        return self.repository.get_review(review_id)

    def summarize_reviews(self) -> Any:
        return self.repository.summarize_reviews()

    def mark_item_reviewed(self, item_id: str, *, reviewer: str = "", note: str = "") -> DecisionQualityItem:
        return self.repository.mark_item_reviewed(item_id, reviewer=reviewer, note=note)

    def mark_item_dismissed(
        self,
        item_id: str,
        *,
        reviewer: str = "",
        reason_code: str = "",
        note: str = "",
    ) -> DecisionQualityItem:
        return self.repository.mark_item_dismissed(
            item_id,
            reviewer=reviewer,
            reason_code=reason_code,
            note=note,
        )

    def create_action_item(self, **kwargs: Any) -> Any:
        return self.repository.create_action_item(**kwargs)

    def _trade_source_items(self, review_id: str, trades: list[Any], journal_links: set[str]) -> list[DecisionQualityItem]:
        items: list[DecisionQualityItem] = []
        for trade in trades:
            if not self._has_source_trace(trade):
                items.append(
                    self._item(
                        review_id,
                        ITEM_TRADE_WITHOUT_SOURCE_TRACE,
                        symbol=trade.stock_code,
                        decision_date=trade.trade_date,
                        source_type="portfolio_trade",
                        source_id=trade.trade_id,
                        related_trade_id=trade.trade_id,
                        reason_codes=["source_trace_missing"],
                        evidence={"trade_id": trade.trade_id, "source_type": trade.source_type},
                        question="這筆流程紀錄是否需要補上來源假設或研究連結？",
                    )
                )
            if self._is_manual_override(trade) and trade.trade_id not in journal_links and not self._has_evidence_link(trade):
                items.append(
                    self._item(
                        review_id,
                        ITEM_MANUAL_OVERRIDE_WITHOUT_EVIDENCE,
                        symbol=trade.stock_code,
                        decision_date=trade.trade_date,
                        source_type=trade.source_type or "manual_override",
                        source_id=trade.trade_id,
                        related_trade_id=trade.trade_id,
                        reason_codes=["manual_override_missing_review"],
                        evidence={"trade_id": trade.trade_id},
                        question="這次人工調整是否需要補上原因與 evidence 連結？",
                    )
                )
            summary = trade.source_summary if isinstance(trade.source_summary, dict) else {}
            if summary.get("regime_profile_mismatch") is True or summary.get("profile_regime_match") is False:
                items.append(
                    self._item(
                        review_id,
                        ITEM_REGIME_PROFILE_MISMATCH,
                        symbol=trade.stock_code,
                        decision_date=trade.trade_date,
                        source_type=trade.source_type,
                        source_id=trade.trade_id,
                        related_trade_id=trade.trade_id,
                        reason_codes=["regime_profile_mismatch"],
                        evidence={"trade_id": trade.trade_id},
                        question="當時使用的 profile 與 regime 假設是否需要補充覆盤？",
                    )
                )
        return items

    def _portfolio_alert_items(
        self,
        review_id: str,
        events: list[Any],
        active_symbols: set[str],
        journal_links: set[str],
    ) -> list[DecisionQualityItem]:
        items: list[DecisionQualityItem] = []
        for event in events:
            if event.event_family != "portfolio":
                continue
            if not event.symbol or event.symbol not in active_symbols or event.event_id in journal_links:
                continue
            severity = "high" if "invalid" in event.event_type.value or "chip" in event.event_type.value else "medium"
            items.append(
                self._item(
                    review_id,
                    ITEM_IGNORED_PORTFOLIO_ALERT,
                    symbol=event.symbol,
                    event_date=event.event_date,
                    decision_date=event.decision_date,
                    source_type=event.source_type,
                    source_id=event.source_id,
                    related_evidence_event_id=event.event_id,
                    severity=severity,
                    reason_codes=["portfolio_alert_unreviewed"],
                    evidence={"event_type": event.event_type.value},
                    question="是否已確認原始 thesis 仍成立？",
                )
            )
        return items

    def _live_gap_items(self, review_id: str, live_gaps: list[Any], journal_links: set[str]) -> list[DecisionQualityItem]:
        items: list[DecisionQualityItem] = []
        for gap in live_gaps:
            value = gap.gap_vs_forward_evidence_bp
            if value is None or abs(int(value)) < 1000 or gap.gap_id in journal_links:
                continue
            items.append(
                self._item(
                    review_id,
                    ITEM_LARGE_LIVE_RESEARCH_GAP,
                    symbol=gap.symbol,
                    event_date=gap.observation_date,
                    decision_date=gap.observation_date,
                    source_type=gap.source_type,
                    source_id=gap.source_id,
                    related_position_id=gap.position_id,
                    related_evidence_event_id=gap.evidence_event_id,
                    related_gap_id=gap.gap_id,
                    severity="medium",
                    reason_codes=["large_gap_unreviewed"],
                    evidence={"gap_vs_forward_evidence_bp": value, "portfolio_mode": gap.portfolio_mode},
                    question="這個 research gap 是否需要記錄 execution、資料品質或情境差異？",
                )
            )
        return items

    def _signal_decay_items(self, review_id: str, decay_rows: list[Any], journal_links: set[str]) -> list[DecisionQualityItem]:
        items: list[DecisionQualityItem] = []
        for row in decay_rows:
            if row.suggested_lifecycle_action not in {SUGGESTION_DEMOTE_CANDIDATE, SUGGESTION_RETIRE_CANDIDATE}:
                continue
            if row.decay_id in journal_links:
                continue
            items.append(
                self._item(
                    review_id,
                    ITEM_UNREVIEWED_SIGNAL_DECAY,
                    symbol="",
                    event_date=row.observation_date,
                    decision_date=row.observation_date,
                    source_type=row.signal_scope_type,
                    source_id=row.signal_scope_id,
                    related_decay_id=row.decay_id,
                    severity="medium",
                    reason_codes=["signal_decay_unreviewed"],
                    evidence={
                        "decay_status": row.decay_status,
                        "suggested_lifecycle_action": row.suggested_lifecycle_action,
                    },
                    question="這個 signal decay candidate 是否需要進入人工 lifecycle review？",
                )
            )
        return items

    def _evidence_quality_items(self, review_id: str, events: list[Any]) -> list[DecisionQualityItem]:
        items: list[DecisionQualityItem] = []
        for event in events:
            if event.data_quality.value not in {"degraded", "missing"} and not event.warnings:
                continue
            items.append(
                self._item(
                    review_id,
                    ITEM_LOW_QUALITY_DATA_USED,
                    symbol=event.symbol or "",
                    event_date=event.event_date,
                    decision_date=event.decision_date,
                    source_type=event.source_type,
                    source_id=event.source_id,
                    related_evidence_event_id=event.event_id,
                    severity="low",
                    reason_codes=["data_quality_review"],
                    evidence={"data_quality": event.data_quality.value, "warnings": list(event.warnings)},
                    question="這筆 evidence 的資料品質限制是否已在覆盤中被標註？",
                )
            )
        return items

    def _missed_signal_items(
        self,
        review_id: str,
        events: list[Any],
        trades: list[Any],
        journals: list[Any],
        *,
        min_sample_size: int,
    ) -> list[DecisionQualityItem]:
        trade_symbols = {trade.stock_code for trade in trades}
        journal_symbols = {entry.stock_code for entry in journals if entry.stock_code}
        outcomes = self.evidence_repository.list_outcomes(window_days=20)
        event_by_id = {event.event_id: event for event in events}
        ready_rows = [
            (event_by_id[outcome.event_id], outcome)
            for outcome in outcomes
            if outcome.event_id in event_by_id
            and outcome.outcome_status == EvidenceOutcomeStatus.READY
            and outcome.benchmark_excess_bp is not None
        ]
        if len(ready_rows) < min_sample_size:
            return []
        strong_rows = [
            (event, outcome)
            for event, outcome in ready_rows
            if int(outcome.benchmark_excess_bp or 0) >= 500
            and event.symbol
            and event.symbol not in trade_symbols
            and event.symbol not in journal_symbols
        ]
        if not strong_rows:
            return []
        event, outcome = sorted(strong_rows, key=lambda row: row[0].event_id)[0]
        return [
            self._item(
                review_id,
                ITEM_MISSED_HIGH_QUALITY_SIGNAL,
                symbol=event.symbol or "",
                event_date=event.event_date,
                decision_date=event.decision_date,
                source_type=event.source_type,
                source_id=event.source_id,
                related_evidence_event_id=event.event_id,
                severity="low",
                reason_codes=["process_review", "sufficient_forward_evidence"],
                evidence={
                    "event_type": event.event_type.value,
                    "sample_size": len(ready_rows),
                    "benchmark_excess_bp": outcome.benchmark_excess_bp,
                },
                question="是否需要檢查研究流程是否漏掉這類 evidence bucket？",
            )
        ]

    def _score_review(
        self,
        *,
        trades: list[Any],
        journals: list[Any],
        items: list[DecisionQualityItem],
        source_linked_count: int,
        evidence_linked_count: int,
        manual_override_count: int,
    ) -> dict[str, int]:
        item_counts = Counter(item.item_type for item in items)
        trade_count = len(trades)
        process_parts = [
            self._ratio_bp(source_linked_count, trade_count),
            self._ratio_bp(len(journals), trade_count),
            self._reviewed_ratio(items, {ITEM_IGNORED_PORTFOLIO_ALERT}),
            self._reviewed_ratio(items, {ITEM_UNREVIEWED_SIGNAL_DECAY}),
        ]
        evidence_parts = [
            self._ratio_bp(source_linked_count, trade_count),
            self._ratio_bp(evidence_linked_count, trade_count),
            self._ratio_bp(evidence_linked_count, trade_count),
            10000 if manual_override_count == 0 else 0,
        ]
        risk_total = (
            item_counts[ITEM_IGNORED_PORTFOLIO_ALERT]
            + item_counts[ITEM_LARGE_LIVE_RESEARCH_GAP]
            + item_counts[ITEM_LOW_QUALITY_DATA_USED]
        )
        risk_score = 10000 if risk_total == 0 else max(0, 10000 - min(10000, risk_total * 2500))
        review_completeness = self._reviewed_ratio(items, {item.item_type for item in items})
        process = self._mean_bp(process_parts)
        evidence = self._mean_bp(evidence_parts)
        completeness = review_completeness
        score = (35 * process + 30 * evidence + 20 * risk_score + 15 * completeness) // 100
        return {
            "process_adherence_score_bp": process,
            "evidence_usage_score_bp": evidence,
            "risk_discipline_score_bp": risk_score,
            "review_completeness_score_bp": completeness,
            "decision_quality_score_bp": score,
        }

    def _item(
        self,
        review_id: str,
        item_type: str,
        *,
        symbol: str = "",
        event_date: str = "",
        decision_date: str = "",
        source_type: str = "",
        source_id: str = "",
        related_trade_id: str = "",
        related_position_id: str = "",
        related_evidence_event_id: str = "",
        related_gap_id: str = "",
        related_decay_id: str = "",
        severity: str = "medium",
        reason_codes: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
        question: str,
    ) -> DecisionQualityItem:
        payload = {
            "review_id": review_id,
            "item_type": item_type,
            "symbol": symbol,
            "event_date": event_date,
            "decision_date": decision_date,
            "source_type": source_type,
            "source_id": source_id,
            "related_trade_id": related_trade_id,
            "related_position_id": related_position_id,
            "related_evidence_event_id": related_evidence_event_id,
            "related_gap_id": related_gap_id,
            "related_decay_id": related_decay_id,
            "reason_codes": reason_codes or [],
        }
        item_id = f"dqi_{uuid5(NAMESPACE_URL, canonical_json(payload)).hex}"
        return DecisionQualityItem(
            item_id=item_id,
            review_id=review_id,
            item_type=item_type,
            symbol=symbol,
            event_date=event_date,
            decision_date=decision_date,
            source_type=source_type,
            source_id=source_id,
            related_trade_id=related_trade_id,
            related_position_id=related_position_id,
            related_evidence_event_id=related_evidence_event_id,
            related_gap_id=related_gap_id,
            related_decay_id=related_decay_id,
            severity=severity,
            reason_codes_json=reason_codes or [],
            evidence_json=evidence or {},
            suggested_review_question=question,
        )

    @staticmethod
    def _review_id(review_type: str, start_date: str, end_date: str, portfolio_id: str, symbol: str | None) -> str:
        payload = canonical_json(
            {
                "review_type": review_type,
                "start": start_date,
                "end": end_date,
                "portfolio_id": portfolio_id,
                "symbol": symbol or "",
            }
        )
        return f"dqr_{uuid5(NAMESPACE_URL, payload).hex}"

    @staticmethod
    def _has_source_trace(trade: Any) -> bool:
        summary = trade.source_summary if isinstance(trade.source_summary, dict) else {}
        return bool(
            (trade.source_type in SOURCE_TRACE_TYPES and (trade.source_id or trade.source_type == "manual_override"))
            or summary.get("research_run_id")
            or summary.get("strategy_version_id")
            or summary.get("evidence_event_id")
            or summary.get("manual_thesis")
        )

    @staticmethod
    def _has_evidence_link(trade: Any) -> bool:
        summary = trade.source_summary if isinstance(trade.source_summary, dict) else {}
        return bool(summary.get("evidence_event_id") or summary.get("evidence_outcome_id"))

    @staticmethod
    def _is_manual_override(trade: Any) -> bool:
        summary = trade.source_summary if isinstance(trade.source_summary, dict) else {}
        return trade.source_type == "manual_override" or summary.get("override") is True

    @staticmethod
    def _in_period(value: str, start_date: str, end_date: str) -> bool:
        if not value:
            return False
        date_value = str(value)[:10]
        return start_date <= date_value <= end_date

    @staticmethod
    def _matches_symbol(actual: str | None, symbol: str | None) -> bool:
        return symbol is None or str(actual or "") == symbol

    @staticmethod
    def _ratio_bp(numerator: int, denominator: int) -> int:
        if denominator <= 0:
            return 10000
        return max(0, min(10000, numerator * 10000 // denominator))

    @staticmethod
    def _mean_bp(values: list[int]) -> int:
        return sum(values) // len(values) if values else 0

    @staticmethod
    def _reviewed_ratio(items: list[DecisionQualityItem], item_types: set[str]) -> int:
        selected = [item for item in items if item.item_type in item_types]
        if not selected:
            return 10000
        done = sum(1 for item in selected if item.status in {"reviewed", "dismissed", "action_planned"})
        return done * 10000 // len(selected)

    @staticmethod
    def _review_status(*, total_sources: int, item_count: int, warnings: list[str]) -> str:
        if total_sources == 0:
            return REVIEW_STATUS_NO_DATA
        if "insufficient_review_sample" in warnings:
            return REVIEW_STATUS_INCOMPLETE
        if item_count:
            return REVIEW_STATUS_NEEDS_REVIEW
        return REVIEW_STATUS_READY

    @staticmethod
    def _deduplicate_items(items: list[DecisionQualityItem]) -> list[DecisionQualityItem]:
        result: dict[str, DecisionQualityItem] = {}
        for item in items:
            result.setdefault(item.item_id, item)
        return list(result.values())
