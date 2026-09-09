"""T+1 next-session-open research Paper execution candidate producer。

這條路徑只消費已存在的觀測：前一自然日凍結的 recommendation JSON、唯讀
``paper_portfolio`` snapshot、append-only Paper fill ledger（若已存在）以及
官方 ``daily_prices`` row。它將 recommendation 轉成明確的 Paper target，
在下一個已由官方證據證明的交易 session open 依 target 與持倉差額建立
Decimal 成交事件，並保留成本、成交量限制、來源 hash、讀取交易與自然日
時間界線。

預設只產生新的 TEMP candidate。受控排程可另提供明確的
``controlled_output_root``，將每輪 candidate 保存到該 root 的新直接子目錄；
只有呼叫端明確要求並提供 ``confirm_append=True`` 時，才會使用既有
``PaperTradeLedgerRepository`` 寫入指定的 append-only ledger。此 writer 仍固定
research-only、不可 broker、不可 auto rebalance。這裡不更新 snapshot、不寫正式
行情／Formal DB、不推導歷史成交，也不啟動交易或訓練；snapshot 只在下一個
自然日的 mark-to-market 流程中以已驗證 ledger transition 投影，不回寫既有
snapshot。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
from zoneinfo import ZoneInfo

from app_module.execution_slippage_model import TaiwanStockTickSlippageModel
from app_module.paper_portfolio_policy import PaperPortfolioAction
from app_module.paper_portfolio_policy_adapter import (
    PaperPolicyCandidate,
    PaperPortfolioPolicyAdapter,
    PaperPortfolioPolicyBatchResult,
    PaperPortfolioPolicyContext,
    PaperPortfolioPolicyAdapterResult,
)
from app_module.paper_portfolio_policy import PaperPortfolioPolicyConfig
from app_module.paper_trade_ledger import (
    PaperTradeFill,
    PaperTradeLedgerRepository,
)
from app_module.portfolio_construction_dtos import (
    PortfolioConstructionCandidate,
    PortfolioConstructionRequest,
)
from app_module.portfolio_construction_service import PortfolioConstructionService
from data_module.official_trading_calendar import OfficialTradingCalendar
from financial_module.units import calculate_fee, quantize_money


TAIPEI = ZoneInfo("Asia/Taipei")
MONEY_QUANTUM = Decimal("0.01")
BPS_DENOMINATOR = Decimal("10000")
TAIWAN_MARKET_OPEN = time(9, 0)
# 本地 daily_prices 沒有逐列 capture timestamp；以交易日收盤後的保守固定時刻
# 作為 delayed EOD replay 的最低可得門檻，避免 09:00 開盤候選回看全天檔案。
TAIWAN_EOD_REPLAY_AVAILABLE_AT = time(15, 0)
PAPER_BOARD_LOT = 1000
PAPER_MAX_PARTICIPATION_BP = 500
PAPER_EXECUTION_SCHEMA_VERSION = "paper-execution-daily-candidate.v1"
PAPER_EXECUTION_PRODUCER_VERSION = "paper-execution-daily-producer.v2-t1-open"
PAPER_EXECUTION_SOURCE_TYPE = "paper_daily_execution_delayed_eod_replay_v1"
PAPER_EXECUTION_LEGACY_SOURCE_TYPES = frozenset({"paper_daily_execution_v1"})
PAPER_EXECUTION_RECEIPT_SCHEMA_VERSION = "paper-execution-operational-receipt.v1"
PAPER_PORTFOLIO_ID = "paper-main"
# A waiting/temporarily unavailable source must retain the frozen decision that
# produced it.  These states are deliberately separate from ``processed`` and
# ``superseded``: a retry may consume them, but they never make a source
# terminal by themselves.
PAPER_EXECUTION_PENDING_QUEUE_STATES = frozenset(
    {"pending_execution", "candidate_only_pending_append"}
)
PAPER_EXECUTION_TERMINAL_QUEUE_STATES = frozenset({"processed", "superseded"})
# Receipts written before the pending-state contract existed are still
# admissible when their complete source/result hashes and a narrowly
# retryable status can be revalidated.  They are adopted in memory only;
# historical files are never rewritten.
PAPER_EXECUTION_LEGACY_PENDING_QUEUE_STATES = frozenset({"waiting", "failed"})
PAPER_CASH_SETTLEMENT_SEMANTICS = (
    "gross_amount_plus_commission_plus_tax_v1"
)
PAPER_COST_ATTRIBUTION_SEMANTICS = (
    "commission_plus_tax_plus_slippage_attribution_v1"
)


class PaperExecutionProducerError(ValueError):
    """Paper execution source、時間或成本 evidence 不完整。"""


@dataclass(frozen=True)
class PaperExecutionPaths:
    """由排程 caller 明確提供的 input 與隔離 output 路徑。"""

    recommendation_json: Path
    state_db: Path
    market_db: Path
    output_root: Path
    ledger_db: Path | None = None
    clock_manifest: Path | None = None
    controlled_output_root: Path | None = None
    # The Paper policy consumer must receive an explicitly selected, hash-bound
    # official PIT sector sidecar or durable archive manifest.  The scheduler
    # owns selecting the exact path; this producer only validates and consumes
    # it at the frozen recommendation time.
    sector_membership_path: Path | None = None
    sector_membership_file_hash: str | None = None


@dataclass(frozen=True)
class _Recommendation:
    path: Path
    file_hash: str
    content_hash: str
    result_id: str
    portfolio_id: str
    profile_id: str | None
    created_at: datetime
    decision_date: date
    candidates: tuple[PortfolioConstructionCandidate, ...]
    raw_count: int
    config_projection: dict[str, object]


@dataclass(frozen=True)
class _QueueReceipt:
    path: Path
    state: str
    source_file_hash: str
    source_result_id: str
    portfolio_id: str
    execution_date: date | None
    recorded_at: datetime


@dataclass(frozen=True)
class _Position:
    stock_code: str
    quantity: int
    mark_price: Decimal
    market_value: Decimal


@dataclass(frozen=True)
class _State:
    snapshot_id: str
    portfolio_id: str
    decision_date: date
    source_result_id: str
    cash: Decimal
    total_value: Decimal
    positions: tuple[_Position, ...]
    content_hash: str
    file_hash: str
    ledger_event_ids: tuple[str, ...] = ()
    execution_snapshot_exists: bool = False


@dataclass(frozen=True)
class _Market:
    reference_date: date
    date: date
    prices: Mapping[str, Decimal]
    volumes: Mapping[str, int]
    rows: tuple[dict[str, object], ...]
    columns: tuple[str, ...]
    content_hash: str
    file_hash: str


def run_paper_execution_daily(
    paths: PaperExecutionPaths,
    *,
    now: datetime | None = None,
    calendar: OfficialTradingCalendar | None = None,
    confirm_append: bool = False,
) -> dict[str, object]:
    """建立一輪 T+1 next-session-open Paper execution candidate。

    Recommendation 在決策自然日凍結；只有下一個已由官方證據證明的交易日，
    且主機時間已到台北 09:00 session-open cutoff，才讀取當日官方開盤價並
    建立 Paper fill。CLI 不暴露 ``now``；該參數只供隔離測試使用。任何來源
    缺件、未來／逾期 execution session、calendar unknown、價格不一致、成交量
    或現金不足都會寫成具體 blocker，不會以空 fills 或零成本當作成功。
    """

    observed = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    ).astimezone(timezone.utc)
    output_root = _prepare_output_root(
        paths.output_root,
        controlled_root=paths.controlled_output_root,
    )
    base = {
        "schema_version": PAPER_EXECUTION_SCHEMA_VERSION,
        "producer": "data_module.paper_daily_execution_producer",
        "producer_version": PAPER_EXECUTION_PRODUCER_VERSION,
        "producer_code_sha256": _producer_code_hash(),
        "observed_at": observed.isoformat(),
        "decision_timezone": "Asia/Taipei",
        "portfolio_id": PAPER_PORTFOLIO_ID,
        "execution_contract": "t_plus_one_next_official_session_open",
        "snapshot_semantics": "preopen_t_minus_one_mark_to_market",
        "recommendation_freeze_semantics": "decision_natural_day_before_execution_session",
        "market_event_semantics": (
            "official_daily_prices_open_at_session_open_replayed_after_session_close"
        ),
        "cash_settlement_semantics": PAPER_CASH_SETTLEMENT_SEMANTICS,
        "cost_attribution_semantics": PAPER_COST_ATTRIBUTION_SEMANTICS,
        "execution_replay_mode": "delayed_eod_replay",
        "execution_event_time_basis": "official_session_open_schedule",
        "execution_event_time_proven": False,
        "candidate_only": True,
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "formal_credit": False,
        "research_only": True,
        "broker_order_allowed": False,
        "auto_rebalance_allowed": False,
        "writes_formal_controlled_paths": False,
        "writes_market_database": False,
        "historical_backfill_claimed": False,
        "late_replay_policy": "no_historical_backfill_pending_session_missed",
        "training_started": False,
        "broker_execution": False,
        "retryable": False,
        "append_requested": bool(confirm_append),
    }
    try:
        recommendation = _load_recommendation(
            paths.recommendation_json,
            observed=observed,
        )
        base.update(
            {
                "decision_date": recommendation.decision_date.isoformat(),
                "recommendation": {
                    "path": str(recommendation.path),
                    "file_hash": recommendation.file_hash,
                    "content_hash": recommendation.content_hash,
                    "result_id": recommendation.result_id,
                    "portfolio_id": recommendation.portfolio_id,
                    "profile_id": recommendation.profile_id,
                    "created_at": recommendation.created_at.isoformat(),
                    "decision_date": recommendation.decision_date.isoformat(),
                    "raw_row_count": recommendation.raw_count,
                    "config": recommendation.config_projection,
                },
            }
        )
        if paths.clock_manifest is not None:
            base["clock"] = _load_clock_projection(
                paths.clock_manifest,
                decision_date=recommendation.decision_date,
            )

        next_day = _next_day_projection(
            recommendation.decision_date,
            paths.market_db,
            calendar=calendar,
        )
        base["next_proven_trading_day"] = next_day
        base["official_calendar"] = next_day.get("calendar")
        if next_day.get("status") != "ready" or not next_day.get("date"):
            reason = str(next_day.get("reason") or "next_official_trading_day_unproven")
            base["status"] = "blocked"
            base["blockers"] = [reason]
            return _write_candidate(output_root, base)

        execution_date = _strict_date(
            next_day["date"],
            "next_proven_trading_day.date",
        )
        execution_open_at = datetime.combine(
            execution_date,
            TAIWAN_MARKET_OPEN,
            tzinfo=TAIPEI,
        )
        eod_replay_available_at = datetime.combine(
            execution_date,
            TAIWAN_EOD_REPLAY_AVAILABLE_AT,
            tzinfo=TAIPEI,
        )
        observed_taipei = observed.astimezone(TAIPEI)
        base.update(
            {
                "execution_date": execution_date.isoformat(),
                "execution_cutoff_at": execution_open_at.isoformat(),
                "execution_event_at": execution_open_at.isoformat(),
                "execution_event_timezone": "Asia/Taipei",
                "observed_taipei_at": observed_taipei.isoformat(),
                "execution_source_available_after": eod_replay_available_at.isoformat(),
                "execution_source_availability_policy": (
                    "conservative_session_close_plus_90m_delayed_eod_replay"
                ),
            }
        )
        if recommendation.created_at > execution_open_at:
            raise PaperExecutionProducerError(
                "recommendation was frozen after next session open"
            )
        if observed < execution_open_at:
            base["status"] = "waiting_for_execution_session"
            base["retryable"] = True
            base["blockers"] = [
                "paper_execution_waiting_for_next_session_open:"
                + execution_open_at.isoformat(),
            ]
            return _write_candidate(output_root, base)
        if observed < eod_replay_available_at:
            base["status"] = "waiting_for_execution_source"
            base["retryable"] = True
            base["blockers"] = [
                "paper_execution_waiting_for_delayed_eod_source:"
                + eod_replay_available_at.isoformat(),
            ]
            return _write_candidate(output_root, base)
        if observed_taipei.date() > execution_date:
            raise PaperExecutionProducerError(
                "paper execution session was missed; historical backfill is disabled"
            )

        # 早盤 snapshot 代表 execution session 開始前的 T-1 狀態；排程若先跑
        # preopen valuation，再於收盤後重播執行，必須重用這個 snapshot，而不是
        # 把排程順序誤判成永久 blocker。snapshot 仍全程唯讀，真正的 transition
        # 只會由明確 append 的 ledger 保存。
        state = _load_prior_state(
            paths.state_db,
            execution_date=execution_date,
            ledger_db=paths.ledger_db,
            allow_existing_execution_snapshot=True,
        )
        target = _build_target(
            recommendation,
            capital_amount=state.total_value,
        )
        # A delayed EOD retry must ignore only the immutable rows produced by
        # this exact recommendation.  Same-day rows from another intent are
        # real cash/position evidence and must be projected before the policy
        # batch so a second candidate cannot borrow yesterday's cash or sector.
        same_day_replay_ids = _expected_execution_fill_ids(
            state=state,
            target=target,
            execution_date=execution_date,
            recommendation_hash=recommendation.content_hash,
        )
        state = _apply_same_day_paper_fills(
            state,
            ledger_db=paths.ledger_db,
            execution_date=execution_date,
            exclude_fill_ids=frozenset(same_day_replay_ids),
        )
        symbols = tuple(
            sorted(
                {
                    candidate.stock_code for candidate in recommendation.candidates
                }
                | {position.stock_code for position in state.positions}
            )
        )
        reference_prices = {
            candidate.stock_code: candidate.reference_price
            for candidate in recommendation.candidates
        }
        market_reference = _reference_day_projection(
            recommendation.decision_date,
            paths.market_db,
            calendar=calendar,
        )
        base["market_reference_session"] = market_reference
        if market_reference.get("status") != "ready" or not market_reference.get("date"):
            reason = str(
                market_reference.get("reason")
                or "recommendation_market_reference_not_proven"
            )
            base["status"] = "blocked"
            base["blockers"] = [reason]
            return _write_candidate(output_root, base)
        reference_date = _strict_date(
            market_reference["date"],
            "market_reference_session.date",
        )
        base["market_reference_date"] = reference_date.isoformat()
        market = _load_market(
            paths.market_db,
            reference_date=reference_date,
            execution_date=execution_date,
            symbols=symbols,
            reference_prices=reference_prices,
        )
        policy = PaperPortfolioPolicyConfig()
        (
            policy_target,
            policy_projection,
            policy_context,
            policy_batch,
        ) = _evaluate_policy_batch(
            paths=paths,
            state=state,
            target=target,
            prices=market.prices,
            recommendation=recommendation,
            execution_date=execution_date,
            calendar=calendar,
            policy=policy,
        )
        fills, projection = _build_fills(
            state=state,
            target=policy_target,
            prices=market.prices,
            volumes=market.volumes,
            execution_date=execution_date,
            policy=policy,
            recommendation_hash=recommendation.content_hash,
        )
        post_policy = _reconcile_policy_after_fills(
            state=state,
            target=policy_target,
            fills=fills,
            projection=projection,
            policy_context=policy_context,
            policy_batch=policy_batch,
            policy=policy,
        )
        fill_records = _fill_candidate_records(fills, projection)
        target_policy = _policy_projection(policy, target, recommendation)
        target_policy.update(
            {
                "adapter": policy_projection,
                "target_quantities_after_policy": dict(
                    sorted(policy_target.items())
                ),
                "post_fill_reconciliation": post_policy,
            }
        )
        base.update(
            {
                "status": "machine_verified_candidate",
                "state_source": {
                    "path": str(paths.state_db.expanduser().resolve()),
                    "mode": "ro/query_only",
                    "snapshot_id": state.snapshot_id,
                    "decision_date": state.decision_date.isoformat(),
                    "source_result_id": state.source_result_id,
                    "cash": str(state.cash),
                    "total_value": str(state.total_value),
                    "content_hash": state.content_hash,
                    "file_hash": state.file_hash,
                    "file_hash_semantics": "main_db_bytes_observation_only",
                    "ledger_event_ids_applied": list(state.ledger_event_ids),
                    "execution_snapshot_exists": state.execution_snapshot_exists,
                    "snapshot_transition_policy": (
                        "preopen_snapshot_reused_append_only_postfill_transition"
                        if state.execution_snapshot_exists
                        else "prior_snapshot_append_only_postfill_transition"
                    ),
                },
                "market_source": {
                    "path": str(paths.market_db.expanduser().resolve()),
                    "table": "daily_prices",
                    "mode": "ro/query_only",
                    "decision_date": recommendation.decision_date.isoformat(),
                    "execution_date": market.date.isoformat(),
                    "execution_price_field": "開盤價",
                    "execution_event_at": execution_open_at.isoformat(),
                    "recommendation_reference_date": market.reference_date.isoformat(),
                    "recommendation_reference_date_basis": (
                        "latest_proven_official_session_on_or_before_decision_date"
                    ),
                    "recommendation_reference_price_field": "收盤價",
                    "liquidity_volume_date": market.reference_date.isoformat(),
                    "liquidity_volume_field": "成交股數",
                    "liquidity_volume_availability": "reference_session_close_before_execution",
                    "execution_data_availability": "delayed_eod_replay_after_session_close",
                    "execution_source_capture_at": None,
                    "execution_source_capture_at_proven": False,
                    "execution_source_time_semantics": (
                        "daily_prices_eod_row_has_no_intraday_capture_timestamp"
                    ),
                    "execution_source_kind": "official_daily_prices_eod",
                    "pretrade_cap_uses_execution_day_volume": False,
                    "execution_event_time_basis": "official_session_open_schedule",
                    "execution_event_time_proven": False,
                    "intraday_open_availability_proven": False,
                    "realtime_execution_allowed": False,
                    "max_participation_bp": PAPER_MAX_PARTICIPATION_BP,
                    "columns": list(market.columns),
                    "row_count": len(market.rows),
                    "content_hash": market.content_hash,
                    "file_hash": market.file_hash,
                    "file_hash_semantics": "main_db_bytes_observation_only",
                    "read_consistency": "sqlite_read_transaction",
                },
                "target_policy": target_policy,
                "fills": fill_records,
                "fill_count": len(fills),
                "post_execution_projection": projection,
                "ledger": {
                    "path": (
                        None
                        if paths.ledger_db is None
                        else str(paths.ledger_db.expanduser().resolve())
                    ),
                    "append_requested": bool(confirm_append),
                    "appended": False,
                    "readback_verified": False,
                },
            }
        )
        if not fills:
            base["status"] = "no_trade_required_candidate"
            base["blockers"] = ["paper_target_equals_current_state"]
        elif confirm_append:
            if paths.ledger_db is None:
                raise PaperExecutionProducerError(
                    "paper ledger path is required for explicit append"
                )
            idempotent_replay = _append_and_read_back(
                paths.ledger_db,
                fills,
            )
            ledger = base["ledger"]
            if not isinstance(ledger, dict):  # pragma: no cover - local construction
                raise PaperExecutionProducerError("ledger projection is invalid")
            ledger.update(
                {
                    "appended": True,
                    "readback_verified": True,
                    "idempotent_replay": idempotent_replay,
                    "fill_ids": [fill.fill_id for fill in fills],
                    "mode": "append_only_writer_then_ro_readback",
                }
            )
            post_policy["ledger_readback"] = _verify_policy_ledger_readback(
                paths.ledger_db,
                policy_context=policy_context,
                policy=policy,
            )
            post_policy["execution_readback_verified"] = True
        return _write_candidate(output_root, base)
    except PaperExecutionProducerError as error:
        retryable = _is_retryable_source_error(error)
        base.update(
            {
                "status": "blocked",
                "blockers": [str(error)],
                "retryable": retryable,
                "formal_ready": False,
            }
        )
        return _write_candidate(output_root, base)
    except (OSError, sqlite3.Error, InvalidOperation, ValueError) as error:
        base.update(
            {
                "status": "blocked",
                "blockers": [f"paper_execution_source_rejected:{type(error).__name__}:{error}"],
                "formal_ready": False,
            }
        )
        return _write_candidate(output_root, base)


def run_paper_execution_daily_from_queue(
    paths: PaperExecutionPaths,
    *,
    recommendation_root: Path,
    receipt_root: Path | None = None,
    now: datetime | None = None,
    calendar: OfficialTradingCalendar | None = None,
    confirm_append: bool = False,
    persist_receipt: bool = True,
) -> dict[str, object]:
    """由持久 recommendation queue 選取一筆待執行決策並可保存 receipt。

    Queue 只消費已存在且已凍結的 recommendation；它依官方下一 session
    是否落在當前台北自然日選取 due item。成功、等待或失敗都可寫入獨立
    operational receipt，避免排程依賴人工每日改環境變數。receipt 不會改寫
    recommendation、snapshot、market DB 或 Formal DB。
    """

    observed = _aware_datetime(
        now if now is not None else datetime.now(timezone.utc), "now"
    ).astimezone(timezone.utc)
    selected, reason = resolve_pending_recommendation(
        recommendation_root,
        observed=observed,
        market_db=paths.market_db,
        calendar=calendar,
        receipt_root=receipt_root,
    )
    if selected is None:
        result = _write_queue_status(
            paths.output_root,
            recommendation_root=recommendation_root,
            observed=observed,
            reason=reason,
            append_requested=confirm_append,
            controlled_root=paths.controlled_output_root,
        )
    else:
        selected_paths = PaperExecutionPaths(
            recommendation_json=selected,
            state_db=paths.state_db,
            market_db=paths.market_db,
            output_root=paths.output_root,
            ledger_db=paths.ledger_db,
            clock_manifest=paths.clock_manifest,
            controlled_output_root=paths.controlled_output_root,
            sector_membership_path=paths.sector_membership_path,
            sector_membership_file_hash=paths.sector_membership_file_hash,
        )
        result = run_paper_execution_daily(
            selected_paths,
            now=observed,
            calendar=calendar,
            confirm_append=confirm_append,
        )
    if receipt_root is not None and persist_receipt:
        result = persist_operational_receipt(
            result,
            receipt_root,
            observed=observed,
        )
    return result


def resolve_pending_recommendation(
    recommendation_root: Path,
    *,
    observed: datetime | None = None,
    market_db: Path | None = None,
    calendar: OfficialTradingCalendar | None = None,
    receipt_root: Path | None = None,
) -> tuple[Path | None, str]:
    """選取尚未處理、且下一官方 session 已到期的 frozen recommendation。

    同一個 Paper portfolio／execution session 只允許一個 frozen source。
    同 session 的較舊候選會留下 ``superseded`` receipt，避免 processed hash
    排除最新候選後，下一次重跑又切換到較舊策略。
    """

    observed_at = _aware_datetime(
        observed if observed is not None else datetime.now(timezone.utc), "observed"
    ).astimezone(timezone.utc)
    resolved_root = recommendation_root.expanduser().resolve()
    if not resolved_root.exists():
        return None, "recommendation_root_missing"
    if not resolved_root.is_dir():
        return None, "recommendation_root_not_directory"
    queue_receipts, receipt_issues = _load_queue_receipts(receipt_root)
    terminal_hashes = {
        receipt.source_file_hash
        for receipt in queue_receipts
        if receipt.state in PAPER_EXECUTION_TERMINAL_QUEUE_STATES
    }
    processed_by_execution: dict[tuple[str, date], _QueueReceipt] = {}
    for receipt in queue_receipts:
        if receipt.state != "processed" or receipt.execution_date is None:
            continue
        processed_by_execution.setdefault(
            (receipt.portfolio_id, receipt.execution_date),
            receipt,
        )
    pending_by_execution: dict[tuple[str, date], list[_QueueReceipt]] = {}
    for receipt in queue_receipts:
        if (
            receipt.state in PAPER_EXECUTION_PENDING_QUEUE_STATES
            and receipt.execution_date is not None
        ):
            pending_by_execution.setdefault(
                (receipt.portfolio_id, receipt.execution_date),
                [],
            ).append(receipt)
    stale_pending = [
        receipt
        for receipt in queue_receipts
        if (
            receipt.state in PAPER_EXECUTION_PENDING_QUEUE_STATES
            and receipt.execution_date is not None
            and receipt.execution_date < observed_at.astimezone(TAIPEI).date()
        )
    ]
    if stale_pending:
        stale_dates = sorted(
            {receipt.execution_date for receipt in stale_pending if receipt.execution_date}
        )
        return None, (
            "pending_execution_session_missed:"
            + ",".join(item.isoformat() for item in stale_dates)
        )
    observed_taipei_date = observed_at.astimezone(TAIPEI).date()
    candidates: list[_Recommendation] = []
    invalid_sources: list[str] = []
    for path in sorted(resolved_root.glob("*.json")):
        try:
            recommendation = _load_recommendation(path, observed=observed_at)
        except (OSError, PaperExecutionProducerError, ValueError) as error:
            invalid_sources.append(
                f"{path.name}:{type(error).__name__}:{str(error)[:160]}"
            )
            continue
        if recommendation.decision_date >= observed_taipei_date:
            continue
        if recommendation.file_hash in terminal_hashes:
            continue
        candidates.append(recommendation)
    if not candidates:
        if invalid_sources:
            return None, _queue_diagnostic_reason(
                "no_pending_recommendation_invalid_source",
                invalid_sources,
            )
        if receipt_issues:
            return None, _queue_diagnostic_reason(
                "no_pending_recommendation_invalid_receipt",
                receipt_issues,
            )
        return None, "no_pending_recommendation"
    candidates.sort(
        key=lambda item: (
            item.decision_date,
            item.created_at.astimezone(timezone.utc),
            item.path.name,
        )
    )
    if market_db is None:
        return candidates[-1].path, "latest_prior_frozen_recommendation"

    due_by_execution: dict[tuple[str, date], list[_Recommendation]] = {}
    unknown: list[_Recommendation] = []
    for recommendation in candidates:
        next_day = _next_day_projection(
            recommendation.decision_date,
            market_db,
            calendar=calendar,
        )
        if next_day.get("status") == "ready" and next_day.get("date"):
            next_date = _strict_date(next_day["date"], "next_proven_trading_day.date")
            if next_date == observed_taipei_date:
                due_by_execution.setdefault(
                    (recommendation.portfolio_id, next_date),
                    [],
                ).append(recommendation)
            continue
        unknown.append(recommendation)

    if due_by_execution:
        # The fixed Paper producer currently serves one portfolio, but retaining
        # the key makes the queue invariant explicit if another research profile
        # is introduced later.
        selected_due: list[_Recommendation] = []
        pending_retry_selected = False
        for execution_key, group in due_by_execution.items():
            processed = processed_by_execution.get(execution_key)
            if processed is not None:
                for recommendation in group:
                    if recommendation.file_hash == processed.source_file_hash:
                        continue
                    _write_superseded_receipt(
                        recommendation,
                        execution_date=execution_key[1],
                        selected_source_file_hash=processed.source_file_hash,
                        receipt_root=receipt_root,
                        observed=observed_at,
                    )
                    terminal_hashes.add(recommendation.file_hash)
                continue
            pending = pending_by_execution.get(execution_key, [])
            pending_hashes = {item.source_file_hash for item in pending}
            if len(pending_hashes) > 1:
                # Two different frozen sources have both been recorded as
                # pending for one execution session.  Switching between them
                # would make retry non-deterministic, so stop and expose the
                # conflict for reconciliation.
                return None, (
                    "pending_execution_source_conflict:"
                    + execution_key[1].isoformat()
                )
            if pending_hashes:
                pinned_hash = next(iter(pending_hashes))
                pinned = next(
                    (
                        recommendation
                        for recommendation in group
                        if recommendation.file_hash == pinned_hash
                    ),
                    None,
                )
                if pinned is None:
                    return None, (
                        "pending_execution_source_missing:"
                        + execution_key[1].isoformat()
                    )
                # Leave newer recommendations unclassified until this pinned
                # source reaches a terminal receipt.  A later retry therefore
                # cannot silently replace a pending decision with a 05:10
                # recommendation for the same execution session.
                selected_due.append(pinned)
                pending_retry_selected = True
                continue
            winner = max(
                group,
                key=lambda item: (
                    item.decision_date,
                    item.created_at.astimezone(timezone.utc),
                    item.path.name,
                ),
            )
            selected_due.append(winner)
            for recommendation in group:
                if recommendation.file_hash == winner.file_hash:
                    continue
                _write_superseded_receipt(
                    recommendation,
                    execution_date=execution_key[1],
                    selected_source_file_hash=winner.file_hash,
                    receipt_root=receipt_root,
                    observed=observed_at,
                )
                terminal_hashes.add(recommendation.file_hash)
        if selected_due:
            selected_due.sort(
                key=lambda item: (
                    item.decision_date,
                    item.created_at.astimezone(timezone.utc),
                    item.path.name,
                )
            )
            return selected_due[-1].path, (
                "pending_execution_retry"
                if pending_retry_selected
                else "next_official_session_due"
            )
        if receipt_issues:
            return None, _queue_diagnostic_reason(
                "no_pending_recommendation_already_processed_invalid_receipt",
                receipt_issues,
            )
        return None, "no_pending_recommendation_already_processed"
    if unknown:
        # calendar unknown 時交給正式 producer 留下可稽核 blocker，而不是
        # 靜默跳過所有 frozen input。
        unknown.sort(
            key=lambda item: (
                item.decision_date,
                item.created_at.astimezone(timezone.utc),
                item.path.name,
            )
        )
        return unknown[-1].path, "next_official_session_unproven"
    if invalid_sources:
        return None, _queue_diagnostic_reason(
            "no_pending_recommendation_invalid_source",
            invalid_sources,
        )
    return None, "no_pending_recommendation_due_for_current_session"


def persist_operational_receipt(
    result: Mapping[str, object],
    receipt_root: Path,
    *,
    observed: datetime | None = None,
) -> dict[str, object]:
    """以 immutable 新檔保存 queue attempt／processed／failed receipt。"""

    resolved_root = receipt_root.expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    observed_value = result.get("observed_at")
    if isinstance(observed_value, str):
        recorded_at = _aware_datetime(observed_value, "result.observed_at").astimezone(
            timezone.utc
        )
    else:
        recorded_at = _aware_datetime(
            observed if observed is not None else datetime.now(timezone.utc),
            "observed",
        ).astimezone(timezone.utc)
    source = result.get("recommendation")
    source_map = source if isinstance(source, Mapping) else {}
    source_file_hash = source_map.get("file_hash")
    source_result_id = source_map.get("result_id")
    state_source = result.get("state_source")
    state_source_map = state_source if isinstance(state_source, Mapping) else {}
    portfolio_id = source_map.get("portfolio_id") or state_source_map.get(
        "portfolio_id",
        PAPER_PORTFOLIO_ID,
    )
    candidate_hash = result.get("content_sha256")
    status = str(result.get("status") or "unknown")
    queue_state = _operational_queue_state(result)
    receipt_body: dict[str, object] = {
        "schema_version": PAPER_EXECUTION_RECEIPT_SCHEMA_VERSION,
        "recorded_at": recorded_at.isoformat(),
        "status": status,
        "queue_state": queue_state,
        "portfolio_id": str(portfolio_id),
        "source_file_hash": None if source_file_hash is None else str(source_file_hash),
        "source_result_id": None if source_result_id is None else str(source_result_id),
        "decision_date": result.get("decision_date"),
        "execution_date": result.get("execution_date"),
        "candidate_content_sha256": (
            None if candidate_hash is None else str(candidate_hash)
        ),
        "candidate_file_hash": result.get("candidate_file_hash"),
        "candidate_path": result.get("candidate_path"),
        "append_requested": result.get("append_requested") is True,
        "ledger": result.get("ledger"),
        "result": dict(result),
    }
    receipt_body["content_sha256"] = _payload_hash(receipt_body)
    source_token = (
        str(source_file_hash).replace("sha256:", "")[:16]
        if source_file_hash is not None
        else "none"
    )
    date_token = str(result.get("execution_date") or recorded_at.date().isoformat())
    timestamp_token = recorded_at.strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"paper_execution_{date_token}_{source_token}_{timestamp_token}"
    receipt_path = _write_receipt_payload(resolved_root, receipt_body, stem=stem)
    receipt_file_hash = _file_sha256(receipt_path)
    return {
        **dict(result),
        "operational_receipt": {
            "path": str(receipt_path),
            "file_hash": receipt_file_hash,
            "content_hash": str(receipt_body["content_sha256"]),
            "queue_state": queue_state,
        },
    }


def _write_superseded_receipt(
    recommendation: _Recommendation,
    *,
    execution_date: date,
    selected_source_file_hash: str,
    receipt_root: Path | None,
    observed: datetime,
) -> None:
    """保存同一 execution session 被較新 frozen source 取代的明確紀錄。"""

    if receipt_root is None:
        return
    resolved_root = receipt_root.expanduser().resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {
        "schema_version": PAPER_EXECUTION_RECEIPT_SCHEMA_VERSION,
        "recorded_at": observed.astimezone(timezone.utc).isoformat(),
        "status": "superseded",
        "queue_state": "superseded",
        "portfolio_id": recommendation.portfolio_id,
        "source_file_hash": recommendation.file_hash,
        "source_result_id": recommendation.result_id,
        "decision_date": recommendation.decision_date.isoformat(),
        "execution_date": execution_date.isoformat(),
        "candidate_content_sha256": None,
        "candidate_file_hash": None,
        "candidate_path": None,
        "append_requested": False,
        "ledger": None,
        "superseded_by_source_file_hash": selected_source_file_hash,
        "reason": "same_portfolio_execution_session_latest_frozen_recommendation",
        "result": {
            "status": "superseded",
            "recommendation": {
                "path": str(recommendation.path),
                "file_hash": recommendation.file_hash,
                "content_hash": recommendation.content_hash,
                "result_id": recommendation.result_id,
                "portfolio_id": recommendation.portfolio_id,
                "created_at": recommendation.created_at.isoformat(),
                "decision_date": recommendation.decision_date.isoformat(),
            },
            "decision_date": recommendation.decision_date.isoformat(),
            "execution_date": execution_date.isoformat(),
        },
    }
    body["content_sha256"] = _payload_hash(body)
    source_token = recommendation.file_hash.replace("sha256:", "")[:16]
    stem = (
        f"paper_execution_superseded_{execution_date.isoformat()}_"
        f"{source_token}_{observed.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
    )
    _write_receipt_payload(resolved_root, body, stem=stem)


def _write_receipt_payload(
    receipt_root: Path,
    body: Mapping[str, object],
    *,
    stem: str,
) -> Path:
    encoded = (_canonical_json(dict(body)) + "\n").encode("utf-8")
    for suffix in range(1000):
        suffix_text = "" if suffix == 0 else f"_{suffix}"
        receipt_path = receipt_root / f"{stem}{suffix_text}.json"
        try:
            with receipt_path.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            return receipt_path
        except FileExistsError:
            continue
    raise PaperExecutionProducerError("paper operational receipt filename exhausted")


def _write_queue_status(
    output_root: Path,
    *,
    recommendation_root: Path,
    observed: datetime,
    reason: str,
    append_requested: bool,
    controlled_root: Path | None = None,
) -> dict[str, object]:
    resolved_output = _prepare_output_root(
        output_root,
        controlled_root=controlled_root,
    )
    body: dict[str, object] = {
        "schema_version": PAPER_EXECUTION_SCHEMA_VERSION,
        "producer": "data_module.paper_daily_execution_producer",
        "producer_version": PAPER_EXECUTION_PRODUCER_VERSION,
        "producer_code_sha256": _producer_code_hash(),
        "observed_at": observed.isoformat(),
        "decision_timezone": "Asia/Taipei",
        "execution_contract": "t_plus_one_next_official_session_open",
        "snapshot_semantics": "preopen_t_minus_one_mark_to_market",
        "execution_replay_mode": "delayed_eod_replay",
        "execution_event_time_basis": "official_session_open_schedule",
        "execution_event_time_proven": False,
        "candidate_only": True,
        "formal_ready": False,
        "formal_consumer_compatible": False,
        "formal_credit": False,
        "research_only": True,
        "broker_order_allowed": False,
        "auto_rebalance_allowed": False,
        "writes_formal_controlled_paths": False,
        "writes_market_database": False,
        "historical_backfill_claimed": False,
        "late_replay_policy": "no_historical_backfill_pending_session_missed",
        "training_started": False,
        "broker_execution": False,
        "append_requested": bool(append_requested),
        "status": "skipped_no_pending_recommendation",
        "blockers": [reason],
        "queue": {
            "recommendation_root": str(recommendation_root.expanduser().resolve()),
            "selection": "next_official_session_due",
            "reason": reason,
            "source_configured": recommendation_root.exists(),
            "late_replay_policy": "no_historical_backfill_pending_session_missed",
        },
    }
    return _write_candidate(resolved_output, body)


def _processed_recommendation_hashes(receipt_root: Path | None) -> set[str]:
    receipts, _ = _load_queue_receipts(receipt_root)
    return {
        receipt.source_file_hash
        for receipt in receipts
        if receipt.state == "processed"
    }


def _load_queue_receipts(
    receipt_root: Path | None,
) -> tuple[tuple[_QueueReceipt, ...], tuple[str, ...]]:
    """讀取完整 receipt，並只把可重驗狀態接回 queue。

    ``pending_execution``（以及舊版未完成 append 的
    ``candidate_only_pending_append``）不是 terminal state，但仍是重要的
    queue state：它把 execution session 綁回第一次選中的 recommendation，
    讓 crash／來源晚到的重試不會改用另一份 frozen source。
    """

    if receipt_root is None:
        return (), ()
    resolved_root = receipt_root.expanduser().resolve()
    if not resolved_root.is_dir():
        return (), ()
    valid: list[_QueueReceipt] = []
    issues: list[str] = []
    for path in sorted(resolved_root.glob("*.json")):
        try:
            raw_value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            issues.append(f"{path.name}:{type(error).__name__}:{str(error)[:160]}")
            continue
        if not isinstance(raw_value, Mapping):
            issues.append(f"{path.name}:receipt must be a JSON object")
            continue
        state = raw_value.get("queue_state")
        if state not in (
            PAPER_EXECUTION_TERMINAL_QUEUE_STATES
            | PAPER_EXECUTION_PENDING_QUEUE_STATES
            | PAPER_EXECUTION_LEGACY_PENDING_QUEUE_STATES
        ):
            continue
        validation_error = _validate_queue_receipt(path, raw_value)
        if validation_error is not None:
            issues.append(f"{path.name}:{validation_error}")
            continue
        source_hash = raw_value.get("source_file_hash")
        source_result_id = raw_value.get("source_result_id")
        portfolio_value = raw_value.get("portfolio_id", PAPER_PORTFOLIO_ID)
        recorded_value = raw_value.get("recorded_at")
        execution_value = raw_value.get("execution_date")
        execution_date = (
            None
            if execution_value is None
            else _strict_date(execution_value, f"{path.name}.execution_date")
        )
        if not isinstance(source_hash, str) or not isinstance(source_result_id, str):
            # _validate_queue_receipt has already rejected this path.  Keep the
            # guard for type narrowing and future schema additions.
            issues.append(f"{path.name}:receipt source identity is invalid")
            continue
        try:
            recorded_at = _aware_datetime(recorded_value, f"{path.name}.recorded_at")
        except PaperExecutionProducerError as error:
            issues.append(f"{path.name}:receipt recorded_at is invalid:{error}")
            continue
        valid.append(
            _QueueReceipt(
                path=path,
                state=(
                    "pending_execution"
                    if state in PAPER_EXECUTION_LEGACY_PENDING_QUEUE_STATES
                    else str(state)
                ),
                source_file_hash=source_hash,
                source_result_id=source_result_id,
                portfolio_id=str(portfolio_value),
                execution_date=execution_date,
                recorded_at=recorded_at,
            )
        )
    return tuple(valid), tuple(issues)


def _validate_queue_receipt(
    path: Path,
    value: Mapping[object, object],
) -> str | None:
    """驗證 receipt hash、source identity、日期與 ledger readback。

    Historical ``waiting``／``failed`` receipts receive the same immutable
    source/content/date checks as new ``pending_execution`` receipts.  Only a
    clearly missing/late execution source is adopted for retry; mixed timing or
    identity violations are rejected even if a missing-row marker is present.
    """

    if value.get("schema_version") != PAPER_EXECUTION_RECEIPT_SCHEMA_VERSION:
        return "unsupported_schema_version"
    declared_hash = value.get("content_sha256")
    if not _is_sha256(declared_hash):
        return "content_hash_missing_or_invalid"
    body = dict(value)
    body.pop("content_sha256", None)
    if _payload_hash(body) != declared_hash:
        return "content_hash_mismatch"
    try:
        recorded_at = _aware_datetime(value.get("recorded_at"), f"{path.name}.recorded_at")
    except PaperExecutionProducerError as error:
        return f"recorded_at_invalid:{error}"
    source_hash = value.get("source_file_hash")
    if not _is_sha256(source_hash):
        return "source_file_hash_missing_or_invalid"
    source_result_id = value.get("source_result_id")
    if not isinstance(source_result_id, str) or not source_result_id.strip():
        return "source_result_id_missing"
    portfolio_value = value.get("portfolio_id", PAPER_PORTFOLIO_ID)
    if not isinstance(portfolio_value, str) or not portfolio_value.strip():
        return "portfolio_id_missing"
    execution_value = value.get("execution_date")
    if execution_value is None:
        return "execution_date_missing"
    try:
        _strict_date(execution_value, f"{path.name}.execution_date")
    except PaperExecutionProducerError as error:
        return str(error)

    result_value = value.get("result")
    if not isinstance(result_value, Mapping):
        return "result_missing"
    recommendation_value = result_value.get("recommendation")
    if not isinstance(recommendation_value, Mapping):
        return "result_recommendation_missing"
    if recommendation_value.get("file_hash") != source_hash:
        return "result_source_file_hash_mismatch"
    if recommendation_value.get("result_id") != source_result_id:
        return "result_source_result_id_mismatch"
    recommendation_content_hash = recommendation_value.get("content_hash")
    if not _is_sha256(recommendation_content_hash):
        return "result_source_content_hash_missing_or_invalid"
    source_path = recommendation_value.get("path")
    if not isinstance(source_path, str) or not source_path.strip():
        return "result_recommendation_path_missing"
    try:
        source_raw = Path(source_path).expanduser().resolve().read_bytes()
        if _sha256_bytes(source_raw) != source_hash:
            return "recommendation_source_changed"
        source_value = json.loads(source_raw.decode("utf-8"))
        if not isinstance(source_value, Mapping):
            return "recommendation_source_not_object"
        if _payload_hash(source_value) != recommendation_content_hash:
            return "recommendation_source_content_changed"
        recommendation = _load_recommendation(
            Path(source_path).expanduser().resolve(),
            observed=recorded_at,
        )
        if recommendation.result_id != source_result_id:
            return "recommendation_source_result_id_changed"
        if recommendation.decision_date.isoformat() != recommendation_value.get(
            "decision_date"
        ):
            return "recommendation_source_decision_date_changed"
    except PaperExecutionProducerError as error:
        return f"recommendation_source_contract_invalid:{type(error).__name__}"
    except (UnicodeError, json.JSONDecodeError):
        return "recommendation_source_invalid_json"
    except (OSError, ValueError, RuntimeError) as error:
        return f"recommendation_source_unreadable:{type(error).__name__}"

    raw_state = str(value.get("queue_state"))
    state = (
        "pending_execution"
        if raw_state in PAPER_EXECUTION_LEGACY_PENDING_QUEUE_STATES
        else raw_state
    )
    if result_value.get("execution_date") != execution_value:
        return "result_execution_date_mismatch"
    if result_value.get("decision_date") != recommendation_value.get("decision_date"):
        return "result_decision_date_mismatch"
    if state == "superseded":
        superseded_by = value.get("superseded_by_source_file_hash")
        if not _is_sha256(superseded_by) or superseded_by == source_hash:
            return "superseded_source_identity_invalid"
        if result_value.get("status") != "superseded":
            return "superseded_result_status_mismatch"
        return None

    result_status = result_value.get("status")
    legacy_pending = raw_state in PAPER_EXECUTION_LEGACY_PENDING_QUEUE_STATES
    if state in PAPER_EXECUTION_PENDING_QUEUE_STATES:
        if result_status in {"waiting_for_execution_session", "waiting_for_execution_source"}:
            if not legacy_pending and result_value.get("retryable") is not True:
                return "pending_waiting_result_not_retryable"
            if not _has_retryable_waiting_blocker(result_value):
                return "pending_waiting_reason_not_retryable"
            return _validate_optional_candidate_hashes(value, result_value)
        if result_status == "blocked":
            if not legacy_pending and result_value.get("retryable") is not True:
                return "pending_blocked_result_not_retryable"
            if not _has_retryable_source_blocker(result_value):
                return "pending_blocked_reason_not_retryable"
            return _validate_optional_candidate_hashes(value, result_value)
        if result_status == "machine_verified_candidate":
            candidate_error = _validate_required_candidate_hashes(value, result_value)
            if candidate_error is not None:
                return candidate_error
            ledger_value = value.get("ledger")
            result_ledger = result_value.get("ledger")
            if not isinstance(ledger_value, Mapping) or not isinstance(result_ledger, Mapping):
                return "pending_ledger_missing"
            if dict(ledger_value) != dict(result_ledger):
                return "pending_ledger_projection_mismatch"
            if ledger_value.get("appended") is True:
                return "pending_ledger_already_appended"
            return None
        return "pending_result_status_invalid"

    if state != "processed":
        return "unsupported_terminal_queue_state"
    candidate_error = _validate_required_candidate_hashes(value, result_value)
    if candidate_error is not None:
        return candidate_error
    if result_status == "no_trade_required_candidate":
        if result_value.get("fill_count") != 0:
            return "no_trade_fill_count_mismatch"
        return None
    if result_status != "machine_verified_candidate":
        return "processed_result_status_invalid"
    ledger_value = value.get("ledger")
    result_ledger = result_value.get("ledger")
    if not isinstance(ledger_value, Mapping) or not isinstance(result_ledger, Mapping):
        return "processed_ledger_missing"
    if dict(ledger_value) != dict(result_ledger):
        return "processed_ledger_projection_mismatch"
    if ledger_value.get("appended") is not True:
        return "processed_ledger_not_appended"
    if ledger_value.get("readback_verified") is not True:
        return "processed_ledger_readback_not_verified"
    if not _ledger_readback_matches(
        ledger_value,
        recommendation_content_hash=str(recommendation_content_hash),
        execution_date=str(execution_value),
        portfolio_id=str(portfolio_value),
    ):
        return "processed_ledger_readback_mismatch"
    return None


def _validate_required_candidate_hashes(
    value: Mapping[object, object],
    result: Mapping[object, object],
) -> str | None:
    candidate_hash = value.get("candidate_content_sha256")
    candidate_file_hash = value.get("candidate_file_hash")
    if not _is_sha256(candidate_hash) or not _is_sha256(candidate_file_hash):
        return "candidate_hash_missing_or_invalid"
    if result.get("content_sha256") != candidate_hash:
        return "result_candidate_content_hash_mismatch"
    if result.get("candidate_file_hash") != candidate_file_hash:
        return "result_candidate_file_hash_mismatch"
    candidate_path = result.get("candidate_path")
    if not isinstance(candidate_path, str) or not candidate_path.strip():
        return "candidate_path_missing"
    try:
        candidate_raw = Path(candidate_path).expanduser().resolve().read_bytes()
        if _sha256_bytes(candidate_raw) != candidate_file_hash:
            return "candidate_file_changed"
        candidate_value = json.loads(candidate_raw.decode("utf-8"))
        if not isinstance(candidate_value, Mapping):
            return "candidate_not_object"
        candidate_body = dict(candidate_value)
        candidate_declared = candidate_body.pop("content_sha256", None)
        if candidate_declared != candidate_hash:
            return "candidate_content_hash_mismatch"
        if _payload_hash(candidate_body) != candidate_hash:
            return "candidate_content_changed"
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RuntimeError):
        return "candidate_unreadable"
    return None


def _validate_optional_candidate_hashes(
    value: Mapping[object, object],
    result: Mapping[object, object],
) -> str | None:
    candidate_hash = value.get("candidate_content_sha256")
    candidate_file_hash = value.get("candidate_file_hash")
    if candidate_hash is None and candidate_file_hash is None:
        return None
    return _validate_required_candidate_hashes(value, result)


def _ledger_readback_matches(
    ledger: Mapping[object, object],
    *,
    recommendation_content_hash: str,
    execution_date: str,
    portfolio_id: str,
) -> bool:
    path_value = ledger.get("path")
    fill_ids_value = ledger.get("fill_ids")
    if not isinstance(path_value, str) or not path_value.strip():
        return False
    if not isinstance(fill_ids_value, list) or not fill_ids_value:
        return False
    fill_ids = [item for item in fill_ids_value if isinstance(item, str) and item]
    if len(fill_ids) != len(fill_ids_value) or len(set(fill_ids)) != len(fill_ids):
        return False
    resolved = Path(path_value).expanduser().resolve()
    if not resolved.is_file():
        return False
    connection: sqlite3.Connection | None = None
    try:
        uri = f"file:{resolved.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        placeholders = ",".join("?" for _ in fill_ids)
        rows = connection.execute(
            "SELECT fill_id, order_id, portfolio_id, event_date, source_event_id, "
            "research_only, broker_order_allowed, auto_rebalance_allowed "
            "FROM paper_trade_ledger "
            f"WHERE fill_id IN ({placeholders})",
            tuple(fill_ids),
        ).fetchall()
        if len(rows) != len(fill_ids):
            return False
        by_id = {str(row["fill_id"]): row for row in rows}
        expected_prefix = (
            f"paper-execution:{execution_date}:"
            f"{recommendation_content_hash.replace('sha256:', '')[:16]}:"
        )
        return all(
            fill_id in by_id
            and str(by_id[fill_id]["fill_id"]) == fill_id
            and str(by_id[fill_id]["order_id"])
            == fill_id.replace("paper-execution:", "paper-order:", 1)
            and str(by_id[fill_id]["portfolio_id"]) == portfolio_id
            and str(by_id[fill_id]["event_date"]) == execution_date
            and str(by_id[fill_id]["source_event_id"]) == fill_id
            and fill_id.startswith(expected_prefix)
            and int(by_id[fill_id]["research_only"]) == 1
            and int(by_id[fill_id]["broker_order_allowed"]) == 0
            and int(by_id[fill_id]["auto_rebalance_allowed"]) == 0
            for fill_id in fill_ids
        )
    except (OSError, RuntimeError, sqlite3.Error, ValueError, TypeError):
        return False
    finally:
        if connection is not None:
            connection.close()


def _queue_diagnostic_reason(prefix: str, diagnostics: Sequence[str]) -> str:
    detail = "|".join(diagnostics[:3])
    return prefix if not detail else f"{prefix}:{detail}"


_RETRYABLE_SOURCE_ERROR_MARKERS = (
    "paper market DB is missing",
    "paper market read failed:",
    "daily_prices is missing execution-date open rows:",
    "daily_prices is missing market-reference-date close rows:",
    "daily_prices is missing market-reference-date liquidity rows:",
)
_NONRETRYABLE_SOURCE_MARKERS = (
    "future",
    "identity",
    "clock",
    "timing",
    "session was missed",
    "recommendation was frozen",
    "reference price does not match",
    "same-day",
    "same_day",
    "decision date",
    "decision_date",
    "execution date mismatch",
)


def _is_retryable_source_blocker_text(value: str) -> bool:
    lowered = value.casefold()
    if any(marker in lowered for marker in _NONRETRYABLE_SOURCE_MARKERS):
        return False
    return any(marker.casefold() in lowered for marker in _RETRYABLE_SOURCE_ERROR_MARKERS)


def _is_retryable_source_error(error: BaseException) -> bool:
    """Classify only late/missing market source errors as retryable.

    A malformed recommendation, a clock/session violation, a price mismatch or
    any other contract error remains terminal.  This narrow list is what lets
    the 15:05 failed attempt be retried at 21:00 without turning a bad source
    into a perpetually pending queue item.
    """

    return _is_retryable_source_blocker_text(str(error))


def _has_retryable_source_blocker(result: Mapping[object, object]) -> bool:
    blockers = result.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        return False
    # Every blocker must belong to the same retryable source class.  In
    # particular, a missing row combined with a future/identity/timing error
    # cannot be downgraded to a pending retry by matching only one string.
    return all(
        isinstance(blocker, str) and _is_retryable_source_blocker_text(blocker)
        for blocker in blockers
    )


def _has_retryable_waiting_blocker(result: Mapping[object, object]) -> bool:
    blockers = result.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        return False
    allowed_prefixes = (
        "paper_execution_waiting_for_next_session_open:",
        "paper_execution_waiting_for_delayed_eod_source:",
    )
    return all(
        isinstance(blocker, str)
        and blocker.startswith(allowed_prefixes)
        for blocker in blockers
    )


def _operational_queue_state(result: Mapping[str, object]) -> str:
    status = str(result.get("status") or "unknown")
    if status == "no_trade_required_candidate":
        return "processed"
    if status == "machine_verified_candidate":
        ledger = result.get("ledger")
        if isinstance(ledger, Mapping) and ledger.get("appended") is True:
            return "processed"
        return "candidate_only_pending_append"
    if status.startswith("waiting_"):
        return "pending_execution"
    if status == "blocked" and result.get("retryable") is True:
        return "pending_execution"
    if status == "skipped_no_pending_recommendation":
        return "skipped"
    return "failed"


def next_proven_trading_day(
    start_date: date,
    *,
    market_db: Path,
    calendar: OfficialTradingCalendar | None = None,
    horizon_days: int = 10,
) -> dict[str, object]:
    """只沿官方 evidence 尋找下一個開市日，不以 weekday 猜測。"""

    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or not 1 <= horizon_days <= 31:
        raise PaperExecutionProducerError("horizon_days must be an integer between 1 and 31")
    for offset in range(1, horizon_days + 1):
        candidate = start_date + timedelta(days=offset)
        projection, blocker = _calendar_evidence(
            market_db,
            target_date=candidate,
            calendar=calendar,
        )
        if projection.get("is_trading_day") is True:
            return {
                "status": "ready",
                "date": candidate.isoformat(),
                "calendar": projection,
            }
        if projection.get("is_trading_day") is None:
            return {
                "status": "blocked",
                "date": None,
                "calendar": projection,
                "reason": blocker or "next_official_trading_day_unproven",
            }
    return {
        "status": "blocked",
        "date": None,
        "calendar": None,
        "reason": "next_official_trading_day_not_found_in_bounded_horizon",
    }


def _next_day_projection(
    start_date: date,
    market_db: Path,
    *,
    calendar: OfficialTradingCalendar | None,
) -> dict[str, object]:
    try:
        return next_proven_trading_day(
            start_date,
            market_db=market_db,
            calendar=calendar,
        )
    except Exception as error:  # noqa: BLE001 - status must remain structured
        return {
            "status": "blocked",
            "date": None,
            "reason": f"next_official_trading_day_unproven:{type(error).__name__}:{error}",
        }


def latest_proven_market_session_on_or_before(
    target_date: date,
    *,
    market_db: Path,
    calendar: OfficialTradingCalendar | None = None,
    horizon_days: int = 31,
) -> dict[str, object]:
    """以官方 evidence 找到 target date 當日或之前最近的交易 session。

    recommendation 的 decision date 可以落在週末或休市日。此時市場 reference
    必須綁定實際有官方資料的上一 session，不能把 decision date 的自然日直接
    當成 ``daily_prices`` 日期，也不能用 weekday 規則猜測。遇到未知日曆時
    保持 blocked，直到較早日期有可重驗的官方日曆／本地 market_indices 證據。
    """

    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or not 1 <= horizon_days <= 31:
        raise PaperExecutionProducerError("horizon_days must be an integer between 1 and 31")
    evidence: list[dict[str, object]] = []
    for offset in range(horizon_days):
        candidate = target_date - timedelta(days=offset)
        projection, blocker = _calendar_evidence(
            market_db,
            target_date=candidate,
            calendar=calendar,
        )
        evidence.append(projection)
        if projection.get("is_trading_day") is True:
            return {
                "status": "ready",
                "date": candidate.isoformat(),
                "calendar": projection,
                "evidence": evidence,
                "reason": "latest_proven_official_session_on_or_before_decision_date",
            }
        # False is a proven closed day (weekend or official holiday), so it is
        # safe to continue backwards. Unknown cannot establish that no trading
        # session lies between the selected date and the decision date.
        if projection.get("is_trading_day") is None:
            return {
                "status": "blocked",
                "date": None,
                "calendar": projection,
                "evidence": evidence,
                "reason": blocker or "market_reference_session_unproven",
            }
    return {
        "status": "blocked",
        "date": None,
        "calendar": None,
        "evidence": evidence,
        "reason": "market_reference_session_not_found_in_bounded_horizon",
    }


def _reference_day_projection(
    target_date: date,
    market_db: Path,
    *,
    calendar: OfficialTradingCalendar | None,
) -> dict[str, object]:
    try:
        return latest_proven_market_session_on_or_before(
            target_date,
            market_db=market_db,
            calendar=calendar,
        )
    except Exception as error:  # noqa: BLE001 - status must remain structured
        return {
            "status": "blocked",
            "date": None,
            "calendar": None,
            "reason": f"market_reference_session_unproven:{type(error).__name__}:{error}",
        }


def _load_recommendation(path: Path, *, observed: datetime) -> _Recommendation:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PaperExecutionProducerError("paper recommendation source file is missing")
    raw = resolved.read_bytes()
    file_hash = _sha256_bytes(raw)
    try:
        payload_value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperExecutionProducerError("paper recommendation JSON is invalid") from error
    if not isinstance(payload_value, Mapping):
        raise PaperExecutionProducerError("paper recommendation must be a JSON object")
    payload = {str(key): value for key, value in payload_value.items()}
    result_id = _required_text(payload.get("result_id"), "recommendation.result_id")
    created_at = _aware_datetime(payload.get("created_at"), "recommendation.created_at")
    if created_at > observed:
        raise PaperExecutionProducerError("recommendation created_at is after current wall clock")
    config_value = payload.get("config")
    if not isinstance(config_value, Mapping):
        raise PaperExecutionProducerError("recommendation.config is missing")
    config = {str(key): value for key, value in config_value.items()}
    safety_value = config.get("safety_boundary")
    if not isinstance(safety_value, Mapping):
        raise PaperExecutionProducerError("recommendation safety_boundary is missing")
    safety = {str(key): value for key, value in safety_value.items()}
    expected_false = ("confirm", "writes_evidence_db", "auto_trading", "lifecycle_action")
    if config.get("research_only") is not True:
        raise PaperExecutionProducerError("recommendation is not research_only")
    for field_name in expected_false:
        if safety.get(field_name) is not False:
            raise PaperExecutionProducerError(
                f"recommendation safety boundary is not disabled:{field_name}"
            )
    created_taipei_date = created_at.astimezone(TAIPEI).date()
    configured_date = _optional_date(config.get("decision_date"), "recommendation.config.decision_date")
    decision_date = configured_date or created_taipei_date
    if decision_date != created_taipei_date:
        raise PaperExecutionProducerError(
            "recommendation decision_date does not match created_at natural date"
        )
    observed_taipei_date = observed.astimezone(TAIPEI).date()
    if decision_date > observed_taipei_date:
        raise PaperExecutionProducerError(
            "recommendation is for a future natural day"
        )
    rows_value = payload.get("recommendations")
    if not isinstance(rows_value, list) or not rows_value:
        raise PaperExecutionProducerError("recommendation contains no candidates")
    max_positions = _positive_int(config.get("top_n"), "recommendation.config.top_n", default=8)
    max_positions = min(max_positions, 8)
    candidates: list[PortfolioConstructionCandidate] = []
    seen: set[str] = set()
    for raw_row in rows_value[:max_positions]:
        if not isinstance(raw_row, Mapping):
            raise PaperExecutionProducerError("recommendation row is invalid")
        symbol = _stock_code(raw_row.get("證券代號"))
        if symbol in seen:
            raise PaperExecutionProducerError(f"recommendation symbol is duplicated:{symbol}")
        seen.add(symbol)
        row_date = _optional_date(raw_row.get("eligible_universe_date"), "recommendation row date")
        if row_date is not None and row_date != decision_date:
            raise PaperExecutionProducerError(
                f"recommendation row is outside decision date:{symbol}"
            )
        score = _finite_decimal(raw_row.get("總分"), f"recommendation score:{symbol}")
        if score < 0 or score > Decimal("100"):
            raise PaperExecutionProducerError(f"recommendation score is outside 0..100:{symbol}")
        reference = _finite_decimal(
            raw_row.get("收盤價"),
            f"recommendation reference price:{symbol}",
        ).quantize(MONEY_QUANTUM)
        if reference <= 0:
            raise PaperExecutionProducerError(f"recommendation reference price is invalid:{symbol}")
        candidates.append(
            PortfolioConstructionCandidate(
                stock_code=symbol,
                stock_name=str(raw_row.get("證券名稱") or "").strip() or symbol,
                score_bp=int((score * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)),
                reference_price=reference,
                metadata={"sector": str(raw_row.get("產業") or "")},
            )
        )
    if not candidates:
        raise PaperExecutionProducerError("recommendation has no usable candidate")
    content_hash = _payload_hash(payload)
    portfolio_value = config.get("portfolio_id", PAPER_PORTFOLIO_ID)
    portfolio_id = _required_text(portfolio_value, "recommendation.config.portfolio_id")
    if portfolio_id != PAPER_PORTFOLIO_ID:
        raise PaperExecutionProducerError(
            "recommendation portfolio identity is not supported:" + portfolio_id
        )
    profile_id = config.get("profile_id")
    profile_text = None if profile_id is None else str(profile_id)
    config_projection: dict[str, object] = {
        "research_only": True,
        "safety_boundary": {field: False for field in expected_false},
        "portfolio_id": portfolio_id,
        "profile_id": profile_text,
        "configured_decision_date": decision_date.isoformat(),
        "formal_credit": False,
        "source_result_id": result_id,
    }
    return _Recommendation(
        path=resolved,
        file_hash=file_hash,
        content_hash=content_hash,
        result_id=result_id,
        portfolio_id=portfolio_id,
        profile_id=profile_text,
        created_at=created_at,
        decision_date=decision_date,
        candidates=tuple(candidates),
        raw_count=len(rows_value),
        config_projection=config_projection,
    )


def _load_clock_projection(path: Path, *, decision_date: date) -> dict[str, object]:
    """讀取既有 clock 作 lineage；不把 Paper profile 升格為 Formal。"""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PaperExecutionProducerError("optional formal clock manifest is missing")
    raw = resolved.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise PaperExecutionProducerError("optional formal clock manifest is invalid") from error
    if not isinstance(value, Mapping):
        raise PaperExecutionProducerError("optional formal clock manifest must be an object")
    payload = {str(key): item for key, item in value.items()}
    activation = _strict_date(
        payload.get("activation_trading_day"),
        "clock.activation_trading_day",
    )
    if activation > decision_date:
        raise PaperExecutionProducerError("clock activation day is after Paper decision date")
    for field_name in ("historical_backfill_claimed", "real_money", "broker_execution"):
        if payload.get(field_name) is not False:
            raise PaperExecutionProducerError(
                f"clock safety boundary is invalid:{field_name}"
            )
    declared_hash = payload.get("manifest_hash")
    return {
        "path": str(resolved),
        "file_hash": _sha256_bytes(raw),
        "declared_manifest_hash": None if declared_hash is None else str(declared_hash),
        "clock_id": _required_text(payload.get("clock_id"), "clock.clock_id"),
        "activation_trading_day": activation.isoformat(),
        "strategy_version": payload.get("strategy_version"),
        "policy_version": payload.get("policy_version"),
        "formal_credit": False,
        "binding": "lineage_only_paper_profile_not_formal_authorization",
    }


def _load_prior_state(
    path: Path,
    *,
    execution_date: date,
    ledger_db: Path | None = None,
    allow_existing_execution_snapshot: bool = False,
) -> _State:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PaperExecutionProducerError("paper snapshot state DB is missing")
    before_hash = _file_sha256(resolved)
    uri = f"file:{resolved.as_posix()}?mode=ro"
    connection: sqlite3.Connection | None = None
    execution_snapshot_exists = False
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        _require_table_columns(
            connection,
            "paper_portfolio_snapshots",
            {"snapshot_id", "portfolio_id", "decision_date", "source_result_id", "cash", "total_value"},
        )
        _require_table_columns(
            connection,
            "paper_portfolio_positions",
            {"snapshot_id", "stock_code", "quantity", "mark_price", "market_value", "weight_bp"},
        )
        headers = connection.execute(
            "SELECT snapshot_id, portfolio_id, decision_date, source_result_id, cash, total_value "
            "FROM paper_portfolio_snapshots ORDER BY decision_date, snapshot_id"
        ).fetchall()
        if not headers:
            raise PaperExecutionProducerError("paper snapshot state DB is empty")
        parsed_headers: list[tuple[sqlite3.Row, date]] = []
        seen_dates: set[date] = set()
        for row in headers:
            row_date = _strict_date(row["decision_date"], "paper snapshot decision_date")
            if row_date in seen_dates:
                raise PaperExecutionProducerError(
                    f"paper snapshot has duplicate decision date:{row_date.isoformat()}"
                )
            seen_dates.add(row_date)
            parsed_headers.append((row, row_date))
        if any(row_date > execution_date for _, row_date in parsed_headers):
            raise PaperExecutionProducerError("paper snapshot contains a future decision date")
        execution_snapshot_exists = any(
            row_date == execution_date for _, row_date in parsed_headers
        )
        if execution_snapshot_exists and not allow_existing_execution_snapshot:
            raise PaperExecutionProducerError(
                "paper snapshot for execution date already exists; caller must explicitly permit append-only preopen reuse"
            )
        eligible = [(row, row_date) for row, row_date in parsed_headers if row_date < execution_date]
        if not eligible:
            raise PaperExecutionProducerError("paper snapshot has no prior natural-day state")
        row, row_date = eligible[-1]
        snapshot_id = _required_text(row["snapshot_id"], "paper snapshot.snapshot_id")
        portfolio_id = _required_text(row["portfolio_id"], "paper snapshot.portfolio_id")
        if portfolio_id != PAPER_PORTFOLIO_ID:
            raise PaperExecutionProducerError("paper snapshot portfolio identity is invalid")
        source_result_id = _required_text(row["source_result_id"], "paper snapshot.source_result_id")
        cash = _nonnegative_decimal(row["cash"], "paper snapshot.cash")
        total_value = _nonnegative_decimal(row["total_value"], "paper snapshot.total_value")
        position_rows = connection.execute(
            "SELECT stock_code, quantity, mark_price, market_value, weight_bp "
            "FROM paper_portfolio_positions WHERE snapshot_id = ? ORDER BY stock_code",
            (snapshot_id,),
        ).fetchall()
        positions: list[_Position] = []
        seen_symbols: set[str] = set()
        for item in position_rows:
            symbol = _stock_code(item["stock_code"])
            if symbol in seen_symbols:
                raise PaperExecutionProducerError(f"paper snapshot position duplicated:{symbol}")
            seen_symbols.add(symbol)
            quantity = _nonnegative_int(item["quantity"], "paper snapshot.quantity")
            mark_price = _nonnegative_decimal(item["mark_price"], "paper snapshot.mark_price")
            market_value = _nonnegative_decimal(item["market_value"], "paper snapshot.market_value")
            weight_bp = _nonnegative_int(item["weight_bp"], "paper snapshot.weight_bp")
            if weight_bp > 10000:
                raise PaperExecutionProducerError("paper snapshot.weight_bp is outside 0..10000")
            positions.append(
                _Position(
                    stock_code=symbol,
                    quantity=quantity,
                    mark_price=mark_price,
                    market_value=market_value,
                )
            )
        expected_total = quantize_money(cash + sum((item.market_value for item in positions), Decimal("0")))
        if quantize_money(total_value) != expected_total:
            raise PaperExecutionProducerError("paper snapshot cash and positions do not reconcile")
        state_payload: dict[str, object] = {
            "snapshot_id": snapshot_id,
            "portfolio_id": portfolio_id,
            "decision_date": row_date.isoformat(),
            "source_result_id": source_result_id,
            "cash": str(cash),
            "total_value": str(total_value),
            "positions": [
                {
                    "stock_code": item.stock_code,
                    "quantity": item.quantity,
                    "mark_price": str(item.mark_price),
                    "market_value": str(item.market_value),
                }
                for item in positions
            ],
        }
        connection.commit()
    except PaperExecutionProducerError:
        if connection is not None:
            connection.rollback()
        raise
    except sqlite3.Error as error:
        if connection is not None:
            connection.rollback()
        raise PaperExecutionProducerError(
            f"paper snapshot read failed:{type(error).__name__}:{error}"
        ) from error
    finally:
        if connection is not None:
            connection.close()
    after_hash = _file_sha256(resolved)
    if before_hash != after_hash:
        raise PaperExecutionProducerError("paper snapshot DB changed during read")
    effective_cash = cash
    effective_total = total_value
    effective_positions = tuple(positions)
    ledger_event_ids: tuple[str, ...] = ()
    ledger_projection: dict[str, object] | None = None
    if ledger_db is not None:
        (
            effective_cash,
            effective_total,
            effective_positions,
            ledger_event_ids,
            ledger_projection,
        ) = _apply_prior_paper_fills(
            ledger_db,
            portfolio_id=portfolio_id,
            after_date=row_date,
            before_date=execution_date,
            initial_cash=cash,
            initial_total=total_value,
            initial_positions=effective_positions,
        )
    state_payload = {
        "snapshot_id": snapshot_id,
        "portfolio_id": portfolio_id,
        "decision_date": row_date.isoformat(),
        "source_result_id": source_result_id,
        "cash": str(effective_cash),
        "total_value": str(effective_total),
        "positions": [
            {
                "stock_code": item.stock_code,
                "quantity": item.quantity,
                "mark_price": str(item.mark_price),
                "market_value": str(item.market_value),
            }
            for item in effective_positions
        ],
        "ledger_event_ids": list(ledger_event_ids),
        "ledger_projection": ledger_projection,
    }
    return _State(
        snapshot_id=snapshot_id,
        portfolio_id=portfolio_id,
        decision_date=row_date,
        source_result_id=source_result_id,
        cash=effective_cash,
        total_value=effective_total,
        positions=effective_positions,
        content_hash=_payload_hash(state_payload),
        file_hash=before_hash,
        ledger_event_ids=ledger_event_ids,
        execution_snapshot_exists=execution_snapshot_exists,
    )


def _apply_prior_paper_fills(
    path: Path,
    *,
    portfolio_id: str,
    after_date: date,
    before_date: date,
    initial_cash: Decimal,
    initial_total: Decimal,
    initial_positions: tuple[_Position, ...],
    exclude_fill_ids: frozenset[str] = frozenset(),
) -> tuple[
    Decimal,
    Decimal,
    tuple[_Position, ...],
    tuple[str, ...],
    dict[str, object] | None,
]:
    """將 snapshot 後、execution 前已 append 的 Paper fills 投影成期初狀態。

    Snapshot 是台北 08:30 的 preopen T-1 mark；成交事件是獨立的 T+1
    session-open transition。事件日與 snapshot 同日代表該日盤後追加的
    postfill transition，下一個 execution session 必須納入，因此下界是
    inclusive、上界是 exclusive。此 projection 只讀既有 ledger，讓下一個
    自然日不會重新以舊 snapshot 重複建立相同成交。沒有 ledger 檔案時保持原狀；
    有檔案但 schema／來源不受控時 fail closed。
    """

    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return initial_cash, initial_total, initial_positions, (), None
    if not resolved.is_file():
        raise PaperExecutionProducerError("paper fill ledger path is not a file")
    before_hash = _file_sha256(resolved)
    uri = f"file:{resolved.as_posix()}?mode=ro"
    connection: sqlite3.Connection | None = None
    rows: list[sqlite3.Row] = []
    columns: tuple[str, ...] = ()
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        columns = _table_columns(connection, "paper_trade_ledger")
        required = {
            "schema_version",
            "fill_id",
            "order_id",
            "portfolio_id",
            "event_date",
            "stock_code",
            "side",
            "requested_quantity",
            "filled_quantity",
            "reference_price",
            "fill_price",
            "commission",
            "tax",
            "slippage_cost",
            "turnover_bp",
            "execution_gap_bp",
            "status",
            "source_event_id",
            "override_reason",
            "source_type",
            "research_only",
            "broker_order_allowed",
            "auto_rebalance_allowed",
        }
        if not required.issubset(set(columns)):
            raise PaperExecutionProducerError(
                "paper fill ledger state projection schema is incomplete"
            )
        rows = connection.execute(
            "SELECT * FROM paper_trade_ledger "
            "WHERE portfolio_id = ? AND event_date >= ? AND event_date < ? "
            "ORDER BY event_date, fill_id",
            (portfolio_id, after_date.isoformat(), before_date.isoformat()),
        ).fetchall()
        connection.commit()
    except PaperExecutionProducerError:
        if connection is not None:
            connection.rollback()
        raise
    except sqlite3.Error as error:
        if connection is not None:
            connection.rollback()
        raise PaperExecutionProducerError(
            f"paper fill ledger read failed:{type(error).__name__}:{error}"
        ) from error
    finally:
        if connection is not None:
            connection.close()
    after_hash = _file_sha256(resolved)
    if before_hash != after_hash:
        raise PaperExecutionProducerError("paper fill ledger changed during read")

    cash = quantize_money(initial_cash)
    quantities = {item.stock_code: item.quantity for item in initial_positions}
    marks = {item.stock_code: item.mark_price for item in initial_positions}
    event_ids: list[str] = []
    for row in rows:
        fill = _paper_fill_from_row(row)
        if fill.fill_id in exclude_fill_ids:
            continue
        if fill.source_type not in {
            PAPER_EXECUTION_SOURCE_TYPE,
            *PAPER_EXECUTION_LEGACY_SOURCE_TYPES,
        }:
            raise PaperExecutionProducerError(
                "paper fill ledger has unsupported state transition source"
                f":{fill.source_type}"
            )
        event_date = _strict_date(fill.event_date, "paper fill ledger.event_date")
        if not after_date <= event_date < before_date:
            raise PaperExecutionProducerError("paper fill ledger event is outside state window")
        event_ids.append(fill.fill_id)
        if fill.filled_quantity == 0:
            continue
        if fill.filled_quantity % PAPER_BOARD_LOT != 0:
            raise PaperExecutionProducerError(
                f"paper fill is not board-lot aligned:{fill.fill_id}"
            )
        quantity = fill.filled_quantity
        current = quantities.get(fill.stock_code, 0)
        gross = fill.gross_amount
        # fill_price 已含 tick slippage；slippage_cost 僅作歸因，不能再次
        # 從現金結算扣除。實付現金是 gross + commission + tax。
        settlement_cost = fill.commission + fill.tax
        if fill.side == "buy":
            quantities[fill.stock_code] = current + quantity
            cash = quantize_money(cash - gross - settlement_cost)
        elif fill.side == "sell":
            if quantity > current:
                raise PaperExecutionProducerError(
                    f"paper fill sells more than projected holding:{fill.fill_id}"
                )
            quantities[fill.stock_code] = current - quantity
            cash = quantize_money(cash + gross - settlement_cost)
        else:  # pragma: no cover - PaperTradeFill validates this
            raise PaperExecutionProducerError("paper fill side is invalid")
        if fill.fill_price is not None:
            marks[fill.stock_code] = fill.fill_price
    if cash < Decimal("0"):
        raise PaperExecutionProducerError("paper fill ledger projection cash is negative")
    positions = tuple(
        _Position(
            stock_code=symbol,
            quantity=quantity,
            mark_price=marks[symbol],
            market_value=quantize_money(marks[symbol] * Decimal(quantity)),
        )
        for symbol, quantity in sorted(quantities.items())
        if quantity > 0
    )
    total = quantize_money(
        cash + sum((item.market_value for item in positions), Decimal("0"))
    )
    if total <= Decimal("0"):
        raise PaperExecutionProducerError("paper fill ledger projection total value is invalid")
    projection = {
        "path": str(resolved),
        "mode": "ro/query_only",
        "file_hash": before_hash,
        "after_snapshot_date": after_date.isoformat(),
        "before_execution_date": before_date.isoformat(),
        "event_count": len(event_ids),
        "event_ids": event_ids,
        "source_type": PAPER_EXECUTION_SOURCE_TYPE,
    }
    return cash, total, positions, tuple(event_ids), projection


def _apply_same_day_paper_fills(
    state: _State,
    *,
    ledger_db: Path | None,
    execution_date: date,
    exclude_fill_ids: frozenset[str],
) -> _State:
    """Project prior same-session fills into a retry's policy state.

    The normal snapshot projection intentionally stops before the execution
    date.  EOD policy evaluation has a stronger observation boundary: rows
    already persisted on that same date are available.  Exact rows belonging
    to the current recommendation are excluded by their deterministic fill
    identity so a retry remains idempotent; every other valid row changes the
    cash/position basis used by the next candidate.
    """

    if ledger_db is None or not ledger_db.exists():
        return state
    next_day = execution_date + timedelta(days=1)
    (
        cash,
        total,
        positions,
        event_ids,
        projection,
    ) = _apply_prior_paper_fills(
        ledger_db,
        portfolio_id=state.portfolio_id,
        after_date=execution_date,
        before_date=next_day,
        initial_cash=state.cash,
        initial_total=state.total_value,
        initial_positions=state.positions,
        exclude_fill_ids=exclude_fill_ids,
    )
    if not event_ids:
        return state
    all_event_ids = tuple((*state.ledger_event_ids, *event_ids))
    state_payload = {
        "snapshot_id": state.snapshot_id,
        "portfolio_id": state.portfolio_id,
        "decision_date": state.decision_date.isoformat(),
        "source_result_id": state.source_result_id,
        "cash": str(cash),
        "total_value": str(total),
        "positions": [
            {
                "stock_code": item.stock_code,
                "quantity": item.quantity,
                "mark_price": str(item.mark_price),
                "market_value": str(item.market_value),
            }
            for item in positions
        ],
        "ledger_event_ids": list(all_event_ids),
        "same_day_projection": projection,
    }
    return _State(
        snapshot_id=state.snapshot_id,
        portfolio_id=state.portfolio_id,
        decision_date=state.decision_date,
        source_result_id=state.source_result_id,
        cash=cash,
        total_value=total,
        positions=positions,
        content_hash=_payload_hash(state_payload),
        file_hash=state.file_hash,
        ledger_event_ids=all_event_ids,
        execution_snapshot_exists=state.execution_snapshot_exists,
    )


def _load_market(
    path: Path,
    *,
    reference_date: date,
    execution_date: date,
    symbols: Sequence[str],
    reference_prices: Mapping[str, Decimal],
) -> _Market:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PaperExecutionProducerError("paper market DB is missing")
    if not symbols:
        raise PaperExecutionProducerError("paper execution symbol universe is empty")
    before_hash = _file_sha256(resolved)
    if reference_date >= execution_date:
        raise PaperExecutionProducerError(
            "market reference date must be before execution date"
        )
    date_keys = tuple(
        dict.fromkeys(
            (
                reference_date.isoformat(),
                reference_date.strftime("%Y%m%d"),
                execution_date.isoformat(),
                execution_date.strftime("%Y%m%d"),
            )
        )
    )
    placeholders = ",".join("?" for _ in symbols)
    date_placeholders = ",".join("?" for _ in date_keys)
    uri = f"file:{resolved.as_posix()}?mode=ro"
    connection: sqlite3.Connection | None = None
    rows: list[dict[str, object]] = []
    prices: dict[str, Decimal] = {}
    volumes: dict[str, int] = {}
    prior_closes: dict[str, Decimal] = {}
    rows_by_date_symbol: dict[tuple[date, str], dict[str, object]] = {}
    columns: tuple[str, ...] = ()
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        columns = _table_columns(connection, "daily_prices")
        required = {"日期", "證券代號", "收盤價", "開盤價", "成交股數"}
        if not required.issubset(columns):
            raise PaperExecutionProducerError("daily_prices required columns are missing")
        selected = connection.execute(
            f'SELECT * FROM "daily_prices" WHERE "日期" IN ({date_placeholders}) '
            f'AND "證券代號" IN ({placeholders})',
            (*date_keys, *symbols),
        ).fetchall()
        date_index = columns.index("日期")
        symbol_index = columns.index("證券代號")
        close_index = columns.index("收盤價")
        open_index = columns.index("開盤價")
        volume_index = columns.index("成交股數")
        for row in selected:
            row_date = _strict_date(row[date_index], "daily_prices.日期")
            symbol = _stock_code(row[symbol_index])
            if row_date not in {reference_date, execution_date}:
                raise PaperExecutionProducerError("daily_prices row is outside T+1 source window")
            key = (row_date, symbol)
            if key in rows_by_date_symbol:
                raise PaperExecutionProducerError(
                    f"daily_prices has duplicate source row:{row_date.isoformat()}:{symbol}"
                )
            row_payload = {
                str(column): _json_scalar(row[index])
                for index, column in enumerate(columns)
            }
            rows_by_date_symbol[key] = row_payload
            if row_date == reference_date:
                liquidity_volume = _nonnegative_int(
                    row[volume_index],
                    f"daily_prices.reference_volume:{symbol}",
                )
                if liquidity_volume <= 0:
                    raise PaperExecutionProducerError(
                        f"daily_prices reference volume is unavailable:{symbol}"
                    )
                # 成交量上限只能使用 reference session 收盤前已可取得的量。
                # execution 日完整 EOD 成交股數在開盤時尚不存在，不能回看作為 cap。
                volumes[symbol] = liquidity_volume
                if symbol in reference_prices:
                    close = _finite_decimal(
                        row[close_index], f"daily_prices.reference_close:{symbol}"
                    ).quantize(MONEY_QUANTUM)
                    if close <= 0:
                        raise PaperExecutionProducerError(
                            f"daily_prices reference close is invalid:{symbol}"
                        )
                    prior_closes[symbol] = close
            if row_date == execution_date:
                opening = _finite_decimal(
                    row[open_index], f"daily_prices.open:{symbol}"
                ).quantize(MONEY_QUANTUM)
                if opening <= 0:
                    raise PaperExecutionProducerError(
                        f"daily_prices execution open is invalid:{symbol}"
                    )
                prices[symbol] = opening
        connection.commit()
    except PaperExecutionProducerError:
        if connection is not None:
            connection.rollback()
        raise
    except sqlite3.Error as error:
        if connection is not None:
            connection.rollback()
        raise PaperExecutionProducerError(
            f"paper market read failed:{type(error).__name__}:{error}"
        ) from error
    finally:
        if connection is not None:
            connection.close()
    after_hash = _file_sha256(resolved)
    if before_hash != after_hash:
        raise PaperExecutionProducerError("paper market DB changed during read")
    missing = sorted(set(symbols) - set(prices))
    if missing:
        raise PaperExecutionProducerError("daily_prices is missing execution-date open rows:" + ",".join(missing))
    missing_prior = sorted(set(reference_prices) - set(prior_closes))
    if missing_prior:
        raise PaperExecutionProducerError(
            "daily_prices is missing market-reference-date close rows:" + ",".join(missing_prior)
        )
    missing_liquidity = sorted(set(symbols) - set(volumes))
    if missing_liquidity:
        raise PaperExecutionProducerError(
            "daily_prices is missing market-reference-date liquidity rows:"
            + ",".join(missing_liquidity)
        )
    mismatched = sorted(
        symbol
        for symbol, expected in reference_prices.items()
        if symbol not in prior_closes
        or prior_closes[symbol] != expected.quantize(MONEY_QUANTUM)
    )
    if mismatched:
        raise PaperExecutionProducerError(
            "recommendation reference price does not match official market-reference-date close:"
            + ",".join(mismatched)
        )
    rows = [rows_by_date_symbol[key] for key in sorted(rows_by_date_symbol)]
    content = {
        "table": "daily_prices",
        "market_reference_date": reference_date.isoformat(),
        "execution_date": execution_date.isoformat(),
        "execution_price_field": "開盤價",
        "market_reference_price_field": "收盤價",
        "columns": list(columns),
        "rows": rows,
    }
    return _Market(
        date=execution_date,
        prices=prices,
        reference_date=reference_date,
        volumes=volumes,
        rows=tuple(rows),
        columns=columns,
        content_hash=_payload_hash(content),
        file_hash=before_hash,
    )


def _evaluate_policy_batch(
    *,
    paths: PaperExecutionPaths,
    state: _State,
    target: Mapping[str, int],
    prices: Mapping[str, Decimal],
    recommendation: _Recommendation,
    execution_date: date,
    calendar: OfficialTradingCalendar | None,
    policy: PaperPortfolioPolicyConfig,
) -> tuple[
    dict[str, int],
    dict[str, object],
    PaperPortfolioPolicyContext,
    PaperPortfolioPolicyBatchResult,
]:
    """在建立 fills 前以真 ledger／PIT sector／官方 calendar 評估整批 target。

    ``PaperPortfolioPolicyAdapter`` 是此 producer 的唯一政策入口。被政策拒絕
    的 target 會被固定回目前持倉，因此後續 execution builder 不會繞過
    weekly turnover、cooldown 或 sector gate；sell proceeds 與 sector exposure
    仍只由實際 fills 改變。
    """

    if paths.ledger_db is None:
        raise PaperExecutionProducerError(
            "paper policy ledger source is missing"
        )
    symbols = tuple(sorted(set(target) | {item.stock_code for item in state.positions}))
    sector_by_symbol, sector_source = _load_policy_sector_mapping(
        paths.sector_membership_path,
        expected_file_hash=paths.sector_membership_file_hash,
        as_of=recommendation.created_at,
        decision_date=recommendation.decision_date,
        symbols=symbols,
    )
    official_days, calendar_source = _policy_calendar_snapshot(
        paths.market_db,
        calendar=calendar,
        start_date=state.decision_date,
        end_date=execution_date,
    )
    current_weights = {
        item.stock_code: _amount_to_bp(
            item.market_value,
            state.total_value,
            field_name=f"current market value:{item.stock_code}",
        )
        for item in state.positions
        if item.quantity > 0
    }
    target_weights = {
        symbol: _amount_to_bp(
            prices[symbol] * Decimal(quantity),
            state.total_value,
            field_name=f"target market value:{symbol}",
        )
        for symbol, quantity in target.items()
        if quantity > 0
    }
    # Include zero targets so a held symbol can be explicitly evaluated as a
    # sell and cannot evade cooldown/sector policy by disappearing from a
    # recommendation.
    target_weights.update(
        {
            symbol: 0
            for symbol in symbols
            if symbol not in target_weights
        }
    )
    current_weights.update(
        {
            symbol: 0
            for symbol in symbols
            if symbol not in current_weights
        }
    )
    if sum(target_weights.values()) > 10_000:
        raise PaperExecutionProducerError(
            "paper policy target weights exceed 10000 bp"
        )
    target_position_count = sum(1 for quantity in target.values() if quantity > 0)
    if target_position_count > policy.max_positions:
        raise PaperExecutionProducerError(
            "paper policy max_positions exceeded:"
            f"{target_position_count}>{policy.max_positions}"
        )
    expected_fill_ids = _expected_execution_fill_ids(
        state=state,
        target=target,
        execution_date=execution_date,
        recommendation_hash=recommendation.content_hash,
    )
    context = PaperPortfolioPolicyContext(
        # EOD replay has a complete same-session ledger view.  The exact fill
        # identities for this recommendation are excluded so a retry evaluates
        # the same target idempotently; a different recommendation's same-day
        # fills remain policy evidence for turnover and cooldown.
        decision_date=execution_date,
        current_cash_bp=_amount_to_bp(
            state.cash,
            state.total_value,
            field_name="current cash",
        ),
        current_weights_bp=current_weights,
        sector_by_symbol=sector_by_symbol,
        official_trading_days=official_days,
        ledger_history_start=state.decision_date,
        official_calendar_coverage_start=state.decision_date,
        official_calendar_coverage_end=execution_date,
        official_calendar_source_hash=str(calendar_source["source_hash"]),
        official_calendar_complete=True,
        portfolio_id=state.portfolio_id,
        snapshot_id=state.snapshot_id,
        include_decision_date_rows=True,
        ignored_fill_ids=expected_fill_ids,
    )
    candidates = tuple(
        PaperPolicyCandidate(
            stock_code=symbol,
            current_weight_bp=current_weights[symbol],
            target_weight_bp=target_weights[symbol],
        )
        for symbol in symbols
    )
    batch = PaperPortfolioPolicyAdapter(
        paths.ledger_db,
        policy,
    ).evaluate_batch(context, candidates)
    if batch.status != "ready" or batch.state is None:
        blockers = ",".join(batch.blockers) or "policy_adapter_source_not_ready"
        raise PaperExecutionProducerError(
            f"paper policy adapter {batch.status}:{blockers}"
        )
    if len(batch.results) != len(candidates):
        raise PaperExecutionProducerError(
            "paper policy adapter returned incomplete batch results"
        )
    effective_target = dict(target)
    current_quantities = {item.stock_code: item.quantity for item in state.positions}
    for candidate, result in zip(candidates, batch.results):
        if result.status != "ready" or result.decision is None:
            blockers = ",".join(result.blockers) or "candidate_policy_result_not_ready"
            raise PaperExecutionProducerError(
                f"paper policy candidate {candidate.stock_code} {result.status}:{blockers}"
            )
        if result.decision.action is not PaperPortfolioAction.PAPER_TRADE_CANDIDATE:
            # A rejected/no-trade candidate must not be turned into a fill by
            # the lower-level liquidity/cash simulator.
            effective_target[candidate.stock_code] = current_quantities.get(
                candidate.stock_code,
                0,
            )
    adapter_projection = {
        "status": batch.status,
        "enforced": True,
        "consumer": (
            "app_module.paper_portfolio_policy_adapter."
            "PaperPortfolioPolicyAdapter.evaluate_batch"
        ),
        "decision_date": execution_date.isoformat(),
        "recommendation_freeze_at": recommendation.created_at.isoformat(),
        "sector_source": sector_source,
        "calendar_source": calendar_source,
        "ledger_source": {
            "path": str(paths.ledger_db.expanduser().resolve()),
            "mode": "ro/query_only",
            "ledger_history_start": state.decision_date.isoformat(),
            "portfolio_id": state.portfolio_id,
        },
        "context": {
            "current_cash_bp": context.current_cash_bp,
            "current_weights_bp": dict(sorted(current_weights.items())),
            "target_weights_bp": dict(sorted(target_weights.items())),
            "official_trading_days": [
                item.isoformat() for item in context.official_trading_days
            ],
            "official_calendar_source_hash": context.official_calendar_source_hash,
            "official_calendar_complete": context.official_calendar_complete,
            "snapshot_id": context.snapshot_id,
            "include_decision_date_rows": context.include_decision_date_rows,
            "ignored_fill_ids": list(context.ignored_fill_ids),
        },
        "policy": _policy_config_projection(policy),
        "cash_reservation_semantics": batch.cash_reservation_semantics,
        "sector_reservation_semantics": batch.sector_reservation_semantics,
        "results": [
            _policy_result_projection(candidate, result)
            for candidate, result in zip(candidates, batch.results)
        ],
        "ledger_state": {
            "weekly_turnover_used_bp": batch.state.weekly_turnover_used_bp,
            "future_rows_excluded": batch.state.future_rows_excluded,
            "last_trade_date_by_symbol": {
                symbol: item.isoformat()
                for symbol, item in sorted(
                    batch.state.last_trade_date_by_symbol.items()
                )
            },
            "trading_days_since_last_trade_by_symbol": dict(
                sorted(batch.state.trading_days_since_last_trade_by_symbol.items())
            ),
        },
        "target_quantities_before_policy": dict(sorted(target.items())),
        "target_quantities_after_policy": dict(sorted(effective_target.items())),
    }
    return effective_target, adapter_projection, context, batch


def _expected_execution_fill_ids(
    *,
    state: _State,
    target: Mapping[str, int],
    execution_date: date,
    recommendation_hash: str,
) -> tuple[str, ...]:
    """Return immutable fill identities that belong to this exact replay.

    A same-day retry must not consume its own already-appended rows as a new
    turnover/cooldown event.  The identity is derived from the same ordered
    current/target delta used by :func:`_build_fills`; any other recommendation
    hash therefore remains visible to the policy adapter.
    """

    current = {item.stock_code: item.quantity for item in state.positions}
    symbols = sorted(set(current) | set(target))
    prefix = recommendation_hash.replace("sha256:", "")[:16]
    fill_ids: list[str] = []
    for side in ("sell", "buy"):
        for symbol in symbols:
            before = current.get(symbol, 0)
            after = target.get(symbol, 0)
            if (side == "sell" and before <= after) or (
                side == "buy" and after <= before
            ):
                continue
            fill_ids.append(
                f"paper-execution:{execution_date.isoformat()}:{prefix}:"
                f"{symbol}:{side}"
            )
    return tuple(sorted(fill_ids))


def _load_policy_sector_mapping(
    path: Path | None,
    *,
    expected_file_hash: str | None,
    as_of: datetime,
    decision_date: date,
    symbols: Sequence[str],
) -> tuple[dict[str, str], dict[str, object]]:
    """讀取 hash 綁定的官方 accepted sector sidecar or PIT archive.

    An exact ``archive_manifest.json`` is consumed through the durable PIT
    archive custody oracle; a canonical sidecar uses the assembler validator.
    Rows outside the frozen recommendation instant are ignored.  A missing or
    conflicting as-of row remains an explicit source blocker; the
    recommendation's display ``產業`` field is never used as a fallback.
    """

    if path is None:
        raise PaperExecutionProducerError(
            "paper policy sector mapping source is missing"
        )
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise PaperExecutionProducerError(
            f"paper policy sector mapping source is missing:{resolved}"
        )
    if not _is_sha256(expected_file_hash):
        raise PaperExecutionProducerError(
            "paper policy sector mapping file hash is missing or invalid"
        )
    observed_file_hash = _file_sha256(resolved)
    if observed_file_hash != expected_file_hash:
        raise PaperExecutionProducerError(
            "paper policy sector mapping file hash mismatch"
        )
    archive_readback: dict[str, object] | None = None
    source_mode = "official_pit_sector_sidecar_ro_hash_bound"
    manifest_hash: str
    if resolved.name == "archive_manifest.json":
        # The scheduled caller passes an exact durable archive manifest.  The
        # archive consumer is the custody oracle; do not copy its publication
        # back to TEMP or trust producer-declared hashes as an allowlist.
        archive_root = resolved.parents[2]
        try:
            from ml_module.pit_archive_consumer import (  # noqa: PLC0415
                consume_pit_candidate_archive,
            )

            archive_readback = consume_pit_candidate_archive(
                archive_root=archive_root,
                manifest_path=resolved,
                expected_manifest_file_hash=observed_file_hash,
                decision_at=as_of,
            )
            raw_rows = archive_readback.get("rows")
            if not isinstance(raw_rows, list):
                raise PaperExecutionProducerError(
                    "paper policy archived sector rows are missing"
                )
            rows = tuple(
                item for item in raw_rows if isinstance(item, Mapping)
            )
            if len(rows) != len(raw_rows):
                raise PaperExecutionProducerError(
                    "paper policy archived sector row is invalid"
                )
            manifest_hash = _required_text(
                archive_readback.get("publication_content_hash"),
                "archive publication content hash",
            )
            source_mode = "official_pit_archive_manifest_ro_hash_bound"
        except PaperExecutionProducerError:
            raise
        except Exception as error:  # noqa: BLE001 - source boundary is fail closed
            raise PaperExecutionProducerError(
                "paper policy sector archive rejected:"
                f"{type(error).__name__}:{error}"
            ) from error
    else:
        try:
            from data_module.portfolio_ml_dataset_assembler import (  # noqa: PLC0415
                _load_sector_membership_sidecar,
            )

            rows, manifest_hash = _load_sector_membership_sidecar(resolved)
        except Exception as error:  # noqa: BLE001 - source boundary is fail closed
            raise PaperExecutionProducerError(
                "paper policy sector mapping sidecar rejected:"
                f"{type(error).__name__}:{error}"
            ) from error
    if _file_sha256(resolved) != observed_file_hash:
        raise PaperExecutionProducerError(
            "paper policy sector mapping changed during read"
        )
    by_symbol: dict[str, list[tuple[datetime, date, date | None, str, str]]] = {}
    selected_source_ids: set[str] = set()
    freeze = _aware_datetime(as_of, "recommendation.created_at").astimezone(timezone.utc)
    for row in rows:
        if not isinstance(row, Mapping):  # pragma: no cover - assembler guard
            raise PaperExecutionProducerError(
                "paper policy sector mapping row is invalid"
            )
        status = row.get("status")
        if status != "accepted":
            raise PaperExecutionProducerError(
                "paper policy sector mapping contains non-accepted row"
            )
        try:
            symbol = _stock_code(row.get("symbol"))
            sector = _required_text(row.get("sector_id"), "sector membership.sector_id")
            source_id = _required_text(row.get("source_id"), "sector membership.source_id")
            available_at = _aware_datetime(
                row.get("available_at"),
                "sector membership.available_at",
            ).astimezone(timezone.utc)
            effective_from = _strict_date(
                row.get("effective_from"),
                "sector membership.effective_from",
            )
            effective_to = _optional_date(
                row.get("effective_to"),
                "sector membership.effective_to",
            )
        except (PaperExecutionProducerError, ValueError) as error:
            raise PaperExecutionProducerError(
                f"paper policy sector mapping row rejected:{error}"
            ) from error
        # Official PIT producer identities are explicit; a free-form display
        # industry or a historical self-description cannot authorize policy.
        if not source_id.casefold().startswith("official:"):
            continue
        if available_at > freeze:
            continue
        if effective_from > decision_date:
            continue
        if effective_to is not None and effective_to < decision_date:
            continue
        by_symbol.setdefault(symbol, []).append(
            (available_at, effective_from, effective_to, sector, source_id)
        )
    result: dict[str, str] = {}
    for symbol in symbols:
        candidates = by_symbol.get(symbol, [])
        if not candidates:
            continue
        latest_key = max((item[0], item[1]) for item in candidates)
        latest = [item for item in candidates if (item[0], item[1]) == latest_key]
        sectors = {item[3] for item in latest}
        if len(sectors) != 1:
            raise PaperExecutionProducerError(
                f"paper policy sector mapping is ambiguous:{symbol}"
            )
        result[symbol] = next(iter(sectors))
        selected_source_ids.update(item[4] for item in latest)
    missing = sorted(set(symbols) - set(result))
    if missing:
        raise PaperExecutionProducerError(
            "paper policy sector mapping missing as-of recommendation freeze:"
            + ",".join(missing)
        )
    source_projection: dict[str, object] = {
        "path": str(resolved),
        "mode": source_mode,
        "file_hash": observed_file_hash,
        "canonical_manifest_hash": manifest_hash,
        "as_of": freeze.isoformat(),
        "effective_date": decision_date.isoformat(),
        "rows_read": len(rows),
        "selected_symbols": list(sorted(result)),
        "source_ids": sorted(selected_source_ids),
        "official_source_required": True,
        "display_industry_fallback_allowed": False,
    }
    if archive_readback is not None:
        source_projection.update(
            {
                "archive_root": str(archive_root),
                "archive_manifest_hash": archive_readback.get(
                    "archive_manifest_hash"
                ),
                "archive_id": archive_readback.get("archive_id"),
                "archive_producer_code_sha256": archive_readback.get(
                    "producer_code_sha256"
                ),
                "archive_current_code_hash_match": archive_readback.get(
                    "current_code_hash_match"
                ),
                "archive_code_hash_compatibility": archive_readback.get(
                    "code_hash_compatibility"
                ),
                "archive_legacy_code_hash_compatibility_verified": (
                    archive_readback.get("legacy_code_hash_compatibility_verified")
                ),
                "captured_at": archive_readback.get("captured_at"),
                "available_at": archive_readback.get("available_at"),
                "archived_at": archive_readback.get("archived_at"),
                "archive_consumer": (
                    "ml_module.pit_archive_consumer.consume_pit_candidate_archive"
                ),
                "archive_source_custody_verified": archive_readback.get(
                    "source_custody_verified"
                ),
                "archive_rows_rebuilt_from_raw": archive_readback.get(
                    "rows_rebuilt_from_raw"
                ),
            }
        )
    return result, source_projection


def _policy_calendar_snapshot(
    market_db: Path,
    *,
    calendar: OfficialTradingCalendar | None,
    start_date: date,
    end_date: date,
) -> tuple[tuple[date, ...], dict[str, object]]:
    """建立 adapter 所需的 bounded official calendar coverage。"""

    if end_date < start_date:
        raise PaperExecutionProducerError(
            "paper policy calendar coverage range is invalid"
        )
    evidence_rows: list[dict[str, object]] = []
    trading_days: list[date] = []
    cursor = start_date
    service = calendar or OfficialTradingCalendar(db_path=market_db)
    while cursor <= end_date:
        evidence, _ = _calendar_evidence(
            market_db,
            target_date=cursor,
            calendar=service,
        )
        status = evidence.get("is_trading_day")
        if status is None:
            raise PaperExecutionProducerError(
                "paper policy official calendar unknown:"
                f"{cursor.isoformat()}"
            )
        if status is True:
            trading_days.append(cursor)
        evidence_rows.append(evidence)
        cursor += timedelta(days=1)
    if end_date not in trading_days:
        raise PaperExecutionProducerError(
            "paper policy execution date is not an official trading day:"
            + end_date.isoformat()
        )
    source_hash = _payload_hash(
        {
            "provider": "data_module.official_trading_calendar.OfficialTradingCalendar",
            "coverage_start": start_date.isoformat(),
            "coverage_end": end_date.isoformat(),
            "dates": evidence_rows,
        }
    )
    return tuple(trading_days), {
        "provider": "data_module.official_trading_calendar.OfficialTradingCalendar",
        "mode": "bounded_official_calendar_evidence",
        "coverage_start": start_date.isoformat(),
        "coverage_end": end_date.isoformat(),
        "trading_days": [item.isoformat() for item in trading_days],
        "dates": evidence_rows,
        "source_hash": source_hash,
        "complete": True,
        "lookahead_allowed": False,
    }


def _amount_to_bp(amount: Decimal, total_value: Decimal, *, field_name: str) -> int:
    """將 Decimal 金額保守轉成整數 bp，不用 binary float。"""

    if (
        not isinstance(amount, Decimal)
        or not amount.is_finite()
        or amount < 0
        or not isinstance(total_value, Decimal)
        or not total_value.is_finite()
        or total_value <= 0
    ):
        raise PaperExecutionProducerError(f"{field_name} cannot be converted to bp")
    value = (amount * BPS_DENOMINATOR / total_value).to_integral_value(
        rounding=ROUND_FLOOR
    )
    if value < 0 or value > BPS_DENOMINATOR:
        raise PaperExecutionProducerError(f"{field_name} bp is outside 0..10000")
    return int(value)


def _policy_config_projection(policy: PaperPortfolioPolicyConfig) -> dict[str, object]:
    payload = asdict(policy)
    payload["initial_capital"] = str(policy.initial_capital)
    return payload


def _policy_result_projection(
    candidate: PaperPolicyCandidate,
    result: PaperPortfolioPolicyAdapterResult,
) -> dict[str, object]:
    decision = result.decision
    return {
        "stock_code": candidate.stock_code,
        "current_weight_bp": candidate.current_weight_bp,
        "target_weight_bp": candidate.target_weight_bp,
        "status": result.status,
        "blockers": list(result.blockers),
        "action": None if decision is None else decision.action.value,
        "weight_gap_bp": None if decision is None else decision.weight_gap_bp,
        "estimated_round_trip_cost_bp": (
            None if decision is None else decision.estimated_round_trip_cost_bp
        ),
        "reasons": [] if decision is None else list(decision.reasons),
        "reservation_weekly_turnover_used_bp": (
            result.reservation_weekly_turnover_used_bp
        ),
        "projected_sector_weight_after_bp": (
            result.projected_sector_weight_after_bp
        ),
    }


def _reconcile_policy_after_fills(
    *,
    state: _State,
    target: Mapping[str, int],
    fills: Sequence[PaperTradeFill],
    projection: Mapping[str, object],
    policy_context: PaperPortfolioPolicyContext,
    policy_batch: PaperPortfolioPolicyBatchResult,
    policy: PaperPortfolioPolicyConfig,
) -> dict[str, object]:
    """以實際 filled quantity 重算 policy invariants。

    這個檢查發生在 liquidity/cash simulator 之後，故 partial 或 rejected
    sell 不會釋放預期現金或 sector exposure。它同時在 candidate-only 與
    explicit append 前執行；append 後再由 adapter 做 ledger readback。
    """

    if policy_batch.state is None:
        raise PaperExecutionProducerError("paper policy state is missing after batch")
    expected_cash = quantize_money(state.cash)
    actual_turnover = 0
    fills_by_symbol: dict[str, list[PaperTradeFill]] = {}
    for fill in fills:
        fills_by_symbol.setdefault(fill.stock_code, []).append(fill)
        if fill.status in {"filled", "partially_filled"}:
            if fill.filled_quantity <= 0 or fill.turnover_bp is None:
                raise PaperExecutionProducerError(
                    f"paper policy actual fill is incomplete:{fill.fill_id}"
                )
            actual_turnover += fill.turnover_bp
            settlement = fill.commission + fill.tax
            if fill.side == "sell":
                expected_cash = quantize_money(
                    expected_cash + fill.gross_amount - settlement
                )
            elif fill.side == "buy":
                expected_cash = quantize_money(
                    expected_cash - fill.gross_amount - settlement
                )
            else:  # pragma: no cover - PaperTradeFill validates this
                raise PaperExecutionProducerError("paper policy fill side is invalid")
        elif fill.filled_quantity != 0:
            raise PaperExecutionProducerError(
                f"paper policy rejected fill has quantity:{fill.fill_id}"
            )
    cash_after = _projection_decimal(projection, "cash_after")
    if cash_after != expected_cash:
        raise PaperExecutionProducerError(
            "paper policy actual cash reconciliation mismatch"
        )
    reserve = quantize_money(
        state.total_value * Decimal(policy.minimum_cash_bp) / BPS_DENOMINATOR
    )
    if cash_after < reserve:
        raise PaperExecutionProducerError(
            f"paper policy actual cash reserve not met:{cash_after}<{reserve}"
        )
    previous_turnover = policy_batch.state.weekly_turnover_used_bp
    if previous_turnover + actual_turnover > policy.weekly_turnover_cap_bp:
        raise PaperExecutionProducerError(
            "paper policy actual weekly turnover cap exceeded:"
            f"{previous_turnover}+{actual_turnover}>{policy.weekly_turnover_cap_bp}"
        )
    reported_turnover = projection.get("turnover_bp")
    if reported_turnover != actual_turnover:
        raise PaperExecutionProducerError(
            "paper policy actual turnover projection mismatch"
        )
    raw_positions = projection.get("positions")
    if not isinstance(raw_positions, list):
        raise PaperExecutionProducerError("paper policy post positions are missing")
    post_total = _projection_decimal(projection, "total_value_after_mark")
    sector_weights: dict[str, int] = {}
    position_rows: list[dict[str, object]] = []
    position_total = Decimal("0.00")
    for raw in raw_positions:
        if not isinstance(raw, Mapping):
            raise PaperExecutionProducerError("paper policy post position is invalid")
        symbol = _stock_code(raw.get("stock_code"))
        quantity = _nonnegative_int(raw.get("quantity"), "paper post quantity")
        market_value = _finite_decimal(
            raw.get("market_value"),
            f"paper post market value:{symbol}",
        )
        if quantity <= 0 or market_value < 0:
            raise PaperExecutionProducerError("paper policy post position is invalid")
        position_total = quantize_money(position_total + market_value)
        sector = policy_context.sector_by_symbol.get(symbol)
        if not isinstance(sector, str) or not sector.strip():
            raise PaperExecutionProducerError(
                f"paper policy post sector mapping missing:{symbol}"
            )
        weight_bp = _amount_to_bp(
            market_value,
            post_total,
            field_name=f"post market value:{symbol}",
        )
        sector_weights[sector] = sector_weights.get(sector, 0) + weight_bp
        position_rows.append(
            {
                "stock_code": symbol,
                "quantity": quantity,
                "market_value": str(market_value),
                "weight_bp": weight_bp,
                "sector": sector,
            }
        )
    if quantize_money(cash_after + position_total) != post_total:
        raise PaperExecutionProducerError(
            "paper policy post total value reconciliation mismatch"
        )
    if any(weight > policy.max_sector_weight_bp for weight in sector_weights.values()):
        raise PaperExecutionProducerError(
            "paper policy actual sector cap exceeded"
        )
    return {
        "status": "passed",
        "enforced": True,
        "cash_before": str(state.cash),
        "cash_after": str(cash_after),
        "minimum_cash_reserve": str(reserve),
        "weekly_turnover_before_bp": previous_turnover,
        "actual_turnover_bp": actual_turnover,
        "weekly_turnover_after_bp": previous_turnover + actual_turnover,
        "weekly_turnover_cap_bp": policy.weekly_turnover_cap_bp,
        "sector_weights_after_bp": dict(sorted(sector_weights.items())),
        "max_sector_weight_bp": policy.max_sector_weight_bp,
        "positions_after": position_rows,
        "fills_by_symbol": {
            symbol: [
                {
                    "fill_id": fill.fill_id,
                    "side": fill.side,
                    "status": fill.status,
                    "requested_quantity": fill.requested_quantity,
                    "filled_quantity": fill.filled_quantity,
                }
                for fill in symbol_fills
            ]
            for symbol, symbol_fills in sorted(fills_by_symbol.items())
        },
        "cash_reservation_semantics": (
            "sell_proceeds_count_only_after_actual_fill_settlement"
        ),
        "sector_reservation_semantics": (
            "sell_exposure_count_only_after_actual_fill_readback"
        ),
        "execution_readback_verified": False,
        "target_quantities": dict(sorted(target.items())),
    }


def _projection_decimal(projection: Mapping[str, object], field_name: str) -> Decimal:
    value = projection.get(field_name)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise PaperExecutionProducerError(
            f"paper policy projection {field_name} is invalid"
        ) from error
    if not parsed.is_finite() or parsed < 0:
        raise PaperExecutionProducerError(
            f"paper policy projection {field_name} is invalid"
        )
    return quantize_money(parsed)


def _verify_policy_ledger_readback(
    path: Path,
    *,
    policy_context: PaperPortfolioPolicyContext,
    policy: PaperPortfolioPolicyConfig,
) -> dict[str, object]:
    result = PaperPortfolioPolicyAdapter(path, policy).inspect(policy_context)
    if result.status != "ready" or result.state is None:
        blockers = ",".join(result.blockers) or "ledger_policy_readback_not_ready"
        raise PaperExecutionProducerError(
            f"paper policy ledger readback {result.status}:{blockers}"
        )
    return {
        "status": result.status,
        "path": str(path.expanduser().resolve()),
        "mode": "ro/query_only",
        "ledger_rows_read": result.state.ledger_rows_read,
        "future_rows_excluded": result.state.future_rows_excluded,
        "ledger_rows_sha256": result.state.ledger_rows_sha256,
        "ledger_data_version": result.state.ledger_data_version,
        "weekly_turnover_used_bp": result.state.weekly_turnover_used_bp,
    }


def _build_target(
    recommendation: _Recommendation,
    *,
    capital_amount: Decimal,
) -> dict[str, int]:
    policy = PaperPortfolioPolicyConfig()
    result = PortfolioConstructionService().construct(
        PortfolioConstructionRequest(
            decision_date=recommendation.decision_date.isoformat(),
            capital_amount=capital_amount,
            allocation_method="score_weight",
            candidates=recommendation.candidates,
            max_position_weight_bp=policy.max_single_position_bp,
            lot_size=PAPER_BOARD_LOT,
        )
    )
    target: dict[str, int] = {}
    for row in result.allocations:
        shares = row.executable_shares
        if shares is None or isinstance(shares, bool) or not isinstance(shares, int) or shares < 0:
            raise PaperExecutionProducerError(
                f"portfolio construction returned invalid executable shares:{row.stock_code}"
            )
        target[row.stock_code] = shares
    return target


def _build_fills(
    *,
    state: _State,
    target: Mapping[str, int],
    prices: Mapping[str, Decimal],
    volumes: Mapping[str, int],
    execution_date: date,
    policy: PaperPortfolioPolicyConfig,
    recommendation_hash: str,
) -> tuple[tuple[PaperTradeFill, ...], dict[str, object]]:
    current = {item.stock_code: item.quantity for item in state.positions}
    symbols = sorted(set(current) | set(target))
    for symbol in symbols:
        if symbol not in prices:
            raise PaperExecutionProducerError(f"paper execution price is missing:{symbol}")
        if symbol not in volumes or (
            isinstance(volumes[symbol], bool)
            or not isinstance(volumes[symbol], int)
            or volumes[symbol] <= 0
        ):
            raise PaperExecutionProducerError(f"paper execution volume is missing:{symbol}")
        if (
            isinstance(prices[symbol], bool)
            or not isinstance(prices[symbol], Decimal)
            or not prices[symbol].is_finite()
            or prices[symbol] <= 0
        ):
            raise PaperExecutionProducerError(f"paper execution price is invalid:{symbol}")
        if current.get(symbol, 0) % PAPER_BOARD_LOT != 0:
            raise PaperExecutionProducerError(
                f"paper snapshot position is not board-lot aligned:{symbol}"
            )
        target_quantity = target.get(symbol, 0)
        if (
            isinstance(target_quantity, bool)
            or not isinstance(target_quantity, int)
            or target_quantity < 0
            or target_quantity % PAPER_BOARD_LOT != 0
        ):
            raise PaperExecutionProducerError(
                f"paper target is not board-lot aligned:{symbol}"
            )
    deltas: list[tuple[str, str, int]] = []
    for symbol in symbols:
        before = current.get(symbol, 0)
        after = target.get(symbol, 0)
        if before > after:
            deltas.append((symbol, "sell", before - after))
    for symbol in symbols:
        before = current.get(symbol, 0)
        after = target.get(symbol, 0)
        if after > before:
            deltas.append((symbol, "buy", after - before))
    fills: list[PaperTradeFill] = []
    cash = quantize_money(state.cash)
    reserve = quantize_money(
        state.total_value * Decimal(policy.minimum_cash_bp) / BPS_DENOMINATOR
    )
    total_turnover_bp = 0
    slippage = TaiwanStockTickSlippageModel(ticks=1)
    order_outcomes: list[dict[str, object]] = []
    post_quantities = dict(current)
    for symbol, side, quantity in deltas:
        volume_cap = (
            volumes[symbol] * PAPER_MAX_PARTICIPATION_BP // int(BPS_DENOMINATOR)
        )
        volume_cap = (volume_cap // PAPER_BOARD_LOT) * PAPER_BOARD_LOT
        reference = prices[symbol].quantize(MONEY_QUANTUM)
        fill_price = slippage.calculate_fill_price(reference, side)
        prefix = recommendation_hash.replace("sha256:", "")[:16]
        event_id = f"paper-execution:{execution_date.isoformat()}:{prefix}:{symbol}:{side}"
        cash_before = cash
        allowed_quantity = min(quantity, volume_cap)
        reason_parts: list[str] = []
        if volume_cap < quantity:
            reason_parts.append(
                "liquidity_cap_zero" if volume_cap == 0 else "liquidity_cap_partial"
            )

        filled_quantity = allowed_quantity
        if side == "buy" and filled_quantity > 0:
            affordable_quantity = _max_affordable_buy_quantity(
                max_quantity=filled_quantity,
                cash=cash,
                reserve=reserve,
                reference=reference,
                fill_price=fill_price,
                policy=policy,
                total_value=state.total_value,
            )
            if affordable_quantity < filled_quantity:
                filled_quantity = affordable_quantity
                reason_parts.append("cash_reserve_zero" if filled_quantity == 0 else "cash_reserve_partial")

        if filled_quantity == 0:
            status = "rejected"
            outcome_reason = ";".join(reason_parts) or "policy_rejected"
            gross = Decimal("0.00")
            commission = Decimal("0.00")
            tax = Decimal("0.00")
            slippage_cost = Decimal("0.00")
            execution_gap: int | None = None
            turnover = 0
            actual_fill_price: Decimal | None = None
        else:
            status = "filled" if filled_quantity == quantity else "partially_filled"
            outcome_reason = ";".join(reason_parts) or "filled_within_policy"
            (
                gross,
                commission,
                tax,
                slippage_cost,
                execution_gap,
                turnover,
            ) = _trade_financials(
                reference=reference,
                fill_price=fill_price,
                quantity=filled_quantity,
                side=side,
                policy=policy,
                total_value=state.total_value,
            )
            actual_fill_price = fill_price
            settlement_cost = commission + tax
            if side == "sell":
                cash = quantize_money(cash + gross - settlement_cost)
            else:
                cash = quantize_money(cash - gross - settlement_cost)
            if side == "buy" and cash < reserve:
                raise PaperExecutionProducerError(
                    f"paper execution minimum cash reserve not met:{cash}<{reserve}"
                )
            if side == "sell":
                post_quantities[symbol] = post_quantities.get(symbol, 0) - filled_quantity
            else:
                post_quantities[symbol] = post_quantities.get(symbol, 0) + filled_quantity
            total_turnover_bp += turnover

        remaining_quantity = quantity - filled_quantity
        if filled_quantity == 0 and side == "sell":
            post_quantities[symbol] = post_quantities.get(symbol, 0)
        fills.append(
            PaperTradeFill(
                fill_id=event_id,
                order_id=event_id.replace("paper-execution:", "paper-order:", 1),
                portfolio_id=state.portfolio_id,
                event_date=execution_date.isoformat(),
                stock_code=symbol,
                side=side,
                requested_quantity=quantity,
                filled_quantity=filled_quantity,
                reference_price=reference,
                fill_price=actual_fill_price,
                commission=commission,
                tax=tax,
                slippage_cost=slippage_cost,
                turnover_bp=turnover,
                execution_gap_bp=execution_gap,
                status=status,
                source_event_id=event_id,
                override_reason=outcome_reason,
                source_type=PAPER_EXECUTION_SOURCE_TYPE,
                research_only=True,
                broker_order_allowed=False,
                auto_rebalance_allowed=False,
            )
        )
        order_outcomes.append(
            {
                "fill_id": event_id,
                "stock_code": symbol,
                "side": side,
                "requested_quantity": quantity,
                "filled_quantity": filled_quantity,
                "remaining_quantity": remaining_quantity,
                "status": status,
                "reason": outcome_reason,
                "liquidity_cap_shares": volume_cap,
                "cash_before": str(cash_before),
                "cash_after": str(cash),
            }
        )
    post_positions = []
    for symbol in symbols:
        quantity = post_quantities.get(symbol, 0)
        if quantity <= 0:
            continue
        price = prices[symbol]
        market_value = quantize_money(price * Decimal(quantity))
        post_positions.append(
            {
                "stock_code": symbol,
                "quantity": quantity,
                "mark_price": str(price),
                "market_value": str(market_value),
            }
        )
    post_total = quantize_money(
        cash
        + sum(
            (Decimal(str(item["market_value"])) for item in post_positions),
            Decimal("0"),
        )
    )
    return tuple(fills), {
        "cash_before": str(state.cash),
        "cash_after": str(cash),
        "minimum_cash_reserve": str(reserve),
        "total_value_before": str(state.total_value),
        "total_value_after_mark": str(post_total),
        "positions": post_positions,
        "turnover_bp": total_turnover_bp,
        "order_outcomes": order_outcomes,
        "execution_policy": "sell_before_buy_partial_fill_decimal_costs",
        "cash_settlement_semantics": PAPER_CASH_SETTLEMENT_SEMANTICS,
        "cost_attribution_semantics": PAPER_COST_ATTRIBUTION_SEMANTICS,
        "execution_event": "next_official_session_open",
        "execution_price_field": "開盤價",
        "board_lot": PAPER_BOARD_LOT,
        "max_participation_bp": PAPER_MAX_PARTICIPATION_BP,
        "volume_cap_shares": {
            symbol: (volumes[symbol] * PAPER_MAX_PARTICIPATION_BP // int(BPS_DENOMINATOR) // PAPER_BOARD_LOT) * PAPER_BOARD_LOT
            for symbol in symbols
        },
        "snapshot_update": "deferred_to_next_natural_daily_snapshot",
    }


def _fill_candidate_records(
    fills: Sequence[PaperTradeFill],
    projection: Mapping[str, object],
) -> list[dict[str, object]]:
    """把 ledger fill 與委託級剩餘量／原因合併到 candidate artifact。"""

    raw_outcomes = projection.get("order_outcomes")
    if not isinstance(raw_outcomes, list):
        raise PaperExecutionProducerError("paper execution order outcomes are missing")
    outcomes: dict[str, Mapping[str, object]] = {}
    for raw in raw_outcomes:
        if not isinstance(raw, Mapping):
            raise PaperExecutionProducerError("paper execution order outcome is invalid")
        fill_id = raw.get("fill_id")
        if not isinstance(fill_id, str) or not fill_id or fill_id in outcomes:
            raise PaperExecutionProducerError("paper execution order outcome identity is invalid")
        outcomes[fill_id] = raw
    records: list[dict[str, object]] = []
    for fill in fills:
        outcome = outcomes.get(fill.fill_id)
        if outcome is None:
            raise PaperExecutionProducerError(
                f"paper execution order outcome is missing:{fill.fill_id}"
            )
        record = dict(fill.to_dict())
        record["remaining_quantity"] = outcome.get("remaining_quantity")
        record["execution_reason"] = outcome.get("reason")
        records.append(record)
    if len(records) != len(outcomes):
        raise PaperExecutionProducerError("paper execution order outcome count mismatch")
    return records


def _trade_financials(
    *,
    reference: Decimal,
    fill_price: Decimal,
    quantity: int,
    side: str,
    policy: PaperPortfolioPolicyConfig,
    total_value: Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal, int, int]:
    """計算實際 filled quantity 的 Decimal 成本與風險統計。"""

    gross = quantize_money(fill_price * Decimal(quantity))
    commission = calculate_fee(gross, policy.commission_bp_per_side)
    tax = (
        quantize_money(gross * Decimal(policy.sell_tax_bp) / BPS_DENOMINATOR)
        if side == "sell"
        else Decimal("0.00")
    )
    slippage_cost = quantize_money(
        abs(fill_price - reference) * Decimal(quantity)
    )
    execution_gap = int(
        ((fill_price - reference) * BPS_DENOMINATOR / reference).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    turnover = int(
        (reference * Decimal(quantity) * BPS_DENOMINATOR / total_value).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    if turnover < 0:
        raise PaperExecutionProducerError("paper execution turnover is invalid")
    return gross, commission, tax, slippage_cost, execution_gap, turnover


def _max_affordable_buy_quantity(
    *,
    max_quantity: int,
    cash: Decimal,
    reserve: Decimal,
    reference: Decimal,
    fill_price: Decimal,
    policy: PaperPortfolioPolicyConfig,
    total_value: Decimal,
) -> int:
    """找出不突破保留現金的最大整張買入量。"""

    lot_count = max_quantity // PAPER_BOARD_LOT
    low = 0
    high = lot_count
    while low < high:
        candidate_lots = (low + high + 1) // 2
        candidate_quantity = candidate_lots * PAPER_BOARD_LOT
        gross, commission, tax, slippage_cost, _, _ = _trade_financials(
            reference=reference,
            fill_price=fill_price,
            quantity=candidate_quantity,
            side="buy",
            policy=policy,
            total_value=total_value,
        )
        if cash - gross - commission - tax >= reserve:
            low = candidate_lots
        else:
            high = candidate_lots - 1
    return low * PAPER_BOARD_LOT


def _policy_projection(
    policy: PaperPortfolioPolicyConfig,
    target: Mapping[str, int],
    recommendation: _Recommendation,
) -> dict[str, object]:
    policy_payload = asdict(policy)
    policy_payload["initial_capital"] = str(policy.initial_capital)
    policy_payload.update(
        {
            "allocation_method": "score_weight",
            "lot_size": PAPER_BOARD_LOT,
            "target_quantities": dict(sorted(target.items())),
            "recommendation_result_id": recommendation.result_id,
            "formal_credit": False,
            "cooldown_policy": "enforced_by_paper_portfolio_policy_adapter",
        }
    )
    return {
        "policy": policy_payload,
        "policy_hash": _payload_hash(policy_payload),
    }


def _append_and_read_back(
    path: Path,
    fills: Sequence[PaperTradeFill],
) -> bool:
    """Append a batch once and verify it; return True for an exact replay.

    Deterministic fill IDs make a scheduler retry safe.  An exact existing batch
    is a successful idempotent readback; a partial or divergent batch remains a
    hard blocker and is never silently amended.
    """

    resolved = path.expanduser().resolve()
    if not fills:
        raise PaperExecutionProducerError("cannot append an empty Paper fill batch")
    if resolved.exists():
        existing = _read_ledger_rows(resolved, [fill.fill_id for fill in fills])
        if existing:
            if len(existing) != len(fills) or tuple(existing) != tuple(
                sorted(fills, key=lambda item: item.fill_id)
            ):
                raise PaperExecutionProducerError(
                    "paper ledger contains a partial or divergent generated fill batch"
                )
            return True
    # A preopen snapshot is the T-1 starting state.  The first EOD replay may
    # append its independent postfill transition even when that snapshot was
    # written earlier in the day; only a partial or divergent existing batch is
    # rejected above.
    PaperTradeLedgerRepository(resolved).append_many(fills)
    observed = _read_ledger_rows(resolved, [fill.fill_id for fill in fills])
    if len(observed) != len(fills):
        raise PaperExecutionProducerError("paper ledger append readback row count mismatch")
    for expected, actual in zip(sorted(fills, key=lambda item: item.fill_id), observed):
        if actual != expected:
            raise PaperExecutionProducerError(
                f"paper ledger append readback mismatch:{expected.fill_id}"
            )
    return False


def _paper_fill_from_row(row: sqlite3.Row) -> PaperTradeFill:
    """Hydrate one validated ledger row for read-only state/readback paths."""

    return PaperTradeFill(
        fill_id=str(row["fill_id"]),
        order_id=str(row["order_id"]),
        portfolio_id=str(row["portfolio_id"]),
        event_date=str(row["event_date"]),
        stock_code=str(row["stock_code"]),
        side=str(row["side"]),
        requested_quantity=int(row["requested_quantity"]),
        filled_quantity=int(row["filled_quantity"]),
        reference_price=Decimal(str(row["reference_price"])),
        fill_price=(None if row["fill_price"] is None else Decimal(str(row["fill_price"]))),
        commission=Decimal(str(row["commission"])),
        tax=Decimal(str(row["tax"])),
        slippage_cost=Decimal(str(row["slippage_cost"])),
        turnover_bp=(None if row["turnover_bp"] is None else int(row["turnover_bp"])),
        execution_gap_bp=(
            None if row["execution_gap_bp"] is None else int(row["execution_gap_bp"])
        ),
        status=str(row["status"]),
        source_event_id=str(row["source_event_id"]),
        override_reason=(None if row["override_reason"] is None else str(row["override_reason"])),
        source_type=str(row["source_type"]),
        research_only=bool(row["research_only"]),
        broker_order_allowed=bool(row["broker_order_allowed"]),
        auto_rebalance_allowed=bool(row["auto_rebalance_allowed"]),
    )


def _read_ledger_rows(path: Path, fill_ids: Sequence[str]) -> tuple[PaperTradeFill, ...]:
    if not path.is_file():
        return ()
    placeholders = ",".join("?" for _ in fill_ids)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            columns = _table_columns(connection, "paper_trade_ledger")
            required = {
                "fill_id", "order_id", "portfolio_id", "event_date", "stock_code", "side",
                "requested_quantity", "filled_quantity", "reference_price", "fill_price",
                "commission", "tax", "slippage_cost", "turnover_bp", "execution_gap_bp",
                "status", "source_event_id", "override_reason", "source_type",
                "research_only", "broker_order_allowed", "auto_rebalance_allowed",
            }
            if not required.issubset(columns):
                raise PaperExecutionProducerError("paper ledger readback schema is incomplete")
            rows = connection.execute(
                f'SELECT * FROM "paper_trade_ledger" WHERE fill_id IN ({placeholders}) ORDER BY fill_id',
                tuple(fill_ids),
            ).fetchall()
    except sqlite3.Error as error:
        raise PaperExecutionProducerError(
            f"paper ledger readback failed:{type(error).__name__}:{error}"
        ) from error
    return tuple(_paper_fill_from_row(row) for row in rows)


def _calendar_evidence(
    market_db: Path,
    *,
    target_date: date,
    calendar: OfficialTradingCalendar | None,
) -> tuple[dict[str, object], str | None]:
    service = calendar or OfficialTradingCalendar(db_path=market_db)
    try:
        online_day, online_reason = service.is_official_trading_day(target_date)
    except Exception as error:  # noqa: BLE001 - unknown remains blocked
        online_day, online_reason = None, f"calendar_exception:{type(error).__name__}:{error}"
    projection: dict[str, object] = {
        "target_date": target_date.isoformat(),
        "is_trading_day": online_day,
        "reason_code": online_reason,
        "online_probe_reason_code": online_reason,
        "fallback_evidence": None,
        "provider": "data_module.official_trading_calendar.OfficialTradingCalendar",
        "official_source_required": True,
    }
    evidence_method = getattr(service, "evidence_for", None)
    if callable(evidence_method):
        try:
            source_evidence = evidence_method(target_date)
        except Exception as error:  # noqa: BLE001 - source evidence remains unknown
            source_evidence = {
                "mode": "calendar_evidence_unavailable",
                "error": f"{type(error).__name__}:{error}",
            }
        if isinstance(source_evidence, Mapping):
            projection["source_evidence"] = dict(source_evidence)
    if online_day is None:
        try:
            offline_day, offline_reason = service.is_official_trading_day(
                target_date,
                allow_online_probe=False,
            )
        except TypeError:
            offline_day, offline_reason = None, "offline_probe_unsupported"
        except Exception as error:  # noqa: BLE001
            offline_day, offline_reason = None, f"offline_probe_exception:{type(error).__name__}:{error}"
        projection["fallback_evidence"] = {
            "is_trading_day": offline_day,
            "reason_code": offline_reason,
            "mode": "read_only_market_indices_date_evidence",
        }
        if offline_day is True:
            projection["is_trading_day"] = True
            projection["reason_code"] = offline_reason
    if projection.get("is_trading_day") is True:
        return projection, None
    return projection, "official_calendar_not_proven:" + str(projection["reason_code"])


def _prepare_output_root(
    path: Path,
    *,
    controlled_root: Path | None = None,
) -> Path:
    """建立一次性 candidate 目錄並驗證其寫入邊界。

    一般呼叫仍只允許新的 OS TEMP 目錄。正式排程若要保存 durable candidate，
    必須同時提供明確的 ``controlled_root``，且 target 必須是該 root 下新的
    直接子目錄；這避免環境變數把 writer 指到未知位置，也不會把既有目錄當成
    可覆寫的 candidate。
    """

    resolved = path.expanduser().resolve()
    if controlled_root is None:
        try:
            resolved.relative_to(Path(tempfile.gettempdir()).resolve())
        except ValueError as error:
            raise PaperExecutionProducerError(
                "paper execution output must be under OS TEMP"
            ) from error
    else:
        allowed = controlled_root.expanduser().resolve()
        try:
            relative = resolved.relative_to(allowed)
        except ValueError as error:
            raise PaperExecutionProducerError(
                "controlled paper execution output is outside its declared root"
            ) from error
        if len(relative.parts) != 1 or relative.name in {"", ".", ".."}:
            raise PaperExecutionProducerError(
                "controlled paper execution output must be a new direct child"
            )
        if resolved.parent != allowed:
            raise PaperExecutionProducerError(
                "controlled paper execution output parent does not match declared root"
            )
    if resolved.exists():
        if not resolved.is_dir() or any(resolved.iterdir()):
            raise PaperExecutionProducerError(
                "paper execution output must be a new empty directory"
            )
    else:
        resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _write_candidate(output_root: Path, payload: Mapping[str, object]) -> dict[str, object]:
    body = dict(payload)
    body["content_sha256"] = _payload_hash(body)
    path = output_root / "paper_execution_candidate.json"
    encoded = (_canonical_json(body) + "\n").encode("utf-8")
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise PaperExecutionProducerError("paper execution candidate already exists") from error
    return {
        **body,
        "candidate_path": str(path),
        "candidate_file_hash": _file_sha256(path),
    }


def _require_table_columns(
    connection: sqlite3.Connection,
    table: str,
    required: set[str],
) -> None:
    columns = set(_table_columns(connection, table))
    if not required.issubset(columns):
        raise PaperExecutionProducerError(
            f"{table} required columns are missing:" + ",".join(sorted(required - columns))
        )


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        raise PaperExecutionProducerError(f"table is missing:{table}")
    return tuple(str(row[1]) for row in rows)


def _producer_code_hash() -> str:
    return _sha256_bytes(Path(__file__).read_bytes())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != len("sha256:") + 64:
        return False
    if not value.startswith("sha256:"):
        return False
    return all(character in "0123456789abcdef" for character in value[7:].lower())


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _json_scalar(value: object) -> object:
    if isinstance(value, bytes):
        return {"encoding": "hex", "value": value.hex()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PaperExecutionProducerError(f"{field_name} must be ISO datetime") from error
    else:
        raise PaperExecutionProducerError(f"{field_name} must be timezone-aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PaperExecutionProducerError(f"{field_name} must include timezone")
    return parsed


def _strict_date(value: object, field_name: str) -> date:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError as error:
        raise PaperExecutionProducerError(f"{field_name} must be an ISO date") from error
    if parsed.isoformat() != text[:10]:
        raise PaperExecutionProducerError(f"{field_name} has a non-canonical date")
    return parsed


def _optional_date(value: object, field_name: str) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    return _strict_date(value, field_name)


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PaperExecutionProducerError(f"{field_name} is missing")
    return text


def _stock_code(value: object) -> str:
    text = _required_text(value, "stock_code")
    if not text.isdigit() or not 2 <= len(text) <= 6:
        raise PaperExecutionProducerError(f"stock_code is invalid:{text}")
    return text


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise PaperExecutionProducerError(f"{field_name} is missing")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise PaperExecutionProducerError(f"{field_name} is not Decimal") from error
    if not parsed.is_finite():
        raise PaperExecutionProducerError(f"{field_name} is not finite")
    return parsed


def _nonnegative_decimal(value: object, field_name: str) -> Decimal:
    parsed = _finite_decimal(value, field_name)
    if parsed < 0:
        raise PaperExecutionProducerError(f"{field_name} must be non-negative")
    return parsed


def _positive_int(value: object, field_name: str, *, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        raise PaperExecutionProducerError(f"{field_name} must be a positive integer")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise PaperExecutionProducerError(f"{field_name} must be a positive integer") from error
    if parsed <= 0:
        raise PaperExecutionProducerError(f"{field_name} must be a positive integer")
    return parsed


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise PaperExecutionProducerError(f"{field_name} must be a non-negative integer")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as error:
        raise PaperExecutionProducerError(f"{field_name} must be a non-negative integer") from error
    if parsed < 0:
        raise PaperExecutionProducerError(f"{field_name} must be a non-negative integer")
    return parsed


__all__ = [
    "PAPER_BOARD_LOT",
    "PAPER_EXECUTION_PRODUCER_VERSION",
    "PAPER_EXECUTION_RECEIPT_SCHEMA_VERSION",
    "PAPER_EXECUTION_PENDING_QUEUE_STATES",
    "PAPER_EXECUTION_LEGACY_PENDING_QUEUE_STATES",
    "PAPER_EXECUTION_TERMINAL_QUEUE_STATES",
    "PAPER_EXECUTION_SCHEMA_VERSION",
    "PAPER_EXECUTION_SOURCE_TYPE",
    "TAIWAN_EOD_REPLAY_AVAILABLE_AT",
    "PAPER_MAX_PARTICIPATION_BP",
    "PaperExecutionPaths",
    "PaperExecutionProducerError",
    "latest_proven_market_session_on_or_before",
    "next_proven_trading_day",
    "persist_operational_receipt",
    "resolve_pending_recommendation",
    "run_paper_execution_daily",
    "run_paper_execution_daily_from_queue",
]
