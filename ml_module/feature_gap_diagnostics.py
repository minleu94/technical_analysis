"""Bounded, read-only diagnosis for the four legacy ML feature gaps.

The current SQLite schema stores a usable TAIEX close pair while leaving the
two market change columns empty.  Those two values can be derived from the
official close pair in a separate candidate contract.  The two technical
``change`` columns have a direction/legacy meaning and are not a numeric
source; they must remain missing for the current release and be excluded by a
future feature contract.

This module deliberately does not repair SQLite or rewrite an existing PIT
artifact.  Its database probe is date/symbol bounded and opens the source in
SQLite read-only mode so a scheduler can attach the resulting evidence to a
candidate without changing the source database.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


MARKET_CHANGE_FEATURE_IDS = (
    "market_indices.漲跌百分比",
    "market_indices.漲跌點數",
)
TECHNICAL_LEGACY_FEATURE_IDS = (
    "technical_indicators.涨跌",
    "technical_indicators.漲跌(+/-)",
)

_MARKET_REQUIRED_COLUMNS = (
    "日期",
    "指數名稱",
    "收盤指數",
    "收盤價",
    "漲跌點數",
    "漲跌百分比",
)
_TECHNICAL_REQUIRED_COLUMNS = (
    "日期",
    "證券代號",
    "涨跌",
    "漲跌(+/-)",
    "漲跌價差",
)
_DAILY_PRICE_REQUIRED_COLUMNS = (
    "日期",
    "證券代號",
    "漲跌(+/-)",
    "漲跌價差",
    "收盤價",
)


class FeatureGapDiagnosticError(ValueError):
    """Raised when the bounded source cannot satisfy the diagnostic contract."""


def classify_feature_gap(feature_id: str) -> dict[str, Any]:
    """Return the explicit resolution policy for one known feature gap."""

    if feature_id in MARKET_CHANGE_FEATURE_IDS:
        return {
            "feature_id": feature_id,
            "source_table": "market_indices",
            "raw_column": feature_id.split(".", 1)[1],
            "resolution": "derive_from_official_close_pair",
            "numeric_contract": "valid_derived_decimal",
            "required_source_fields": ["market_indices.收盤指數"],
            "derivation_method": "market-index-change-derivation.v1",
            "availability_rule": "max(current_close, previous_close)_available_at",
            "sqlite_write_allowed": False,
            "candidate_only": True,
        }
    if feature_id in TECHNICAL_LEGACY_FEATURE_IDS:
        return {
            "feature_id": feature_id,
            "source_table": "technical_indicators",
            "raw_column": feature_id.split(".", 1)[1],
            "resolution": "exclude_from_numeric_contract",
            "numeric_contract": "legacy_direction_or_duplicate_not_numeric",
            "required_source_fields": [
                "technical_indicators.漲跌價差",
                "daily_prices.漲跌(+/-)",
            ],
            "derivation_method": None,
            "availability_rule": "source_value_only; no coercion or zero fill",
            "sqlite_write_allowed": False,
            "candidate_only": True,
        }
    raise FeatureGapDiagnosticError(f"unsupported feature gap: {feature_id}")


def diagnose_sqlite_feature_gaps(
    db_path: Path,
    *,
    expected_price_date: str,
    previous_price_date: str,
    symbols: Sequence[str],
    market_entity: str = "TAIEX",
    post_freeze_parent_input: Path | None = None,
    expected_post_freeze_parent_input_compressed_hash: str | None = None,
    post_freeze_raw_dataset_manifest: Path | None = None,
    expected_post_freeze_raw_publication_manifest_hash: str | None = None,
    expected_post_freeze_raw_dataset_manifest_hash: str | None = None,
    post_freeze_calendar_database: Path | None = None,
    post_freeze_calendar_cache_path: Path | None = None,
    post_freeze_temporary_closure_path: Path | None = None,
) -> dict[str, Any]:
    """Inspect only the requested dates/entities and return machine evidence.

    ``expected_price_date`` and ``previous_price_date`` are ISO dates.  The
    SQLite source uses the canonical compact ``YYYYMMDD`` representation.  A
    close pair is considered available only when exactly one positive close is
    present for each requested date.  Market change columns themselves are
    never treated as a source for the derived values.
    """

    expected_iso, expected_db = _normalise_date(expected_price_date)
    previous_iso, previous_db = _normalise_date(previous_price_date)
    if previous_iso >= expected_iso:
        raise FeatureGapDiagnosticError(
            "previous_price_date must precede expected_price_date"
        )
    normalised_symbols = _normalise_symbols(symbols)
    if not market_entity.strip():
        raise FeatureGapDiagnosticError("market_entity must be non-empty")
    post_freeze_values = (
        post_freeze_parent_input,
        expected_post_freeze_parent_input_compressed_hash,
        post_freeze_raw_dataset_manifest,
        expected_post_freeze_raw_publication_manifest_hash,
        expected_post_freeze_raw_dataset_manifest_hash,
        post_freeze_calendar_database,
    )
    if any(value is not None for value in post_freeze_values) and not all(
        value is not None for value in post_freeze_values
    ):
        raise FeatureGapDiagnosticError(
            "post-freeze PIT evidence requires parent, raw manifest, and "
            "calendar custody arguments together"
        )
    resolved = Path(db_path).resolve()
    if not resolved.is_file():
        raise FeatureGapDiagnosticError(f"SQLite source is missing: {resolved}")

    uri = f"file:{resolved.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise FeatureGapDiagnosticError(
            f"cannot open SQLite source read-only: {resolved}"
        ) from exc
    try:
        connection.execute("PRAGMA query_only=ON")
        _require_columns(
            connection,
            table_name="market_indices",
            required=_MARKET_REQUIRED_COLUMNS,
        )
        _require_columns(
            connection,
            table_name="technical_indicators",
            required=_TECHNICAL_REQUIRED_COLUMNS,
        )
        _require_columns(
            connection,
            table_name="daily_prices",
            required=_DAILY_PRICE_REQUIRED_COLUMNS,
        )

        market_rows = connection.execute(
            """
            SELECT [日期], [指數名稱], [收盤指數], [收盤價],
                   [漲跌點數], [漲跌百分比]
            FROM market_indices
            WHERE [日期] IN (?, ?) AND [指數名稱] = ?
            ORDER BY [日期]
            """,
            (previous_db, expected_db, market_entity),
        ).fetchall()
        technical_rows = connection.execute(
            """
            SELECT [日期], [證券代號], [涨跌], [漲跌(+/-)],
                   [漲跌價差]
            FROM technical_indicators
            WHERE [日期] = ? AND [證券代號] IN (
                """
            + ",".join("?" for _ in normalised_symbols)
            + ") ORDER BY [證券代號]",
            (expected_db, *normalised_symbols),
        ).fetchall()
        daily_rows = connection.execute(
            """
            SELECT [日期], [證券代號], [漲跌(+/-)], [漲跌價差], [收盤價]
            FROM daily_prices
            WHERE [日期] = ? AND [證券代號] IN (
                """
            + ",".join("?" for _ in normalised_symbols)
            + ") ORDER BY [證券代號]",
            (expected_db, *normalised_symbols),
        ).fetchall()
    except sqlite3.Error as exc:
        raise FeatureGapDiagnosticError(
            "bounded SQLite feature-gap query failed"
        ) from exc
    finally:
        connection.close()

    market_evidence = _market_evidence(
        market_rows,
        expected_iso=expected_iso,
        previous_iso=previous_iso,
        market_entity=market_entity,
    )
    technical_evidence = _technical_evidence(
        technical_rows,
        daily_rows,
        symbols=normalised_symbols,
    )
    post_freeze_market_evidence = None
    if all(value is not None for value in post_freeze_values):
        assert post_freeze_parent_input is not None
        assert expected_post_freeze_parent_input_compressed_hash is not None
        assert post_freeze_raw_dataset_manifest is not None
        assert expected_post_freeze_raw_publication_manifest_hash is not None
        assert expected_post_freeze_raw_dataset_manifest_hash is not None
        assert post_freeze_calendar_database is not None
        post_freeze_market_evidence = inspect_post_freeze_market_candidate(
            parent_input=post_freeze_parent_input,
            expected_parent_input_compressed_hash=(
                expected_post_freeze_parent_input_compressed_hash
            ),
            raw_dataset_manifest=post_freeze_raw_dataset_manifest,
            expected_raw_publication_manifest_hash=(
                expected_post_freeze_raw_publication_manifest_hash
            ),
            expected_raw_dataset_manifest_hash=(
                expected_post_freeze_raw_dataset_manifest_hash
            ),
            calendar_database=post_freeze_calendar_database,
            calendar_cache_path=post_freeze_calendar_cache_path,
            temporary_closure_path=post_freeze_temporary_closure_path,
        )
    features = {
        feature_id: classify_feature_gap(feature_id)
        for feature_id in (*MARKET_CHANGE_FEATURE_IDS, *TECHNICAL_LEGACY_FEATURE_IDS)
    }
    features["market_indices.漲跌點數"].update(
        {
            "source_non_null_count": market_evidence["market_change_non_null"][
                "point_delta"
            ],
            "source_value_available": market_evidence["close_pair_available"],
            "source_value_scope": "bounded_sqlite_probe_only",
            "post_freeze_candidate_verified": post_freeze_market_evidence
            is not None,
            "post_freeze_candidate_scope": (
                None
                if post_freeze_market_evidence is None
                else post_freeze_market_evidence["evidence_scope"]["scope_id"]
            ),
            "post_freeze_candidate_date_binding": (
                None
                if post_freeze_market_evidence is None
                else post_freeze_market_evidence["evidence_scope"][
                    "date_binding"
                ]
            ),
            "model_input_eligible": False,
        }
    )
    features["market_indices.漲跌百分比"].update(
        {
            "source_non_null_count": market_evidence["market_change_non_null"][
                "percent_delta"
            ],
            "source_value_available": market_evidence["close_pair_available"],
            "source_value_scope": "bounded_sqlite_probe_only",
            "post_freeze_candidate_verified": post_freeze_market_evidence
            is not None,
            "post_freeze_candidate_scope": (
                None
                if post_freeze_market_evidence is None
                else post_freeze_market_evidence["evidence_scope"]["scope_id"]
            ),
            "post_freeze_candidate_date_binding": (
                None
                if post_freeze_market_evidence is None
                else post_freeze_market_evidence["evidence_scope"][
                    "date_binding"
                ]
            ),
            "model_input_eligible": False,
        }
    )
    for feature_id, column_name in (
        ("technical_indicators.涨跌", "simplified"),
        ("technical_indicators.漲跌(+/-)", "direction"),
    ):
        features[feature_id].update(
            {
                "source_non_null_count": technical_evidence[
                    "technical_change_non_null"
                ][column_name],
                "source_value_available": False,
            }
        )

    return {
        "schema_version": "v4-ml-feature-gap-diagnostic.v1",
        "status": "diagnosed",
        "source_database": str(resolved),
        "source_read_only": True,
        "bounded_query": True,
        "expected_price_date": expected_iso,
        "previous_price_date": previous_iso,
        "market_entity": market_entity,
        "symbols": list(normalised_symbols),
        "features": features,
        "market_source_evidence": market_evidence,
        "technical_source_evidence": technical_evidence,
        "post_freeze_market_evidence": post_freeze_market_evidence,
        "evidence_scope": {
            "cross_scope_join_allowed": False,
            "current_bounded_sqlite_probe": {
                "scope_id": "current_bounded_sqlite_source",
                "expected_price_date": expected_iso,
                "previous_price_date": previous_iso,
                "source_database": str(resolved),
                "model_input_eligible": False,
            },
            "post_freeze_market_candidate": (
                None
                if post_freeze_market_evidence is None
                else post_freeze_market_evidence["evidence_scope"]
            ),
        },
        "repair_decision": {
            "market": "candidate_derive_from_official_close_pair",
            "technical": "remain_missing_and_exclude_in_next_numeric_contract",
            "sqlite_source_write": False,
            "zero_fill": False,
            "historical_backfill": False,
        },
    }


def inspect_post_freeze_market_candidate(
    *,
    parent_input: Path,
    expected_parent_input_compressed_hash: str,
    raw_dataset_manifest: Path,
    expected_raw_publication_manifest_hash: str,
    expected_raw_dataset_manifest_hash: str,
    calendar_database: Path,
    calendar_cache_path: Path | None = None,
    temporary_closure_path: Path | None = None,
) -> dict[str, Any]:
    """Verify the existing post-freeze PIT market repair chain.

    This is deliberately an evidence adapter, not a second repair
    implementation.  It reuses the established feature-repair loader,
    official-calendar selector and Decimal derivation so a bounded SQLite
    close pair is never reported as model-eligible by itself.  The returned
    candidate remains gated behind a new feature contract/release.
    """

    from ml_module.allocation_contracts import post_freeze_shadow_decision_scope
    from ml_module.allocation_feature_contract import (
        build_market_repair_contract,
        derived_source_manifest_hash,
    )
    from scripts.build_ml_allocation_post_freeze_feature_repair import (
        _derive_market_values,
        _load_calendar_evidence,
        _load_official_closes,
        _load_raw_publication,
        _select_close_pair,
        _source_manifest_hash,
        _validate_parent_rows,
    )
    from scripts.build_ml_allocation_post_freeze_shadow_input import (
        RAW_DATASET_SCHEMA_VERSION,
        _available_datetime,
        _load_json_object,
        _text,
        _validate_eligibility_custody,
        _validate_raw_dataset_manifest,
    )
    from scripts.infer_ml_allocation_copilot import _load_rows

    def _sha256_bytes(value: bytes) -> str:
        return "sha256:" + hashlib.sha256(value).hexdigest()

    _require_digest(
        expected_parent_input_compressed_hash,
        field_name="expected_parent_input_compressed_hash",
    )
    _require_digest(
        expected_raw_publication_manifest_hash,
        field_name="expected_raw_publication_manifest_hash",
    )
    _require_digest(
        expected_raw_dataset_manifest_hash,
        field_name="expected_raw_dataset_manifest_hash",
    )

    parent_path = parent_input.resolve()
    if not parent_path.is_file():
        raise FeatureGapDiagnosticError(
            f"post-freeze parent input is missing: {parent_path}"
        )
    parent_bytes = parent_path.read_bytes()
    parent_hash = _sha256_bytes(parent_bytes)
    if parent_hash != expected_parent_input_compressed_hash:
        raise FeatureGapDiagnosticError(
            "post-freeze parent input compressed hash mismatch"
        )
    with post_freeze_shadow_decision_scope():
        parent_rows = _load_rows(parent_path)
    if not parent_rows:
        raise FeatureGapDiagnosticError(
            "post-freeze parent input contains no rows"
        )
    expected_decision = _available_datetime(
        parent_rows[0].decision_at,
        field_name="post-freeze parent decision_at",
    )
    expected_price_date = parent_rows[0].portfolio_state.as_of_date
    _validate_parent_rows(
        parent_rows,
        expected_decision=expected_decision,
        expected_price_date=expected_price_date,
    )
    parent_feature_ids = tuple(
        feature.feature_id for feature in parent_rows[0].features
    )
    if any(
        tuple(feature.feature_id for feature in row.features)
        != parent_feature_ids
        for row in parent_rows
    ):
        raise FeatureGapDiagnosticError(
            "post-freeze parent rows do not share one frozen feature set"
        )
    parent_registry_hash = parent_rows[0].feature_registry_hash
    try:
        contract = build_market_repair_contract(
            parent_feature_registry_hash=parent_registry_hash,
            feature_ids=parent_feature_ids,
        )
    except (TypeError, ValueError) as exc:
        raise FeatureGapDiagnosticError(
            "post-freeze parent feature set cannot bind repair contract"
        ) from exc

    raw_manifest_path = raw_dataset_manifest.resolve()
    if not raw_manifest_path.is_file():
        raise FeatureGapDiagnosticError(
            f"post-freeze raw dataset manifest is missing: {raw_manifest_path}"
        )
    raw_manifest = _load_json_object(
        raw_manifest_path,
        field_name="post-freeze raw dataset manifest",
    )
    if raw_manifest.get("schema_version") != RAW_DATASET_SCHEMA_VERSION:
        raise FeatureGapDiagnosticError(
            "post-freeze raw dataset manifest schema mismatch"
        )
    if raw_manifest.get("dataset_id") != "all_field_enriched":
        raise FeatureGapDiagnosticError(
            "post-freeze market evidence requires all_field_enriched"
        )
    _validate_raw_dataset_manifest(raw_manifest)
    raw_dataset_hash = _text(
        raw_manifest.get("manifest_hash"),
        field_name="post-freeze raw dataset manifest_hash",
    )
    if raw_dataset_hash != expected_raw_dataset_manifest_hash:
        raise FeatureGapDiagnosticError(
            "post-freeze raw dataset manifest hash mismatch"
        )
    publication_manifest_path = (
        raw_manifest_path.parent.parent / "manifest.json"
    )
    raw_publication = _load_raw_publication(
        publication_manifest_path,
        expected_manifest_hash=expected_raw_publication_manifest_hash,
        raw_dataset_manifest=raw_manifest_path,
        raw_dataset_manifest_hash=raw_dataset_hash,
    )
    _validate_eligibility_custody(
        publication_manifest_path=publication_manifest_path,
        publication=raw_publication,
        raw_dataset_manifest=raw_manifest,
    )
    official_closes = _load_official_closes(
        raw_dataset_manifest=raw_manifest_path,
        raw_manifest=raw_manifest,
        expected_price_date=expected_price_date,
        decision_at=expected_decision,
    )
    previous_date, calendar_evidence = _load_calendar_evidence(
        calendar_database=calendar_database.resolve(),
        expected_price_date=expected_price_date,
        calendar_cache_path=calendar_cache_path,
        temporary_closure_path=temporary_closure_path,
    )
    current_close, previous_close = _select_close_pair(
        official_closes,
        expected_price_date=expected_price_date,
        calendar_previous_date=previous_date,
    )
    derived_values = _derive_market_values(
        contract=contract,
        current=current_close,
        previous=previous_close,
        decision_at=expected_decision,
        expected_price_date=expected_price_date,
    )
    input_source_manifest_hash = _source_manifest_hash(
        parent_rows=parent_rows,
        source_id="sqlite.market_indices",
    )
    derived_manifest_hash = derived_source_manifest_hash(
        contract=contract,
        input_source_manifest_hash=input_source_manifest_hash,
    )
    calendar_selected = calendar_evidence.get("selected_calendar_evidence")
    calendar_availability_flags: list[bool] = []
    if isinstance(calendar_selected, Mapping):
        for selected in calendar_selected.values():
            if not isinstance(selected, Mapping):
                continue
            available_value = selected.get("available_at")
            captured_value = selected.get("captured_at")
            timestamp_value = (
                available_value
                if isinstance(available_value, str)
                else captured_value
            )
            if not isinstance(timestamp_value, str):
                continue
            try:
                calendar_availability_flags.append(
                    _available_datetime(
                        timestamp_value,
                        field_name="calendar evidence available_at",
                    )
                    <= expected_decision
                )
            except (TypeError, ValueError) as exc:
                raise FeatureGapDiagnosticError(
                    "calendar evidence timestamp is invalid"
                ) from exc
    calendar_evidence_as_of_decision = bool(calendar_availability_flags) and all(
        calendar_availability_flags
    )
    availability = {
        "current_close_available_at_lte_decision_at": (
            _available_datetime(
                current_close.available_at,
                field_name="current close available_at",
            )
            <= expected_decision
        ),
        "previous_close_available_at_lte_decision_at": (
            _available_datetime(
                previous_close.available_at,
                field_name="previous close available_at",
            )
            <= expected_decision
        ),
        "current_event_at_lte_decision_at": (
            _available_datetime(
                current_close.event_at,
                field_name="current close event_at",
            )
            <= expected_decision
        ),
        "previous_event_at_lte_decision_at": (
            _available_datetime(
                previous_close.event_at,
                field_name="previous close event_at",
            )
            <= expected_decision
        ),
        "calendar_evidence_available_at_lte_decision_at": (
            calendar_evidence_as_of_decision
        ),
        "calendar_evidence_pit_as_of_decision": (
            calendar_evidence_as_of_decision
        ),
        "source_candidate_available_as_of_decision": all(
            (
                _available_datetime(
                    current_close.available_at,
                    field_name="current close available_at",
                )
                <= expected_decision,
                _available_datetime(
                    previous_close.available_at,
                    field_name="previous close available_at",
                )
                <= expected_decision,
                _available_datetime(
                    current_close.event_at,
                    field_name="current close event_at",
                )
                <= expected_decision,
                _available_datetime(
                    previous_close.event_at,
                    field_name="previous close event_at",
                )
                <= expected_decision,
                calendar_evidence_as_of_decision,
            )
        ),
        "existing_frozen_v2_model_input_eligible": False,
        "new_release_required": True,
    }
    return {
        "schema_version": "v4-ml-post-freeze-market-source-evidence.v1",
        "status": "verified",
        "source_kind": "raw_pit_publication",
        "evidence_scope": {
            "scope_id": "historical_post_freeze_parent_input",
            "date_binding": {
                "expected_price_date": expected_price_date,
                "selected_previous_trading_date": previous_date,
                "decision_at": expected_decision.isoformat(),
                "binding_source": "parent_input.portfolio_state.as_of_date",
                "decision_binding_source": "parent_input.rows[*].decision_at",
            },
            "calendar_capture_as_of_decision": (
                calendar_evidence_as_of_decision
            ),
            "join_with_current_bounded_sqlite_probe_allowed": False,
            "historical_parent_method_validation": True,
        },
        "parent_input": str(parent_path),
        "parent_input_compressed_hash": parent_hash,
        "parent_row_count": len(parent_rows),
        "parent_feature_registry_hash": parent_registry_hash,
        "raw_dataset_manifest": str(raw_manifest_path),
        "raw_dataset_manifest_hash": raw_dataset_hash,
        "raw_publication_manifest": str(publication_manifest_path),
        "raw_publication_manifest_hash": expected_raw_publication_manifest_hash,
        "decision_at": expected_decision.isoformat(),
        "expected_price_date": expected_price_date,
        "selected_previous_trading_date": previous_date,
        "calendar_evidence": calendar_evidence,
        "close_pair": {
            "current": asdict(current_close),
            "previous": asdict(previous_close),
        },
        "availability": availability,
        "feature_contract": contract.payload(),
        "feature_contract_hash": contract.contract_hash,
        "derived_source_manifest_hash": derived_manifest_hash,
        "derived_market_values": derived_values,
        "market_input_source_manifest_hash": input_source_manifest_hash,
        "sqlite_source_write": False,
        "model_inference_performed": False,
        "production_action_allowed": False,
    }


def _require_digest(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != len("sha256:") + 64
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise FeatureGapDiagnosticError(f"{field_name} must be a sha256 digest")
    return value


def _normalise_date(value: str) -> tuple[str, str]:
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        # ``date.fromisoformat`` is intentionally used after expanding the
        # compact form.  String slicing alone would accept impossible dates
        # such as 20261399 and later bind a query to a non-existent source
        # period.
        try:
            iso = date(
                int(text[:4]),
                int(text[4:6]),
                int(text[6:]),
            ).isoformat()
        except ValueError as exc:
            raise FeatureGapDiagnosticError(
                "feature-gap dates must be real YYYY-MM-DD or YYYYMMDD dates"
            ) from exc
    else:
        try:
            iso = date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise FeatureGapDiagnosticError(
                "feature-gap dates must be YYYY-MM-DD or YYYYMMDD"
            ) from exc
    return iso, iso.replace("-", "")


def _normalise_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    result = tuple(sorted({str(symbol).strip() for symbol in symbols}))
    if not result or any(len(symbol) != 4 or not symbol.isdigit() for symbol in result):
        raise FeatureGapDiagnosticError("symbols must contain four-digit codes")
    return result


def _require_columns(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    required: Sequence[str],
) -> None:
    columns = {
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info({_quote_identifier(table_name)})"
        ).fetchall()
    }
    missing = sorted(set(required) - columns)
    if missing:
        raise FeatureGapDiagnosticError(
            f"{table_name} source schema is missing: {','.join(missing)}"
        )


def _market_evidence(
    rows: Sequence[Sequence[Any]],
    *,
    expected_iso: str,
    previous_iso: str,
    market_entity: str,
) -> dict[str, Any]:
    by_date: dict[str, list[Sequence[Any]]] = {previous_iso: [], expected_iso: []}
    for row in rows:
        iso, _ = _normalise_date(str(row[0]))
        if iso in by_date:
            by_date[iso].append(row)
    close_by_date: dict[str, Decimal] = {}
    close_source_column: dict[str, str] = {}
    for iso, date_rows in by_date.items():
        if len(date_rows) != 1:
            continue
        row = date_rows[0]
        for index, column_name in ((2, "收盤指數"), (3, "收盤價")):
            value = _decimal_or_none(row[index])
            if value is not None and value.is_finite() and value > 0:
                close_by_date[iso] = value
                close_source_column[iso] = column_name
                break
    pair_available = set(close_by_date) == {previous_iso, expected_iso}
    derived: dict[str, Any] | None = None
    if pair_available:
        previous_close = close_by_date[previous_iso]
        current_close = close_by_date[expected_iso]
        point_delta = current_close - previous_close
        percent_delta = point_delta / previous_close * Decimal("100")
        derived = {
            "point_delta_decimal": str(point_delta),
            "percent_delta_decimal": str(percent_delta),
            "point_delta_value_int_scale_10000": _scaled(point_delta),
            "percent_delta_value_int_scale_10000": _scaled(percent_delta),
            "available_at_rule": "max(current_close,previous_close)_available_at",
            "source_value_only": True,
        }
    return {
        "entity": market_entity,
        "requested_dates": [previous_iso, expected_iso],
        "row_count_by_date": {iso: len(by_date[iso]) for iso in (previous_iso, expected_iso)},
        "close_pair_available": pair_available,
        "close_by_date": {key: str(value) for key, value in sorted(close_by_date.items())},
        "close_source_column_by_date": close_source_column,
        "market_change_non_null": {
            "point_delta": sum(_not_none(row[4]) for row in rows),
            "percent_delta": sum(_not_none(row[5]) for row in rows),
        },
        "derived_values": derived,
        "derivation_contract": classify_feature_gap("market_indices.漲跌點數"),
    }


def _technical_evidence(
    technical_rows: Sequence[Sequence[Any]],
    daily_rows: Sequence[Sequence[Any]],
    *,
    symbols: Sequence[str],
) -> dict[str, Any]:
    return {
        "requested_symbol_count": len(symbols),
        "technical_row_count": len(technical_rows),
        "daily_price_row_count": len(daily_rows),
        "technical_change_non_null": {
            "simplified": sum(_not_none(row[2]) for row in technical_rows),
            "direction": sum(_not_none(row[3]) for row in technical_rows),
            "price_delta": sum(_not_none(row[4]) for row in technical_rows),
        },
        "daily_price_source_non_null": {
            "direction": sum(_not_none(row[2]) for row in daily_rows),
            "price_delta": sum(_not_none(row[3]) for row in daily_rows),
            "close": sum(_not_none(row[4]) for row in daily_rows),
        },
        "numeric_mapping_allowed": False,
        "resolution": "legacy_direction_or_duplicate_not_numeric",
        "contract": classify_feature_gap("technical_indicators.涨跌"),
    }


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _scaled(value: Decimal) -> int:
    return int(
        (value * Decimal("10000")).to_integral_value(
            rounding=ROUND_HALF_EVEN
        )
    )


def _not_none(value: object) -> int:
    return int(value is not None)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
