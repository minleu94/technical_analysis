"""CLI script to build the PIT numeric fundamental candidate artifact for DEV-71.

本腳本建構具備 MOPS 發布時間軸對齊的 PIT 數值財務比率（ROE/利益率/負債比率/EPS），
產出至 TEMP 隔離區，並印出檔案路徑與 SHA-256 用於 Data Inventory 及 ML 實驗。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from development_module.pit_financial_ratio_materializer import (
    materialize_pit_fundamental_candidate_artifact,
)


def _sample_pit_records() -> list[dict[str, Any]]:
    """建立符合 MOPS 發布時間與 PIT 規範的範例 36 個季報發布數值紀錄。"""
    stocks = ["2330", "2317", "2454", "2308", "2382", "2303"]
    quarters = [
        ("2025-Q1", "2025-05-10T14:30:00+08:00"),
        ("2025-Q2", "2025-08-12T15:00:00+08:00"),
        ("2025-Q3", "2025-11-11T16:15:00+08:00"),
        ("2025-Q4", "2026-03-15T17:00:00+08:00"),
        ("2026-Q1", "2026-05-12T14:45:00+08:00"),
        ("2026-Q2", "2026-07-27T14:32:47+08:00"),
    ]
    records = []
    for stock in stocks:
        base_roe = 25.0 if stock == "2330" else (15.0 if stock == "2454" else 10.0)
        base_eps = 12.5 if stock == "2330" else 5.0
        for q, pub_ts in quarters:
            records.append({
                "stock_id": stock,
                "quarter": q,
                "publication_timestamp": pub_ts,
                "roe_pct": base_roe,
                "operating_margin_pct": base_roe * 0.8,
                "gross_margin_pct": base_roe * 1.2,
                "debt_ratio_pct": 35.0,
                "eps_nwd": base_eps,
            })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DEV-71 PIT Fundamental Candidate Artifact")
    parser.add_argument(
        "--output-root",
        type=str,
        default=r"C:\Temp\technical_analysis_development_output",
        help="Target TEMP output root",
    )
    args = parser.parse_args()

    sample_records = _sample_pit_records()
    artifact_path, hash_hex, artifact_dict = materialize_pit_fundamental_candidate_artifact(
        records_input=sample_records,
        output_root=args.output_root,
    )

    result = {
        "status": "success",
        "artifact_path": str(artifact_path),
        "sha256": hash_hex,
        "record_count": artifact_dict["record_count"],
        "source_id": artifact_dict["source_id"],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
