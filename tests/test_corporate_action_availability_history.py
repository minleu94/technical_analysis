import importlib
import json
from datetime import date
from pathlib import Path


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
