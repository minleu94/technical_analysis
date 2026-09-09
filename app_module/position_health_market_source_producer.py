"""建立每日 position-health 的 PIT condition 與 Decimal metrics 來源。

這個 producer 只讀取已由 data-update quick／freshness receipt 證明完成的
``technical_indicators`` 與 ``daily_prices``。它把同一個決策日、可得時間、
來源 receipt、SQLite selected rows 與 health baseline 綁在不可變的 derived
JSON；不寫市場 SQLite、不回寫 Paper／Formal，也不使用 UI cache。

這條來源是給 05:15 Pacific health/evidence lane 使用的 post-close
``decision_at``。它不是 08:30 Asia/Taipei 的 forward prediction source；
呼叫者必須把實際 health cutoff 傳入，provider 仍會拒絕未來的
``available_at``。沒有已驗證 stable position identity 的 row 會保留在
``unresolved_identity_codes``，不把 stock code 猜成 position identity。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any

from app_module.portfolio_condition_monitor import (
    PortfolioConditionResult,
    PortfolioCurrentSnapshot,
)
from app_module.position_health_source_providers import (
    CONDITION_SOURCE_SCHEMA_VERSION,
    METRICS_SOURCE_SCHEMA_VERSION,
)


UTC = timezone.utc
SOURCE_VERSION = "position-health-market-source.v1"
SOURCE_ID_PREFIX = "twstock:technical_indicators_daily_prices"
_DECIMAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("close_price", "close_price"),
    ("open_price", "open_price"),
    ("high_price", "high_price"),
    ("low_price", "low_price"),
    ("volume", "volume"),
    ("rsi", "rsi"),
    ("macd", "macd"),
    ("macd_signal", "macd_signal"),
    ("macd_hist", "macd_hist"),
    ("ma5", "ma5"),
    ("ma10", "ma10"),
    ("ma20", "ma20"),
    ("ma60", "ma60"),
    ("atr", "atr"),
    ("adx", "adx"),
)


class PositionHealthMarketSourceError(ValueError):
    """Input custody or selected market rows cannot be trusted."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical(value))


def _parse_date(value: object, field_name: str) -> date:
    text = str(value or "").strip()
    try:
        if len(text) == 8 and text.isdigit():
            parsed = date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        else:
            parsed = date.fromisoformat(text[:10])
    except ValueError as exc:
        raise PositionHealthMarketSourceError(f"{field_name}_invalid") from exc
    if text.isdigit() and len(text) == 8:
        normalised = parsed.strftime("%Y%m%d")
    else:
        normalised = parsed.isoformat()
    if normalised != text[:10] and normalised != text:
        raise PositionHealthMarketSourceError(f"{field_name}_invalid")
    return parsed


