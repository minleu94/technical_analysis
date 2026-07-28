"""Development Data Inventory CLI 腳本。

讀取 Terra Development Dataset V0 的 Manifest 與 Dataset，輸出 sanitized, field-level 盤點報告至 TEMP。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from development_module.data_inventory import build_development_data_inventory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="Terra Dataset V0 manifest.json 路徑")
    parser.add_argument("--dataset", type=Path, required=True, help="Terra Dataset V0 dataset.json 路徑")
    parser.add_argument("--output-root", type=Path, required=True, help="TEMP 輸出根目錄")
    parser.add_argument("--candidate-artifact", type=Path, action="append", help="可選的研究候選 Artifact JSON 路徑")
    parser.add_argument("--candidate-artifact-sha256", type=str, action="append", help="可選的研究候選 Artifact 預期 SHA-256 哈希值")
    args = parser.parse_args(argv)

    if not args.manifest.is_file():
        parser.error(f"manifest file not found: {args.manifest}")
    if not args.dataset.is_file():
        parser.error(f"dataset file not found: {args.dataset}")

    expected_hashes: dict[str, str] = {}
    if args.candidate_artifact and args.candidate_artifact_sha256:
        if len(args.candidate_artifact) != len(args.candidate_artifact_sha256):
            parser.error("count of --candidate-artifact must match count of --candidate-artifact-sha256")
        for art_p, exp_h in zip(args.candidate_artifact, args.candidate_artifact_sha256):
            expected_hashes[str(art_p.resolve())] = exp_h
            expected_hashes[art_p.name] = exp_h

    result = build_development_data_inventory(
        manifest_path=args.manifest,
        dataset_path=args.dataset,
        output_root=args.output_root,
        candidate_artifacts=args.candidate_artifact,
        candidate_expected_hashes=expected_hashes,
    )

    out_summary = {
        "inventory_id": result.inventory_id,
        "generated_at": result.generated_at,
        "summary": result.summary,
        "report_file_path": str(result.report_file_path),
        "report_file_sha256": result.report_file_sha256,
        "sanitized_projection_path": str(result.sanitized_projection_path),
        "sanitized_projection_sha256": result.sanitized_projection_sha256,
        "formal_eligible": False,
        "production_eligible": False,
        "promotion_eligible": False,
    }
    print(json.dumps(out_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
