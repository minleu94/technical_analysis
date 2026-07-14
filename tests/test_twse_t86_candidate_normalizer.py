import json
from datetime import UTC, datetime

from data_module.twse_t86_candidate_normalizer import normalize_t86_payload


FIELDS = [
    "證券代號", "證券名稱", "外陸資買進股數(不含外資自營商)",
    "外陸資賣出股數(不含外資自營商)", "外陸資買賣超股數(不含外資自營商)",
    "投信買進股數", "投信賣出股數", "投信買賣超股數",
    "自營商買進股數(自行買賣)", "自營商賣出股數(自行買賣)",
    "自營商買賣超股數(自行買賣)", "自營商買進股數(避險)",
    "自營商賣出股數(避險)", "自營商買賣超股數(避險)",
]


def payload(rows, fields=FIELDS):
    return json.dumps({"stat": "OK", "fields": fields, "data": rows}, ensure_ascii=False).encode()


def row(symbol="2330", foreign_buy="1,000"):
    return [symbol, "台積電", foreign_buy, "900", "100", "20", "10", "10", "5", "3", "2", "4", "1", "3"]


def test_normalizer_preserves_missing_and_conserves_rows():
    result = normalize_t86_payload(
        payload([row(), row("合計", "--"), row("2317", "")]),
        observation_date="2026-07-10",
        retrieved_at=datetime(2026, 7, 13, 8, tzinfo=UTC),
    )
    assert result.raw_row_count == 3
    assert result.accepted_count == 1
    assert result.quarantined_count == 1
    assert result.ignored_count == 1
    assert result.raw_row_count == result.accepted_count + result.quarantined_count + result.ignored_count
    assert result.rows[0].quantities["foreign_buy_shares"] == 1000
    assert result.rows[0].first_observed_at.isoformat() == "2026-07-13T08:00:00+00:00"
    assert result.rows[0].available_at is None


def test_duplicate_and_conflict_are_explicit_without_double_counting():
    duplicate = row()
    conflict = row(foreign_buy="2,000")
    result = normalize_t86_payload(
        payload([row(), duplicate, conflict]),
        observation_date="2026-07-10",
        retrieved_at=datetime(2026, 7, 13, 8, tzinfo=UTC),
    )
    assert result.accepted_count == 1
    assert result.duplicate_count == 1
    assert result.conflict_count == 1
    assert result.quarantined_count == 1
    assert result.ignored_count == 1
    assert result.raw_row_count == 3


def test_schema_drift_fails_closed():
    result = normalize_t86_payload(
        payload([row()[:-1]], fields=FIELDS[:-1]),
        observation_date="2026-07-10",
        retrieved_at=datetime(2026, 7, 13, 8, tzinfo=UTC),
    )
    assert result.accepted_count == 0
    assert result.quarantined_count == 1
    assert "schema_drift" in result.warnings


def test_non_universe_security_is_explicitly_ignored_but_reported_as_observed():
    result = normalize_t86_payload(
        payload([row("2330"), row("0050")]),
        observation_date="2026-07-10",
        retrieved_at=datetime(2026, 7, 13, 8, tzinfo=UTC),
        allowed_symbols={"2330", "2317"},
    )
    assert result.accepted_count == 1
    assert result.ignored_count == 1
    assert result.symbols == ("2330",)
    assert result.observed_symbols == ("0050", "2330")
    assert result.ignored[0]["reason"] == "outside_ordinary_stock_universe"
