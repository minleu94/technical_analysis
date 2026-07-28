"""Development ML Experiment Runner CLI 腳本。

讀取 Terra Development Dataset V0，執行指定 Feature Pack 與 Model Family 的 Development-Only ML 實驗。
預設無參數時不執行任何操作 (No-Op)，僅印出使用說明。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from development_module.experiment_contract import (
    PREDEFINED_FEATURE_PACKS,
    DevelopmentExperimentContract,
    DevelopmentExperimentRunner,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="Terra Dataset V0 manifest.json 路徑")
    parser.add_argument("--dataset", type=Path, help="Terra Dataset V0 dataset.json 路徑")
    parser.add_argument("--output-root", type=Path, help="TEMP 輸出根目錄")
    parser.add_argument("--experiment-id", type=str, help="實驗唯一 ID (例如 exp-feature-ablation-v1)")
    parser.add_argument(
        "--feature-pack",
        type=str,
        choices=tuple(PREDEFINED_FEATURE_PACKS.keys()),
        default="core_20",
        help="預定義特徵組合 (core_20, technical_only, price_only, price_technical)",
    )
    parser.add_argument("--feature-ids", type=str, help="自訂特徵 ID (逗號分隔)，覆蓋 feature-pack")
    parser.add_argument(
        "--model-families",
        type=str,
        default="linear_logistic,hist_gradient_boosting",
        help="模型家族 (逗號分隔，預設 linear_logistic,hist_gradient_boosting)",
    )
    parser.add_argument("--candidate-artifact", type=Path, help="可選的研究候選 Artifact JSON 路徑")
    parser.add_argument("--candidate-artifact-sha256", type=str, help="可選的研究候選 Artifact 預期 SHA-256 哈希值")
    args = parser.parse_args(argv)

    if not args.manifest or not args.dataset or not args.output_root or not args.experiment_id:
        print(
            json.dumps(
                {
                    "status": "no_op",
                    "message": "Development ML Experiment Runner: 指定 --manifest, --dataset, --output-root 與 --experiment-id 方可執行實驗。",
                    "available_feature_packs": list(PREDEFINED_FEATURE_PACKS.keys()),
                    "formal_oos_allowed": False,
                    "production_blend_alpha_bp": 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.manifest.is_file():
        parser.error(f"manifest file not found: {args.manifest}")
    if not args.dataset.is_file():
        parser.error(f"dataset file not found: {args.dataset}")

    manifest_data = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    parent_dataset_id = str(manifest_data.get("dataset_id", ""))
    parent_manifest_hash = str(manifest_data.get("manifest_hash", ""))

    if args.feature_ids:
        selected_features = tuple(f.strip() for f in args.feature_ids.split(",") if f.strip())
    else:
        selected_features = PREDEFINED_FEATURE_PACKS[args.feature_pack]

    model_fams = tuple(f.strip() for f in args.model_families.split(",") if f.strip())

    contract = DevelopmentExperimentContract(
        experiment_id=args.experiment_id,
        parent_dataset_id=parent_dataset_id,
        parent_dataset_manifest_hash=parent_manifest_hash,
        feature_ids=selected_features,
        model_families=model_fams,
        candidate_research_only=bool(args.candidate_artifact),
    )

    runner = DevelopmentExperimentRunner()
    result = runner.run(
        manifest_path=args.manifest,
        dataset_path=args.dataset,
        output_root=args.output_root,
        contract=contract,
        candidate_artifact_path=args.candidate_artifact,
        candidate_expected_sha256=args.candidate_artifact_sha256,
    )

    summary = {
        "status": "completed",
        "experiment_id": result.experiment_id,
        "selected_model_family": result.selected_model_family,
        "comparison_conclusion": result.comparison_conclusion,
        "metrics_by_family": result.metrics_by_family,
        "report_file_path": str(result.report_file_path),
        "report_file_sha256": result.report_file_sha256,
        "sanitized_projection_path": str(result.sanitized_projection_path),
        "sanitized_projection_sha256": result.sanitized_projection_sha256,
        "formal_oos_allowed": False,
        "production_blend_alpha_bp": 0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