def _parse_aware(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise PositionHealthMarketSourceError(f"{field_name}_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PositionHealthMarketSourceError(f"{field_name}_must_be_timezone_aware")
    return parsed.astimezone(UTC)


def _decimal(value: object, field_name: str) -> Decimal:
    if value is None or value == "":
        raise PositionHealthMarketSourceError(f"{field_name}_missing")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PositionHealthMarketSourceError(f"{field_name}_invalid") from exc
    if not parsed.is_finite():
        raise PositionHealthMarketSourceError(f"{field_name}_non_finite")
    return parsed


def _read_json(path: Path, field_name: str) -> tuple[dict[str, Any], str]:
    try:
        before = path.read_bytes()
        payload = json.loads(before.decode("utf-8-sig"))
        after = path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PositionHealthMarketSourceError(f"{field_name}_unreadable") from exc
    if before != after:
        raise PositionHealthMarketSourceError(f"{field_name}_changed_during_read")
    if not isinstance(payload, Mapping):
        raise PositionHealthMarketSourceError(f"{field_name}_must_be_object")
    return dict(payload), _sha256_bytes(before)


def _stat_token(path: Path) -> dict[str, int]:
    try:
        stat = path.stat()
    except OSError as exc:
        raise PositionHealthMarketSourceError("market_db_stat_failed") from exc
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _date_key(value: object) -> str:
    return _parse_date(value, "date").strftime("%Y%m%d")


def _source_row_code(value: object) -> str:
    return str(value or "").strip()


def _write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_create_only(path: Path, raw: bytes) -> str:
    """Atomically create a file without ever replacing an existing payload.

    A temporary file plus a same-volume hard-link gives us an atomic
    create-only claim on Windows/NTFS.  The caller can distinguish a race that
    wrote identical bytes from a conflict that must receive a new immutable
    filename.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            try:
                existing = path.read_bytes()
            except OSError as exc:
                raise PositionHealthMarketSourceError(
                    "immutable_artifact_existing_read_failed"
                ) from exc
            return "same" if existing == raw else "conflict"
        return "created"
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_hashed(path: Path, body: Mapping[str, Any]) -> tuple[Path, str, str]:
    encoded_body = _canonical(dict(body))
    payload = {**dict(body), "content_sha256": _sha256_bytes(encoded_body)}
    encoded = _canonical(payload) + b"\n"
    dated = path
    outcome = _write_create_only(dated, encoded)
    if outcome == "conflict":
        suffix = hashlib.sha256(encoded).hexdigest()[:16]
        dated = dated.with_name(f"{dated.stem}_{suffix}{dated.suffix}")
        outcome = _write_create_only(dated, encoded)
        if outcome == "conflict":
            raise PositionHealthMarketSourceError("immutable_artifact_hash_path_conflict")
    return dated, _sha256_bytes(encoded), payload["content_sha256"]


def _normalise_positions(payload: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    raw_positions = payload.get("positions")
    if not isinstance(raw_positions, list):
        raise PositionHealthMarketSourceError("health_baseline_positions_invalid")
    positions: list[dict[str, str]] = []
    unresolved: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in raw_positions:
        if not isinstance(raw, Mapping):
            raise PositionHealthMarketSourceError("health_baseline_position_not_object")
        code = _source_row_code(raw.get("stock_code"))
        if not code:
            raise PositionHealthMarketSourceError("health_baseline_stock_code_missing")
        shares_raw = raw.get("paper_shares")
        if shares_raw is None:
            raise PositionHealthMarketSourceError("health_baseline_shares_invalid")
        try:
            shares = int(str(shares_raw))
        except (TypeError, ValueError) as exc:
            raise PositionHealthMarketSourceError("health_baseline_shares_invalid") from exc
        if shares <= 0:
            continue
        position_id = _source_row_code(raw.get("position_id"))
        lineage_id = _source_row_code(raw.get("entry_lineage_id"))
        if not position_id or not lineage_id:
            unresolved.append(code)
            continue
        key = (position_id, lineage_id, code)
        if key in seen:
            raise PositionHealthMarketSourceError(f"health_baseline_position_duplicate:{code}")
        seen.add(key)
        positions.append(
            {
                "position_id": position_id,
                "entry_lineage_id": lineage_id,
                "stock_code": code,
            }
        )
    return positions, sorted(set(unresolved))


class PositionHealthMarketSourceProducer:
    """Produce condition and metrics artifacts from a verified daily market read."""

    def __init__(
        self,
        *,
        market_db_path: str | Path,
        quick_status_path: str | Path,
        freshness_status_path: str | Path,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.market_db_path = Path(market_db_path).expanduser().resolve()
        self.quick_status_path = Path(quick_status_path).expanduser().resolve()
        self.freshness_status_path = Path(freshness_status_path).expanduser().resolve()
        self.now_provider = now_provider or (lambda: datetime.now(UTC))

    def produce(
        self,
        *,
        baseline_path: str | Path,
        output_dir: str | Path,
        decision_date: str,
        decision_at: datetime | str | None = None,
        observed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        baseline = Path(baseline_path).expanduser().resolve()
        output = Path(output_dir).expanduser().resolve()
        decision = _parse_date(decision_date, "decision_date")
        requested_cutoff = (
            None if decision_at is None else _parse_aware(decision_at, "decision_at")
        )
        requested_observed = (
            None if observed_at is None else _parse_aware(observed_at, "observed_at")
        )
        if (
            requested_cutoff is not None
            and requested_observed is not None
            and requested_cutoff > requested_observed
        ):
            raise PositionHealthMarketSourceError("decision_at_after_observed_at")

        run_started = _parse_aware(
            self.now_provider(), "market_capture_started_at"
        )
        receipt_cutoff = requested_cutoff or requested_observed or run_started
        receipt_observed = requested_observed or run_started

        baseline_payload, baseline_hash = _read_json(baseline, "health_baseline")
        baseline_date = _parse_date(
            baseline_payload.get("decision_date") or baseline_payload.get("as_of_date"),
            "health_baseline_decision_date",
        )
        if baseline_date != decision:
            raise PositionHealthMarketSourceError("health_baseline_date_mismatch")
        positions, unresolved = _normalise_positions(baseline_payload)

        quick, quick_hash = _read_json(self.quick_status_path, "quick_status")
        freshness, freshness_hash = _read_json(self.freshness_status_path, "freshness_status")
        available_at, status_warnings = self._validate_receipts(
            quick,
            freshness,
            decision=decision,
            cutoff=receipt_cutoff,
            observed=receipt_observed,
        )

        # The upstream receipts are checked first.  Only then do we capture
        # the selected SQLite rows, so the derived source cannot bind a
        # pre-receipt or later replacement to an earlier cutoff.
        capture_started = _parse_aware(
            self.now_provider(), "market_capture_started_at"
        )
        if requested_cutoff is not None and capture_started > requested_cutoff:
            raise PositionHealthMarketSourceError(
                "market_capture_started_after_decision_cutoff"
            )
        if requested_observed is not None and capture_started > requested_observed:
            raise PositionHealthMarketSourceError(
                "market_capture_started_after_observed_at"
            )

        rows, db_binding = self._read_market_rows(
            codes=tuple(item["stock_code"] for item in positions),
            decision=decision,
        )
        capture_completed = _parse_aware(
            self.now_provider(), "market_capture_completed_at"
        )
        if requested_cutoff is not None and capture_completed > requested_cutoff:
            raise PositionHealthMarketSourceError(
                "market_capture_completed_after_decision_cutoff"
            )
        if requested_observed is not None and capture_completed > requested_observed:
            raise PositionHealthMarketSourceError(
                "market_capture_completed_after_observed_at"
            )
        cutoff = requested_cutoff or requested_observed or capture_completed
        observed = requested_observed or capture_completed
        selected_codes = {str(row["stock_code"]) for row in rows}
        missing_codes = sorted(
            {item["stock_code"] for item in positions} - selected_codes
        )
        source_id = f"{SOURCE_ID_PREFIX}:{decision.strftime('%Y%m%d')}"
        source_binding = {
            "schema_version": SOURCE_VERSION,
            "source_id": source_id,
            "decision_date": decision.isoformat(),
            "upstream_receipt_available_at": available_at.isoformat(),
            "available_at": capture_completed.isoformat(),
            "decision_cutoff_at": cutoff.isoformat(),
            "market_capture_started_at": capture_started.isoformat(),
            "market_capture_completed_at": capture_completed.isoformat(),
            "baseline_sha256": baseline_hash,
            "quick_status_sha256": quick_hash,
            "freshness_status_sha256": freshness_hash,
            "market_db": db_binding,
            "selected_rows": rows,
        }
        source_hash = _sha256_json(source_binding)

        rows_by_code = {str(row["stock_code"]): row for row in rows}
        condition_rows: list[dict[str, Any]] = []
        metric_rows: list[dict[str, Any]] = []
        for identity in positions:
            row = rows_by_code.get(identity["stock_code"])
            if row is None:
                continue
            condition_rows.append(
                self._condition_row(
                    identity=identity,
                    row=row,
                    source_id=source_id,
                    source_hash=source_hash,
                    decision=decision,
                )
            )
            metric_rows.extend(
                {
                    **identity,
                    "metric_id": metric_id,
                    "value": value,
                    "available_date": decision.isoformat(),
                    "available_at": capture_completed.isoformat(),
                }
                for metric_id, value in row["metrics"].items()
            )

        common = {
            "source_version": SOURCE_VERSION,
            "source_id": source_id,
            "source_snapshot_hash": source_hash,
            "as_of_date": decision.isoformat(),
            "upstream_receipt_available_at": available_at.isoformat(),
            "available_at": capture_completed.isoformat(),
            "decision_cutoff_at": cutoff.isoformat(),
            "source_semantics": (
                "daily technical_indicators and daily_prices read after quick receipt; "
                "condition is observation-only until a governed entry thesis exists"
            ),
            "market_db_path": str(self.market_db_path),
            "quick_status_path": str(self.quick_status_path),
            "freshness_status_path": str(self.freshness_status_path),
            "baseline_path": str(baseline),
            "baseline_sha256": baseline_hash,
            "unresolved_identity_codes": unresolved,
            "missing_market_codes": missing_codes,
        }
        condition_body = {
            "schema_version": CONDITION_SOURCE_SCHEMA_VERSION,
            **common,
            "condition_evaluation": "observation_only_without_entry_thesis",
            "positions": condition_rows,
        }
        metrics_body = {
            "schema_version": METRICS_SOURCE_SCHEMA_VERSION,
            **common,
            "metric_definitions": {
                metric_id: f"technical_indicators/daily_prices.{column}"
                for metric_id, column in _DECIMAL_COLUMNS
            },
            "metrics": metric_rows,
        }
        condition_path, condition_file_hash, _ = _write_hashed(
            output / f"condition_{decision.strftime('%Y%m%d')}.json", condition_body
        )
        metrics_path, metrics_file_hash, _ = _write_hashed(
            output / f"metrics_{decision.strftime('%Y%m%d')}.json", metrics_body
        )
        warnings = [*status_warnings]
        warnings.extend(f"position_health_source_identity_missing:{code}" for code in unresolved)
        warnings.extend(f"position_health_source_market_missing:{code}" for code in missing_codes)
        if not positions:
            warnings.append("position_health_source_no_verified_position_id")
        status = "passed" if not warnings else "degraded"
        receipt_body: dict[str, Any] = {
            "schema_version": SOURCE_VERSION,
            "producer": f"{type(self).__module__}.{type(self).__name__}",
            "status": status,
            "decision_date": decision.isoformat(),
            "decision_cutoff_at": cutoff.isoformat(),
            "available_at": capture_completed.isoformat(),
            "observed_at": observed.isoformat(),
            "market_capture_started_at": capture_started.isoformat(),
            "market_capture_completed_at": capture_completed.isoformat(),
            "source_id": source_id,
            "source_snapshot_hash": source_hash,
            "upstream_receipt_available_at": available_at.isoformat(),
            "condition_source_path": str(condition_path),
            "condition_source_file_sha256": condition_file_hash,
            "metrics_source_path": str(metrics_path),
            "metrics_source_file_sha256": metrics_file_hash,
            "verified_position_count": len(positions),
            "condition_row_count": len(condition_rows),
            "metric_row_count": len(metric_rows),
            "unresolved_identity_codes": unresolved,
            "missing_market_codes": missing_codes,
            "warnings": list(dict.fromkeys(warnings)),
            "blockers": [],
            "read_only": True,
            "writes_market_database": False,
            "writes_paper_state": False,
            "writes_formal_state": False,
            "research_only": True,
            "formal_credit": False,
            "broker_execution": False,
        }
        receipt_path, receipt_file_hash, _ = _write_hashed(
            output / f"source_receipt_{decision.strftime('%Y%m%d')}.json", receipt_body
        )
        latest = output / "latest_status.json"
        _write_atomic(latest, (json.dumps({**receipt_body, "receipt_path": str(receipt_path), "receipt_file_sha256": receipt_file_hash}, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        return {
            **receipt_body,
            "receipt_path": str(receipt_path),
            "latest_status_path": str(latest),
        }

    @staticmethod
    def _validate_receipts(
        quick: Mapping[str, Any],
        freshness: Mapping[str, Any],
        *,
        decision: date,
        cutoff: datetime,
        observed: datetime,
    ) -> tuple[datetime, list[str]]:
        if quick.get("status") != "passed":
            raise PositionHealthMarketSourceError("quick_status_not_passed")
        if quick.get("writes_market_data_db") is not True:
            raise PositionHealthMarketSourceError("quick_status_market_write_receipt_missing")
        if quick.get("errors") not in (None, [], ()):
            raise PositionHealthMarketSourceError("quick_status_errors_present")
        quick_date = _parse_date(quick.get("end_date"), "quick_status_end_date")
        if quick_date != decision:
            raise PositionHealthMarketSourceError("quick_status_date_mismatch")
        completed = _parse_aware(quick.get("completed_at"), "quick_status_completed_at")
        if completed > cutoff or completed > observed:
            raise PositionHealthMarketSourceError("quick_status_completed_at_future")
        if freshness.get("status") != "passed":
            raise PositionHealthMarketSourceError("freshness_status_not_passed")
        checks = freshness.get("checks")
        if not isinstance(checks, Mapping):
            raise PositionHealthMarketSourceError("freshness_checks_missing")
        target_key = decision.strftime("%Y%m%d")
        # The long-running updater has emitted both singular and plural key
        # spellings across existing receipt versions.  Accept only those two
        # explicit canonical names; never infer freshness from the SQLite
        # max(date) while the receipt is missing.
        daily_latest_key = checks.get("daily_prices_latest_date_key")
        if daily_latest_key is None:
            daily_latest_key = checks.get("daily_price_latest_date_key")
        if str(daily_latest_key or "") != target_key:
            raise PositionHealthMarketSourceError("freshness_daily_prices_date_mismatch")
        if str(checks.get("technical_indicators_latest_date") or "") != target_key:
            raise PositionHealthMarketSourceError("freshness_technical_date_mismatch")
        checked = _parse_aware(freshness.get("checked_at"), "freshness_checked_at")
        if checked > cutoff or checked > observed:
            raise PositionHealthMarketSourceError("freshness_checked_at_future")
        warnings = [
            str(item)
            for item in (quick.get("warnings") or [])
            if str(item).strip()
        ] + [
            str(item)
            for item in (freshness.get("warnings") or [])
            if str(item).strip()
        ]
        return completed, list(dict.fromkeys(warnings))

    def _read_market_rows(
        self,
        *,
        codes: Sequence[str],
        decision: date,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.market_db_path.is_file():
            raise PositionHealthMarketSourceError("market_db_missing")
        before = _stat_token(self.market_db_path)
        target = decision.strftime("%Y%m%d")
        requested = {str(code) for code in codes if str(code).strip()}
        if not requested:
            # There is no safe stock-code fallback when the health baseline
            # has not proved a position identity.  Avoid scanning a large,
            # possibly active database just to discard every row.
            after = _stat_token(self.market_db_path)
            if before != after:
                raise PositionHealthMarketSourceError("market_db_changed_during_read")
            return [], {
                "path": str(self.market_db_path),
                "stat_before": before,
                "stat_after": after,
                "data_version": None,
                "table_scope": ["technical_indicators", "daily_prices"],
                "decision_date": decision.isoformat(),
                "selected_code_count": 0,
                "query_skipped": "no_verified_position_identity",
            }
        rows: list[dict[str, Any]] = []
        try:
            uri = f"file:{self.market_db_path.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if not {"technical_indicators", "daily_prices"}.issubset(tables):
                    raise PositionHealthMarketSourceError("market_db_required_tables_missing")
                data_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
                query = """
                    SELECT
                        t.證券代號 AS technical_code,
                        t.日期 AS technical_date,
                        t.RSI AS rsi,
                        t.MACD AS macd,
                        t.MACD_signal AS macd_signal,
                        t.MACD_hist AS macd_hist,
                        t.MA5 AS ma5,
                        t.MA10 AS ma10,
                        t.MA20 AS ma20,
                        t.MA60 AS ma60,
                        t.ATR AS atr,
                        t.ADX AS adx,
                        p.證券代號 AS price_code,
                        p.日期 AS price_date,
                        p.收盤價 AS close_price,
                        p.開盤價 AS open_price,
                        p.最高價 AS high_price,
                        p.最低價 AS low_price,
                        p.成交股數 AS volume
                    FROM technical_indicators AS t
                    JOIN daily_prices AS p
                      ON p.證券代號 = t.證券代號 AND p.日期 = t.日期
                    WHERE t.日期 = ?
                """
                selected = connection.execute(query, (target,)).fetchall()
                for raw in selected:
                    code = _source_row_code(raw["technical_code"])
                    if code not in requested:
                        continue
                    if _source_row_code(raw["price_code"]) != code:
                        raise PositionHealthMarketSourceError(
                            f"market_row_identity_mismatch:{code}"
                        )
                    if _date_key(raw["technical_date"]) != target or _date_key(raw["price_date"]) != target:
                        raise PositionHealthMarketSourceError(
                            f"market_row_date_mismatch:{code}"
                        )
                    metrics: dict[str, str] = {}
                    for metric_id, _column in _DECIMAL_COLUMNS:
                        value = raw[metric_id]
                        if value is None or value == "":
                            continue
                        metrics[metric_id] = str(_decimal(value, f"{code}:{metric_id}"))
                    if "close_price" not in metrics:
                        raise PositionHealthMarketSourceError(f"market_close_missing:{code}")
                    rows.append({"stock_code": code, "metrics": dict(sorted(metrics.items()))})
                if len({str(row["stock_code"]) for row in rows}) != len(rows):
                    raise PositionHealthMarketSourceError("market_duplicate_code_date")
                after_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
        except PositionHealthMarketSourceError:
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise PositionHealthMarketSourceError(
                f"market_db_read_failed:{type(exc).__name__}"
            ) from exc
        after = _stat_token(self.market_db_path)
        if before != after or data_version != after_version:
            raise PositionHealthMarketSourceError("market_db_changed_during_read")
        return sorted(rows, key=lambda item: str(item["stock_code"])), {
            "path": str(self.market_db_path),
            "stat_before": before,
            "stat_after": after,
            "data_version": data_version,
            "table_scope": ["technical_indicators", "daily_prices"],
            "decision_date": decision.isoformat(),
            "selected_code_count": len(rows),
        }

    @staticmethod
    def _condition_row(
        *,
        identity: Mapping[str, str],
        row: Mapping[str, Any],
        source_id: str,
        source_hash: str,
        decision: date,
    ) -> dict[str, Any]:
        metrics = row.get("metrics")
        if not isinstance(metrics, Mapping):
            raise PositionHealthMarketSourceError("condition_metrics_invalid")
        close_price = str(metrics.get("close_price") or "")
        result = PortfolioConditionResult(
            stock_code=str(identity["stock_code"]),
            status="warning",
            label="PIT 市場快照已取得，等待進場論點",
            source_label="technical_indicators_pit",
            reasons=[
                "current_market_snapshot_observed",
                "entry_thesis_or_entry_condition_source_required",
            ],
            details={
                "condition_semantics": "observation_only_without_entry_thesis",
                "as_of_date": decision.isoformat(),
                "current_price": close_price,
                "current_snapshot_source": source_id,
            },
        )
        snapshot = PortfolioCurrentSnapshot(
            current_regime="",
            current_total_score=None,
            # The legacy monitor DTO is float-typed; keep Decimal as the
            # canonical metric representation and cross this DTO boundary
            # explicitly for its existing consumer contract.
            current_price=float(Decimal(close_price)),
        )
        return {
            **dict(identity),
            "quality": "observed",
            "result": {
                "stock_code": result.stock_code,
                "status": result.status,
                "label": result.label,
                "source_label": result.source_label,
                "entry_regime": result.entry_regime,
                "current_regime": result.current_regime,
                "entry_total_score": result.entry_total_score,
                "current_total_score": result.current_total_score,
                "reasons": list(result.reasons),
                "details": dict(result.details),
            },
            "current_snapshot": {
                "current_regime": snapshot.current_regime,
                "current_total_score": None,
                "current_price": str(snapshot.current_price),
            },
            "source_trace": [
                f"market_source:{source_id}",
                f"market_source_hash:{source_hash}",
            ],
        }


def produce_position_health_market_sources(**kwargs: Any) -> dict[str, Any]:
    """Convenience wrapper used by the scheduled caller and the CLI."""

    producer = PositionHealthMarketSourceProducer(
        market_db_path=kwargs.pop("market_db_path"),
        quick_status_path=kwargs.pop("quick_status_path"),
        freshness_status_path=kwargs.pop("freshness_status_path"),
    )
    return producer.produce(**kwargs)
