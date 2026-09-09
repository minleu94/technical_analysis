"""TDCC 1-5 weekly candidate capture and normalization.

The official TDCC 1-5 payload contains the distribution levels 1--16 and
level 17, an official total row.  This module keeps every source row and
builds a separate, explicitly derived aggregate for the existing P0 shadow
contract.  It never writes a production database and never turns the report
date into an availability date: ``first_observed_at`` is the only availability
evidence when TDCC does not publish a timestamp in the payload.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


TDCC_SOURCE_ID = "tdcc_shareholding"
TDCC_SOURCE_VERSION = "tdcc-official-od-1-5"
TDCC_URL = "https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5"
TDCC_FIELDS = ("資料日期", "證券代號", "持股分級", "人數", "股數", "占集保庫存數比例%")
TDCC_DISTRIBUTION_TIERS = tuple(range(1, 17))
TDCC_TOTAL_TIER = 17
_REQUIRED = frozenset(TDCC_FIELDS)


class TDCCPayloadError(ValueError):
    """The official payload cannot be safely normalized."""


@dataclass(frozen=True)
class TDCCParseResult:
    report_date: str
    source_payload_sha256: str
    observed_at: str
    tier_rows: tuple[dict[str, Any], ...]
    aggregate_rows: tuple[dict[str, Any], ...]
    quarantine_rows: tuple[dict[str, Any], ...]

    @property
    def symbol_count(self) -> int:
        return len({str(row["symbol"]) for row in self.tier_rows})

    @property
    def ready_count(self) -> int:
        return sum(row["candidate_status"] == "shadow_ready" for row in self.aggregate_rows)

    def manifest_counts(self) -> dict[str, int]:
        return {
            "raw_tier_rows": len(self.tier_rows),
            "aggregate_rows": len(self.aggregate_rows),
            "shadow_ready_rows": self.ready_count,
            "blocked_aggregate_rows": len(self.aggregate_rows) - self.ready_count,
            "quarantine_rows": len(self.quarantine_rows),
            "symbols": self.symbol_count,
        }


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TDCCPayloadError("observed_at 必須是含 timezone 的 datetime")
    return value.astimezone(timezone.utc)


def parse_observed_at(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return _require_aware(datetime.fromisoformat(normalized))
    except (TypeError, ValueError) as exc:
        raise TDCCPayloadError(f"observed_at 無效: {value}") from exc


def _strict_int(value: Any, *, field: str) -> int:
    text = str(value or "").replace(",", "").strip()
    if not text:
        raise TDCCPayloadError(f"{field} 缺少整數")
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise TDCCPayloadError(f"{field} 不是整數") from exc
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        raise TDCCPayloadError(f"{field} 不是整數")
    return int(parsed)


def _ratio_bp(value: Any) -> int:
    text = str(value or "").replace(",", "").replace("%", "").strip()
    if not text:
        raise TDCCPayloadError("占集保庫存數比例% 缺少數值")
    try:
        ratio = Decimal(text)
    except InvalidOperation as exc:
        raise TDCCPayloadError("占集保庫存數比例% 格式錯誤") from exc
    if not ratio.is_finite() or ratio < 0 or ratio > 100:
        raise TDCCPayloadError("占集保庫存數比例% 超出 0..100")
    scaled = ratio * Decimal("100")
    if scaled != scaled.to_integral_value():
        raise TDCCPayloadError("占集保庫存數比例% 超過兩位小數")
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def _row_hash(row: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _parse_report_date(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", text):
        raise TDCCPayloadError("資料日期 必須是 YYYYMMDD")
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise TDCCPayloadError("資料日期 不是合法日期") from exc


def _read_payload_rows(payload: bytes) -> tuple[dict[str, Any], ...]:
    text = payload.decode("utf-8-sig")
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TDCCPayloadError("TDCC JSON 無法解析") from exc
        if not isinstance(decoded, list):
            raise TDCCPayloadError("TDCC JSON 根節點必須是 list")
        rows = tuple(dict(item) for item in decoded if isinstance(item, Mapping))
    else:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise TDCCPayloadError("TDCC CSV 缺少 header")
        rows = tuple(dict(row) for row in reader)
    if not rows:
        raise TDCCPayloadError("TDCC payload 沒有資料列")
    normalized_fields = {str(field).lstrip("\ufeff").strip() for field in rows[0]}
    if not _REQUIRED.issubset(normalized_fields):
        missing = sorted(_REQUIRED - normalized_fields)
        raise TDCCPayloadError(f"TDCC payload 缺少欄位: {','.join(missing)}")
    return tuple(
        {str(key).lstrip("\ufeff").strip(): value for key, value in row.items()}
        for row in rows
    )


def normalize_tdcc_payload(
    payload: bytes,
    *,
    observed_at: datetime,
    source_payload_sha256: str | None = None,
    source_version: str = TDCC_SOURCE_VERSION,
) -> TDCCParseResult:
    """Normalize one official payload while preserving its report/observation times.

    A source row is never silently dropped.  Malformed rows abort the run so
    the caller can keep the raw payload and investigate schema drift.  Four
    live symbols in some TDCC snapshots may have distribution percentages that
    do not reconcile with the official total row; those symbols remain in the
    full tier artifact but their aggregate is marked ``blocked``.
    """

    observed = _require_aware(observed_at)
    observed_text = observed.isoformat().replace("+00:00", "Z")
    observed_taipei = observed.astimezone(ZoneInfo("Asia/Taipei"))
    # Existing individual-research readers have a date-only cutoff.  A
    # same-day observed payload could therefore be read by a morning decision
    # if its UTC date were used directly.  The next Taipei calendar date is a
    # conservative date-only availability boundary; the exact observed_at is
    # retained separately for audit/PIT consumers that support timestamps.
    safe_available_date = (observed_taipei.date() + timedelta(days=1)).isoformat()
    payload_sha = (source_payload_sha256 or sha256(payload).hexdigest()).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", payload_sha):
        raise TDCCPayloadError("source_payload_sha256 必須是 SHA-256")
    rows = _read_payload_rows(payload)
    dates: set[str] = set()
    tier_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for source_row in rows:
        report_date = _parse_report_date(source_row.get("資料日期"))
        dates.add(report_date)
        symbol = str(source_row.get("證券代號") or "").strip()
        if not symbol:
            raise TDCCPayloadError("證券代號 不可為空")
        tier = _strict_int(source_row.get("持股分級"), field="持股分級")
        if tier < 1 or tier > TDCC_TOTAL_TIER:
            raise TDCCPayloadError(f"持股分級 超出 1..{TDCC_TOTAL_TIER}: {tier}")
        identity = (symbol, tier)
        if identity in seen:
            raise TDCCPayloadError(f"TDCC 重複列: {symbol}/{tier}")
        seen.add(identity)
        tier_rows.append(
            {
                "symbol": symbol,
                "report_date": report_date,
                "tier": tier,
                "holder_count": _strict_int(source_row.get("人數"), field="人數"),
                "shares": _strict_int(source_row.get("股數"), field="股數"),
                "holding_ratio_bp": _ratio_bp(source_row.get("占集保庫存數比例%")),
                "tier_role": "official_total" if tier == TDCC_TOTAL_TIER else "distribution",
                "source_payload_sha256": payload_sha,
                "raw_row_sha256": _row_hash(source_row),
                "first_observed_at": observed_text,
                "observed_at": observed_text,
                "available_at": observed_text,
                "available_date": safe_available_date,
                "quality": "degraded",
                "availability_evidence": "first_observed_only",
                "source_version": source_version,
            }
        )
    if len(dates) != 1:
        raise TDCCPayloadError("TDCC payload 必須只有一個資料日期")
    report_date = next(iter(dates))

    by_symbol: dict[str, dict[int, dict[str, Any]]] = {}
    for row in tier_rows:
        by_symbol.setdefault(str(row["symbol"]), {})[int(row["tier"])] = row
    aggregate_rows: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []
    for symbol in sorted(by_symbol):
        levels = by_symbol[symbol]
        missing = sorted(set((*TDCC_DISTRIBUTION_TIERS, TDCC_TOTAL_TIER)) - set(levels))
        if missing:
            raise TDCCPayloadError(f"{symbol} 缺少完整官方級距: {missing}")
        distribution_total_bp = sum(int(levels[t]["holding_ratio_bp"]) for t in TDCC_DISTRIBUTION_TIERS)
        official_total_bp = int(levels[TDCC_TOTAL_TIER]["holding_ratio_bp"])
        large_bp = int(levels[15]["holding_ratio_bp"])
        retail_bp = sum(int(levels[t]["holding_ratio_bp"]) for t in range(1, 6))
        # The existing P0 contract is a full 10,000bp partition.  The source
        # rounds each tier to 2 decimals, so use a disclosed complement for
        # ordinary rounding residuals; large source mismatches remain blocked.
        other_bp = 10000 - large_bp - retail_bp
        residual_bp = 10000 - distribution_total_bp
        mismatch = abs(residual_bp) > 15 or official_total_bp != 10000 or other_bp < 0
        diagnostics = [
            "weekly_period_end_is_not_available_date",
            "official_publication_timestamp_missing",
            "distribution_sum_uses_complement_after_source_rounding",
        ]
        if residual_bp != 0:
            diagnostics.append(f"source_distribution_rounding_residual_bp:{residual_bp}")
        if official_total_bp != 10000:
            diagnostics.append(f"official_total_ratio_not_10000bp:{official_total_bp}")
        if mismatch:
            diagnostics.append("source_distribution_total_mismatch")
        tiers_json = json.dumps(
            [levels[t] for t in sorted(levels)], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        aggregate = {
            "symbol": symbol,
            "stock_code": symbol,
            "period_end": report_date,
            "report_date": report_date,
            "decision_date": report_date,
            "available_date": safe_available_date,
            "first_observed_at": observed_text,
            "observed_at": observed_text,
            "available_at": observed_text,
            "publication_at": "",
            "source_version": source_version,
            "source_payload_sha256": payload_sha,
            "quality": "degraded",
            "availability_evidence": "first_observed_only",
            "shareholding_tiers": tiers_json,
            "large_holder_ratio_bp": large_bp,
            "retail_holder_ratio_bp": retail_bp,
            "other_holder_ratio_bp": other_bp,
            "dispersion_index_bp": retail_bp - large_bp,
            "source_distribution_total_bp": distribution_total_bp,
            "source_distribution_residual_bp": residual_bp,
            "official_total_ratio_bp": official_total_bp,
            "candidate_status": "blocked" if mismatch else "shadow_ready",
            "diagnostics": "|".join(diagnostics),
            "downstream_eligibility": "none",
            "writes_allowed": False,
        }
        aggregate_rows.append(aggregate)
        if mismatch:
            quarantine_rows.append(
                {
                    "symbol": symbol,
                    "report_date": report_date,
                    "source_distribution_total_bp": distribution_total_bp,
                    "official_total_ratio_bp": official_total_bp,
                    "source_distribution_residual_bp": residual_bp,
                    "reason": "source_distribution_total_mismatch",
                    "source_payload_sha256": payload_sha,
                }
            )
    return TDCCParseResult(
        report_date=report_date,
        source_payload_sha256=payload_sha,
        observed_at=observed_text,
        tier_rows=tuple(tier_rows),
        aggregate_rows=tuple(aggregate_rows),
        quarantine_rows=tuple(quarantine_rows),
    )


def p0_shadow_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Project an aggregate candidate into the existing TDCC shadow contract."""

    required = ("symbol", "period_end", "available_date", "source_version")
    missing = [field for field in required if not row.get(field)]
    if missing:
        raise TDCCPayloadError(f"candidate 缺少 P0 欄位: {','.join(missing)}")
    other_ratio = int(row["other_holder_ratio_bp"])
    if str(row.get("candidate_status", "")) != "shadow_ready":
        # Keep a source-mismatch row visibly blocked when it crosses the
        # existing adapter boundary.  The ready aggregate uses a disclosed
        # complement; quarantine rows must expose their raw tier total instead
        # of becoming accidentally shadow_ready through that normalization.
        tiers = json.loads(str(row.get("shareholding_tiers", "[]")))
        other_ratio = sum(
            int(item["holding_ratio_bp"])
            for item in tiers
            if 6 <= int(item.get("tier", 0)) <= 16
        )
    return {
        "symbol": str(row["symbol"]),
        "period_end": str(row["period_end"]),
            "available_date": str(row["available_date"]),
        "source_version": str(row["source_version"]),
        "large_holder_ratio_bp": int(row["large_holder_ratio_bp"]),
        "retail_holder_ratio_bp": int(row["retail_holder_ratio_bp"]),
        "other_holder_ratio_bp": other_ratio,
        "source_payload_sha256": str(row["source_payload_sha256"]),
        "observed_at": str(row.get("observed_at", row.get("first_observed_at", ""))),
        "available_at": str(row.get("available_at", "")),
        "availability_evidence": str(row.get("availability_evidence", "first_observed_only")),
        "quality": str(row["quality"]),
        "candidate_status": str(row["candidate_status"]),
        "diagnostics": str(row["diagnostics"]),
        "downstream_eligibility": "none",
    }


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]], *, fieldnames: Iterable[str]) -> None:
    """Write a deterministic UTF-8 CSV; caller controls the output directory."""

    rows_tuple = tuple(dict(row) for row in rows)
    fields = tuple(fieldnames)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows_tuple)
        handle.flush()
    temp.replace(path)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)
