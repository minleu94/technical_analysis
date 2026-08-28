from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from scripts import qa_technical_indicator_latency as probe


def test_indicator_latency_probe_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    technical_dir = tmp_path / "technical"
    technical_dir.mkdir()
    indicator_path = technical_dir / "2330_indicators.csv"
    pd.DataFrame(
        {
            "日期": ["2026-08-27", "2026-08-28"],
            "證券代號": ["2330", "2330"],
            "收盤價": [900, 901],
        }
    ).to_csv(indicator_path, index=False, encoding="utf-8-sig")
    before = hashlib.sha256(indicator_path.read_bytes()).hexdigest()

    class FakeCalculator:
        def __init__(self, logger=None):
            self.logger = logger

        def calculate_all_indicators(self, frame, stock_id):
            assert stock_id == "2330"
            return frame

    monkeypatch.setattr(probe, "TechnicalIndicatorCalculator", FakeCalculator)
    report = probe.measure_technical_indicator_latency(
        technical_dir=technical_dir,
        stock_ids=("2330",),
        rows=2,
        runs=2,
    )

    assert report["status"] == "measured"
    assert report["read_only"] is True
    assert report["write_attempted"] is False
    assert report["parallelism_enabled"] is False
    assert report["observed_worker_count"] == 1
    assert report["single_writer_required"] is True
    assert report["items"][0]["status"] == "measured"
    assert report["items"][0]["input_rows"] == 2
    assert hashlib.sha256(indicator_path.read_bytes()).hexdigest() == before


def test_indicator_latency_probe_reports_missing_file_without_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    technical_dir = tmp_path / "technical"
    technical_dir.mkdir()
    monkeypatch.setattr(
        probe,
        "TechnicalIndicatorCalculator",
        lambda **_: pytest.fail("missing file must not instantiate calculator"),
    )

    report = probe.measure_technical_indicator_latency(
        technical_dir=technical_dir,
        stock_ids=("2330",),
    )

    assert report["status"] == "blocked"
    assert report["items"][0]["status"] == "missing"
    assert report["items"][0]["reason"] == "indicator_file_missing"
    assert not (technical_dir / "2330_indicators.csv").exists()


def test_indicator_latency_probe_rejects_path_like_stock_id(tmp_path: Path) -> None:
    technical_dir = tmp_path / "technical"
    technical_dir.mkdir()

    report = probe.measure_technical_indicator_latency(
        technical_dir=technical_dir,
        stock_ids=("..",),
    )

    assert report["status"] == "blocked"
    assert report["items"][0]["status"] == "blocked"
    assert "invalid stock id" in report["items"][0]["reason"]


def test_indicator_latency_probe_validates_positive_measurement_options(
    tmp_path: Path,
) -> None:
    technical_dir = tmp_path / "technical"
    technical_dir.mkdir()

    with pytest.raises(ValueError, match="rows"):
        probe.measure_technical_indicator_latency(
            technical_dir=technical_dir,
            stock_ids=("2330",),
            rows=0,
        )
    with pytest.raises(ValueError, match="runs"):
        probe.measure_technical_indicator_latency(
            technical_dir=technical_dir,
            stock_ids=("2330",),
            runs=0,
        )
