import importlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pytest

from data_module.official_market_event_backfill import (
    OFFICIAL_MARKET_ENDPOINTS,
    OfficialMarketEventBackfillBuilder,
    OfficialMarketEventBackfillRequest,
    OfficialMarketEventPublication,
    RawOfficialResponse,
    parse_official_market_events,
)


_OFFICIAL_FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "official_market_events"
)


class _OfficialFixtureFetcher:
    def __init__(
        self,
        *,
        overrides: dict[str, bytes] | None = None,
    ) -> None:
        self._overrides = overrides or {}
        self.calls: list[tuple[str, int]] = []

    def fetch(
        self,
        endpoint: object,
        request_year: int,
        *,
        timeout_seconds: int,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> RawOfficialResponse:
        del timeout_seconds, max_attempts, retry_delay_seconds
        parser_id = str(getattr(endpoint, "parser_id"))
        self.calls.append((parser_id, request_year))
        payload = self._overrides.get(parser_id)
        if payload is None:
            fixture_by_parser = {
                "twse_twtawu.v1": "twse_twtawu_2024.json",
                "tpex_sprcHis.v1": "tpex_sprchis_2024.json",
                "twse_twt49u.v1": "twse_twt49u_2024.json",
                "twse_twtauu.v1": "twse_twtauu_2024.json",
            }
            payload = (
                _OFFICIAL_FIXTURE_ROOT / fixture_by_parser[parser_id]
            ).read_bytes()
        parameters = getattr(endpoint, "parameters_for_year")(request_year)
        return RawOfficialResponse(
            endpoint=endpoint,
            request_year=request_year,
            request_parameters=tuple(sorted(parameters.items())),
            source_url=(
                f"{getattr(endpoint, 'endpoint_url')}?"
                f"{urlencode(parameters)}"
            ),
            retrieved_at="2026-07-30T16:00:00+00:00",
            http_status=200,
            content_type="application/json",
            http_date="Thu, 30 Jul 2026 16:00:00 GMT",
            etag=None,
            last_modified=None,
            payload=payload,
        )


def _raw_fixture(
    parser_id: str,
    fixture_name: str,
    *,
    request_year: int,
) -> RawOfficialResponse:
    endpoint = next(
        item
        for item in OFFICIAL_MARKET_ENDPOINTS
        if item.parser_id == parser_id
    )
    parameters = endpoint.parameters_for_year(request_year)
    return RawOfficialResponse(
        endpoint=endpoint,
        request_year=request_year,
        request_parameters=tuple(sorted(parameters.items())),
        source_url=f"{endpoint.endpoint_url}?{urlencode(parameters)}",
        retrieved_at="2026-07-30T16:00:00+00:00",
        http_status=200,
        content_type="application/json",
        http_date=None,
        etag=None,
        last_modified=None,
        payload=(_OFFICIAL_FIXTURE_ROOT / fixture_name).read_bytes(),
    )


def _module():
    try:
        return importlib.import_module("data_module.corporate_action_availability_history")
    except ModuleNotFoundError:
        return None


def _event(**overrides: str) -> dict[str, str]:
    row = {
        "source_event_id": "evt-1",
        "source_id": "corporate_action.ex_dividend_timeline",
        "source_version": "official-v1",
        "source_hash": "a" * 64,
        "content_hash": "b" * 64,
        "symbol": "2330",
        "event_type": "ex_dividend",
        "event_date": "2025-06-01",
        "announcement_date": "2025-06-10",
        "available_date": "2025-06-10",
        "effective_date": "2025-06-20",
        "quality_tier": "official",
        "revision": "1",
    }
    row.update(overrides)
    return row


def test_event_announcement_available_and_effective_dates_remain_distinct() -> None:
    module = _module()
    assert module is not None, "corporate timeline contract is missing"
    result = module.build_corporate_action_availability_history(
        evidence_rows=(_event(),),
        coverage_rows=(
            {
                "source_id": "corporate_action.ex_dividend_timeline",
                "coverage_start": "2025-01-01",
                "coverage_end": "2025-12-31",
                "quality": "official",
            },
        ),
        as_of_date=date(2025, 12, 31),
    )

    record = result.records[0]
    assert record.event_date == date(2025, 6, 1)
    assert record.announcement_at == date(2025, 6, 10)
    assert record.available_at == date(2025, 6, 10)
    assert record.effective_from == date(2025, 6, 20)
    assert result.visible_as_of(date(2025, 6, 5)) == ()
    assert result.visible_as_of(date(2025, 6, 10)) == (record,)


def test_restriction_release_is_a_new_event_and_coverage_is_source_typed() -> None:
    module = _module()
    assert module is not None, "corporate timeline contract is missing"
    result = module.build_corporate_action_availability_history(
        evidence_rows=(
            _event(
                source_event_id="restrict-1",
                source_id="microstructure.disposition_stock",
                event_type="restriction_start",
                event_date="2025-07-01",
                announcement_date="2025-06-28",
                available_date="2025-06-28",
                effective_date="2025-07-01",
            ),
            _event(
                source_event_id="restrict-2",
                source_id="microstructure.disposition_stock",
                source_version="official-v2",
                content_hash="c" * 64,
                event_type="restriction_release",
                event_date="2025-07-10",
                announcement_date="2025-07-09",
                available_date="2025-07-09",
                effective_date="2025-07-10",
            ),
        ),
        coverage_rows=(
            {
                "source_id": "microstructure.disposition_stock",
                "coverage_start": "2025-01-01",
                "coverage_end": "2025-12-31",
                "quality": "official",
            },
            {
                "source_id": "corporate_action.reduction_split_par_value",
                "coverage_start": "",
                "coverage_end": "",
                "quality": "unknown",
            },
        ),
        as_of_date=date(2025, 7, 31),
    )

    assert [record.event_type for record in result.records] == [
        "restriction_start",
        "restriction_release",
    ]
    assert result.coverage_by_source["microstructure.disposition_stock"].total == 2
    unknown = result.coverage_by_source[
        "corporate_action.reduction_split_par_value"
    ]
    assert unknown.quality == "unknown"
    assert unknown.coverage_unknown is True


def test_unmatched_event_is_counted_under_its_source() -> None:
    module = _module()
    assert module is not None, "corporate timeline contract is missing"
    result = module.build_corporate_action_availability_history(
        evidence_rows=(_event(effective_date=""),),
        coverage_rows=(
            {
                "source_id": "corporate_action.ex_dividend_timeline",
                "coverage_start": "2025-01-01",
                "coverage_end": "2025-12-31",
                "quality": "official",
            },
        ),
        as_of_date=date(2025, 12, 31),
    )

    coverage = result.coverage_by_source["corporate_action.ex_dividend_timeline"]
    assert coverage.total == 1
    assert coverage.unmatched == 1


def test_timeline_writer_stays_under_explicit_staging_root(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "corporate timeline contract is missing"
    result = module.build_corporate_action_availability_history(
        evidence_rows=(_event(),),
        coverage_rows=(),
        as_of_date=date(2025, 12, 31),
    )

    outputs = module.write_corporate_action_availability_history(
        result,
        output_root=tmp_path,
    )

    assert set(outputs) == {"timeline", "coverage", "manifest"}
    assert all(path.parent == tmp_path.resolve() for path in outputs.values())
    assert all(path.exists() for path in outputs.values())


def test_timeline_cli_writes_only_explicit_staging_root(tmp_path: Path) -> None:
    events = tmp_path / "events.json"
    coverage = tmp_path / "coverage.json"
    output_root = tmp_path / "staging"
    events.write_text(json.dumps([_event()]), encoding="utf-8")
    coverage.write_text("[]", encoding="utf-8")
    try:
        cli = importlib.import_module("scripts.build_corporate_action_availability_history")
    except ModuleNotFoundError:
        cli = None
    assert cli is not None, "corporate timeline CLI is missing"

    result = cli.main(
        [
            "--evidence-json",
            str(events),
            "--coverage-json",
            str(coverage),
            "--as-of-date",
            "2025-12-31",
            "--output-root",
            str(output_root),
        ]
    )

    assert result == 0
    assert len(tuple(output_root.iterdir())) == 3


def test_timeline_writer_rejects_existing_output_without_overwriting(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "corporate timeline contract is missing"
    existing = tmp_path / "corporate_action_availability_coverage.json"
    existing.write_bytes(b"owner-existing-output")
    result = module.build_corporate_action_availability_history(
        evidence_rows=(_event(),),
        coverage_rows=(),
        as_of_date=date(2025, 12, 31),
    )

    with pytest.raises(FileExistsError, match="corporate_action_output_exists"):
        module.write_corporate_action_availability_history(result, output_root=tmp_path)

    assert existing.read_bytes() == b"owner-existing-output"
    assert {path.name for path in tmp_path.iterdir()} == {existing.name}


def test_timeline_writer_publishes_staged_files_and_cleans_staging(
    tmp_path: Path, monkeypatch,
) -> None:
    module = _module()
    assert module is not None, "corporate timeline contract is missing"
    result = module.build_corporate_action_availability_history(
        evidence_rows=(_event(),), coverage_rows=(), as_of_date=date(2025, 12, 31)
    )
    original_replace = Path.replace
    replacements: list[tuple[str, str]] = []

    def recording_replace(source: Path, target: Path) -> Path:
        replacements.append((source.name, Path(target).name))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", recording_replace)

    outputs = module.write_corporate_action_availability_history(result, output_root=tmp_path)

    assert {target for _, target in replacements} == {path.name for path in outputs.values()}
    assert not tuple(path for path in tmp_path.iterdir() if path.name.startswith(".corporate-action-"))


def test_timeline_writer_rejects_output_under_forbidden_root(tmp_path: Path) -> None:
    module = _module()
    assert module is not None, "corporate timeline contract is missing"
    forbidden = tmp_path / "formal-data"
    output_root = forbidden / "output" / "corporate-action"
    result = module.build_corporate_action_availability_history(
        evidence_rows=(_event(),), coverage_rows=(), as_of_date=date(2025, 12, 31)
    )

    with pytest.raises(ValueError, match="corporate_action_output_forbidden_root"):
        module.write_corporate_action_availability_history(
            result, output_root=output_root, forbidden_roots=(forbidden,)
        )

    assert not forbidden.exists()


def test_timeline_cli_rejects_output_under_configured_data_root(
    tmp_path: Path, monkeypatch,
) -> None:
    events = tmp_path / "events.json"
    coverage = tmp_path / "coverage.json"
    formal_root = tmp_path / "formal-data"
    output_root = formal_root / "output" / "corporate-action"
    events.write_text(json.dumps([_event()]), encoding="utf-8")
    coverage.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("DATA_ROOT", str(formal_root))
    cli = importlib.import_module("scripts.build_corporate_action_availability_history")

    with pytest.raises(ValueError, match="corporate_action_output_forbidden_root"):
        cli.main(
            [
                "--evidence-json", str(events),
                "--coverage-json", str(coverage),
                "--as-of-date", "2025-12-31",
                "--output-root", str(output_root),
            ]
        )

    assert not formal_root.exists()


@pytest.mark.parametrize(
    ("label", "invalid_payload"),
    (("evidence", {}), ("coverage", ["not-an-object"])),
)
def test_timeline_cli_rejects_invalid_json_rows_before_creating_output(
    tmp_path: Path, label: str, invalid_payload: object,
) -> None:
    events = tmp_path / "events.json"
    coverage = tmp_path / "coverage.json"
    output_root = tmp_path / "staging"
    events.write_text(json.dumps([_event()]), encoding="utf-8")
    coverage.write_text("[]", encoding="utf-8")
    input_path = events if label == "evidence" else coverage
    input_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
    cli = importlib.import_module("scripts.build_corporate_action_availability_history")

    with pytest.raises(ValueError, match=f"corporate_action_{label}_rows_invalid"):
        cli.main(
            [
                "--evidence-json", str(events),
                "--coverage-json", str(coverage),
                "--as-of-date", "2025-12-31",
                "--output-root", str(output_root),
            ]
        )

    assert not output_root.exists()


@pytest.mark.parametrize(
    ("label", "failure", "expected_error"),
    (
        ("evidence", "malformed", "corporate_action_evidence_json_invalid"),
        ("coverage", "malformed", "corporate_action_coverage_json_invalid"),
        ("evidence", "missing", "corporate_action_evidence_read_failed"),
        ("coverage", "missing", "corporate_action_coverage_read_failed"),
    ),
)
def test_timeline_cli_rejects_unreadable_json_before_creating_output(
    tmp_path: Path, label: str, failure: str, expected_error: str,
) -> None:
    events = tmp_path / "events.json"
    coverage = tmp_path / "coverage.json"
    output_root = tmp_path / "staging"
    events.write_text(json.dumps([_event()]), encoding="utf-8")
    coverage.write_text("[]", encoding="utf-8")
    input_path = events if label == "evidence" else coverage
    if failure == "malformed":
        input_path.write_text("[{", encoding="utf-8")
    else:
        input_path.unlink()
    cli = importlib.import_module("scripts.build_corporate_action_availability_history")

    with pytest.raises(ValueError, match=expected_error):
        cli.main(
            [
                "--evidence-json", str(events),
                "--coverage-json", str(coverage),
                "--as-of-date", "2025-12-31",
                "--output-root", str(output_root),
            ]
        )

    assert not output_root.exists()


def test_timeline_cli_rejects_invalid_as_of_date_before_reading_json_or_creating_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "staging"
    cli = importlib.import_module("scripts.build_corporate_action_availability_history")

    def fail_if_json_is_loaded(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("json_loader_called_before_as_of_date_validation")

    monkeypatch.setattr(cli, "_load_json_rows", fail_if_json_is_loaded)

    with pytest.raises(ValueError, match="^corporate_action_as_of_date_invalid$"):
        cli.main(
            [
                "--evidence-json", str(tmp_path / "events.json"),
                "--coverage-json", str(tmp_path / "coverage.json"),
                "--as-of-date", "2025-02-30",
                "--output-root", str(output_root),
            ]
        )

    assert not output_root.exists()


def test_twse_halt_resume_backfill_splits_future_resume_from_halt() -> None:
    events, raw_count = parse_official_market_events(
        _raw_fixture(
            "twse_twtawu.v1",
            "twse_twtawu_2024.json",
            request_year=2024,
        )
    )

    assert raw_count == 1
    assert [event.event_type for event in events] == [
        "trading_halt",
        "trading_resume",
    ]
    halt, resume = events
    assert halt.effective_at == "2024-04-18T08:00:00+08:00"
    assert halt.available_at == halt.effective_at
    assert resume.effective_at == "2024-04-19T08:00:00+08:00"
    assert "resume" not in halt.source_record
    assert halt.event_chain_id == resume.event_chain_id
    assert halt.predecessor_event_id is None
    assert resume.predecessor_event_id == halt.event_id
    assert halt.formal_trading_restriction_allowed is True
    assert halt.formal_label_ledger_allowed is False


def test_twse_halt_resume_accepts_linked_cross_year_continuation() -> None:
    events, raw_count = parse_official_market_events(
        _raw_fixture(
            "twse_twtawu.v1",
            "twse_twtawu_2016_cross_year.json",
            request_year=2016,
        )
    )

    assert raw_count == 1
    halt, resume = events
    assert halt.effective_at == "2016-12-30T08:00:00+08:00"
    assert resume.effective_at == "2017-01-03T08:00:00+08:00"
    assert halt.event_chain_id == resume.event_chain_id
    assert resume.predecessor_event_id == halt.event_id
    assert halt.revision_id == halt.source_record_hash
    assert resume.revision_id == resume.source_record_hash


def test_tpex_sprchis_legacy_schema_preserves_intraday_effective_times() -> None:
    events, raw_count = parse_official_market_events(
        _raw_fixture(
            "tpex_sprcHis.v1",
            "tpex_sprchis_2014.json",
            request_year=2014,
        )
    )

    assert raw_count == 1
    assert [event.effective_at for event in events] == [
        "2014-01-23T08:30:00+08:00",
        "2014-01-23T13:30:00+08:00",
    ]
    assert {event.symbol for event in events} == {"3085"}


@pytest.mark.parametrize(
    ("parser_id", "fixture_name", "event_type"),
    (
        (
            "twse_twt49u.v1",
            "twse_twt49u_2024.json",
            "ex_right_dividend_result",
        ),
        (
            "twse_twtauu.v1",
            "twse_twtauu_2024.json",
            "capital_reduction_resume_result",
        ),
    ),
)
def test_post_event_calculation_tables_are_label_ledger_only(
    parser_id: str,
    fixture_name: str,
    event_type: str,
) -> None:
    events, raw_count = parse_official_market_events(
        _raw_fixture(
            parser_id,
            fixture_name,
            request_year=2024,
        )
    )

    assert raw_count == 1
    event = events[0]
    assert event.event_type == event_type
    assert event.result_only is True
    assert event.formal_label_ledger_allowed is True
    assert event.formal_trading_restriction_allowed is False
    assert event.available_at.endswith("T23:59:59+08:00")
    assert event.available_at > event.effective_at
    assert all("最近一次申報" not in key for key in event.source_record)


def test_capital_reduction_revisions_preserve_vintages_and_supersedes() -> None:
    events, raw_count = parse_official_market_events(
        _raw_fixture(
            "twse_twtauu.v1",
            "twse_twtauu_2014_revisions.json",
            request_year=2014,
        )
    )

    assert raw_count == 2
    assert len(events) == 2
    original, revised = events
    assert original.natural_key == revised.natural_key
    assert original.event_id == revised.event_id
    assert original.revision_id != revised.revision_id
    assert original.announced_at == "2014-08-20T23:59:59+08:00"
    assert original.available_at == "2014-09-09T23:59:59+08:00"
    assert revised.announced_at == "2014-09-22T23:59:59+08:00"
    assert revised.available_at == revised.announced_at
    assert original.supersedes_revision_id is None
    assert revised.supersedes_revision_id == original.revision_id
    assert original.source_record["名稱"] == "南科"
    assert revised.source_record["名稱"] == "南亞科"


def test_same_available_revisions_keep_stable_order_and_ambiguity() -> None:
    events, raw_count = parse_official_market_events(
        _raw_fixture(
            "twse_twtauu.v1",
            "twse_twtauu_2015_same_availability.json",
            request_year=2015,
        )
    )

    assert raw_count == 3
    assert len(events) == 3
    first, second, third = events
    assert first.available_at == second.available_at
    assert first.available_at == "2015-03-20T23:59:59+08:00"
    assert first.announced_at < second.announced_at
    assert first.revision_availability_ambiguous is True
    assert second.revision_availability_ambiguous is True
    assert third.revision_availability_ambiguous is False
    assert [event.source_row_ordinal for event in events] == [1, 2, 3]
    assert second.supersedes_revision_id == first.revision_id
    assert third.supersedes_revision_id == second.revision_id
    assert third.available_at == "2015-03-31T23:59:59+08:00"


def test_parser_rejects_endpoint_that_ignored_requested_year() -> None:
    with pytest.raises(
        ValueError,
        match="ignored requested year|out-of-range",
    ):
        parse_official_market_events(
            _raw_fixture(
                "twse_twtawu.v1",
                "twse_twtawu_2024.json",
                request_year=2014,
            )
        )


def test_twse_current_year_range_stops_at_retrieval_date() -> None:
    endpoint = next(
        item
        for item in OFFICIAL_MARKET_ENDPOINTS
        if item.parser_id == "twse_twtawu.v1"
    )

    parameters = endpoint.parameters_for_year(
        2026,
        query_end_date=date(2026, 7, 30),
    )

    assert parameters["startDate"] == "20260101"
    assert parameters["endDate"] == "20260730"


def test_twse_explicit_no_data_is_zero_rows_not_an_accepted_event() -> None:
    events, raw_count = parse_official_market_events(
        _raw_fixture(
            "twse_twt49u.v1",
            "twse_explicit_no_data.json",
            request_year=2014,
        )
    )

    assert events == ()
    assert raw_count == 0


def test_twse_anomalous_status_fails_closed() -> None:
    raw = _raw_fixture(
        "twse_twt49u.v1",
        "twse_explicit_no_data.json",
        request_year=2014,
    )
    anomalous = RawOfficialResponse(
        endpoint=raw.endpoint,
        request_year=raw.request_year,
        request_parameters=raw.request_parameters,
        source_url=raw.source_url,
        retrieved_at=raw.retrieved_at,
        http_status=raw.http_status,
        content_type=raw.content_type,
        http_date=raw.http_date,
        etag=raw.etag,
        last_modified=raw.last_modified,
        payload=json.dumps(
            {"stat": "系統異常，查無資料，請稍後再試"},
            ensure_ascii=False,
        ).encode("utf-8"),
    )

    with pytest.raises(ValueError, match="stat is not OK"):
        parse_official_market_events(anomalous)


def test_official_backfill_publishes_immutable_raw_and_atomic_latest(
    tmp_path: Path,
) -> None:
    fetcher = _OfficialFixtureFetcher()
    publication = OfficialMarketEventBackfillBuilder(
        fetcher=fetcher,
        now=lambda: datetime(
            2026,
            7,
            30,
            16,
            1,
            tzinfo=timezone.utc,
        ),
        sleep=lambda _: None,
    ).build(
        OfficialMarketEventBackfillRequest(
            output_root=tmp_path / "release_v4",
            start_year=2024,
            end_year=2024,
            request_delay_seconds=0,
        )
    )

    assert publication.raw_request_count == 4
    assert publication.canonical_event_count == 6
    assert publication.new_event_count == 6
    assert len(fetcher.calls) == 4
    manifest = json.loads(
        publication.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["status"] == "formal_source_publication"
    assert manifest["safety"]["active_sqlite_written"] is False
    assert manifest["safety"]["immutable_raw_responses"] is True
    assert (
        manifest["safety"]["result_tables_label_ledger_only"] is True
    )
    assert (
        manifest["safety"]["unlinked_revision_fails_closed"] is True
    )
    assert len(manifest["coverage"]) == 4
    assert all(
        row["complete_year_coverage"] is True
        for row in manifest["coverage"]
    )
    pointer = json.loads(
        publication.latest_manifest_path.read_text(encoding="utf-8")
    )
    assert pointer["publication_id"] == publication.publication_id
    assert pointer["manifest_hash"] == publication.manifest_hash
    raw_files = tuple(
        publication.publication_directory.glob(
            "raw/*/year=2024/response.json"
        )
    )
    assert len(raw_files) == 4
    assert not tuple(
        (tmp_path / "release_v4").glob(
            ".official-market-events-*"
        )
    )


def test_official_no_data_response_keeps_raw_hash_and_zero_row_coverage(
    tmp_path: Path,
) -> None:
    no_data_payload = (
        _OFFICIAL_FIXTURE_ROOT / "twse_explicit_no_data.json"
    ).read_bytes()
    publication = OfficialMarketEventBackfillBuilder(
        fetcher=_OfficialFixtureFetcher(
            overrides={"twse_twt49u.v1": no_data_payload}
        ),
        now=lambda: datetime(
            2026,
            7,
            30,
            16,
            1,
            tzinfo=timezone.utc,
        ),
        sleep=lambda _: None,
    ).build(
        OfficialMarketEventBackfillRequest(
            output_root=tmp_path / "release_v4",
            start_year=2024,
            end_year=2024,
            request_delay_seconds=0,
        )
    )

    manifest = json.loads(
        publication.manifest_path.read_text(encoding="utf-8")
    )
    coverage = next(
        row
        for row in manifest["coverage"]
        if row["source_id"] == "twse.TWT49U.ex_right_dividend_result"
    )
    assert coverage["official_no_data_response_count"] == 1
    assert coverage["raw_row_count"] == 0
    assert coverage["parsed_event_count"] == 0
    raw_index = [
        json.loads(line)
        for line in (
            publication.publication_directory / "raw_index.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    no_data_entry = next(
        row
        for row in raw_index
        if row["source_id"] == "twse.TWT49U.ex_right_dividend_result"
    )
    assert no_data_entry["response_classification"] == "official_no_data"
    assert no_data_entry["response_sha256"].startswith("sha256:")


def test_official_backfill_is_append_only_across_exact_replay(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "release_v4"
    builder = OfficialMarketEventBackfillBuilder(
        fetcher=_OfficialFixtureFetcher(),
        now=lambda: datetime(
            2026,
            7,
            30,
            16,
            2,
            tzinfo=timezone.utc,
        ),
        sleep=lambda _: None,
    )
    request = OfficialMarketEventBackfillRequest(
        output_root=output_root,
        start_year=2024,
        end_year=2024,
        request_delay_seconds=0,
    )

    first = builder.build(request)
    second = builder.build(request)

    assert second.publication_id != first.publication_id
    assert second.canonical_event_count == first.canonical_event_count
    assert second.new_event_count == 0
    second_manifest = json.loads(
        second.manifest_path.read_text(encoding="utf-8")
    )
    assert second_manifest["parent_manifest_hash"] == first.manifest_hash
    assert (
        second_manifest["canonical_events"]["exact_duplicate_count"]
        == first.canonical_event_count
    )
    assert first.publication_directory.exists()
    assert second.publication_directory.exists()


def test_unlinked_revision_fails_without_moving_latest_pointer(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "release_v4"
    request = OfficialMarketEventBackfillRequest(
        output_root=output_root,
        start_year=2024,
        end_year=2024,
        request_delay_seconds=0,
    )
    first = OfficialMarketEventBackfillBuilder(
        fetcher=_OfficialFixtureFetcher(),
        now=lambda: datetime(
            2026,
            7,
            30,
            16,
            3,
            tzinfo=timezone.utc,
        ),
        sleep=lambda _: None,
    ).build(request)
    original_pointer = first.latest_manifest_path.read_bytes()
    revised = json.loads(
        (
            _OFFICIAL_FIXTURE_ROOT / "twse_twt49u_2024.json"
        ).read_text(encoding="utf-8")
    )
    reference_price_index = revised["fields"].index("除權息參考價")
    revised["data"][0][reference_price_index] = "927.40"
    revised_payload = json.dumps(
        revised,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    conflicting_fetcher = _OfficialFixtureFetcher(
        overrides={"twse_twt49u.v1": revised_payload}
    )

    with pytest.raises(ValueError, match="unlinked_revision_conflict"):
        OfficialMarketEventBackfillBuilder(
            fetcher=conflicting_fetcher,
            now=lambda: datetime(
                2026,
                7,
                30,
                16,
                4,
                tzinfo=timezone.utc,
            ),
            sleep=lambda _: None,
        ).build(request)

    assert first.latest_manifest_path.read_bytes() == original_pointer
    assert len(tuple((output_root / "runs").iterdir())) == 1
    assert not tuple(output_root.glob(".official-market-events-*"))
    quarantines = tuple((output_root / "quarantine").iterdir())
    assert len(quarantines) == 1
    failure_manifest = json.loads(
        (quarantines[0] / "failure_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert failure_manifest["status"] == "rejected_failure_custody"
    assert failure_manifest["safety"]["formal_publication"] is False
    assert failure_manifest["safety"]["latest_manifest_updated"] is False
    assert failure_manifest["raw_index"]["response_count"] == 4

    class _NoNetworkFetcher:
        def fetch(self, *args: object, **kwargs: object) -> RawOfficialResponse:
            raise AssertionError("raw custody replay must not fetch network")

    replay = OfficialMarketEventBackfillBuilder(
        fetcher=_NoNetworkFetcher(),
        now=lambda: datetime(
            2026,
            7,
            30,
            16,
            5,
            tzinfo=timezone.utc,
        ),
        sleep=lambda _: None,
    ).build(
        OfficialMarketEventBackfillRequest(
            output_root=tmp_path / "replayed-release-v4",
            raw_custody=quarantines[0],
            start_year=2024,
            end_year=2024,
            request_delay_seconds=0,
        )
    )
    replay_manifest = json.loads(
        replay.manifest_path.read_text(encoding="utf-8")
    )
    assert (
        replay_manifest["request"]["raw_custody_reused_response_count"]
        == 4
    )
    assert replay_manifest["request"]["network_request_count"] == 0


def test_official_backfill_cli_emits_hash_bound_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    publication_dir = tmp_path / "runs" / "publication-1"
    publication_dir.mkdir(parents=True)
    manifest_path = publication_dir / "manifest.json"
    latest_path = tmp_path / "latest_manifest.json"
    events_path = publication_dir / "canonical" / "events.jsonl"
    events_path.parent.mkdir()
    manifest_path.write_text("{}\n", encoding="utf-8")
    latest_path.write_text("{}\n", encoding="utf-8")
    events_path.write_text("", encoding="utf-8")
    publication = OfficialMarketEventPublication(
        publication_id="publication-1",
        publication_directory=publication_dir,
        manifest_path=manifest_path,
        latest_manifest_path=latest_path,
        manifest_hash="sha256:" + ("a" * 64),
        manifest_file_hash="sha256:" + ("b" * 64),
        canonical_events_path=events_path,
        canonical_events_hash="sha256:" + ("c" * 64),
        canonical_event_count=6,
        new_event_count=6,
        raw_request_count=4,
    )
    cli = importlib.import_module(
        "scripts.build_official_market_event_backfill"
    )

    class _Builder:
        def build(
            self,
            request: OfficialMarketEventBackfillRequest,
        ) -> OfficialMarketEventPublication:
            assert request.start_year == 2024
            assert request.end_year == 2024
            return publication

    monkeypatch.setattr(
        cli,
        "OfficialMarketEventBackfillBuilder",
        _Builder,
    )

    assert (
        cli.main(
            [
                "--output-root",
                str(tmp_path),
                "--start-year",
                "2024",
                "--end-year",
                "2024",
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "published"
    assert summary["manifest_hash"] == publication.manifest_hash
    assert summary["canonical_event_count"] == 6
    assert summary["active_sqlite_written"] is False
