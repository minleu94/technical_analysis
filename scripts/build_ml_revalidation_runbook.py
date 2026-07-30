"""Build a repeatable ML shadow revalidation runbook."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_module.ml_revalidation_runbook_service import MLRevalidationRunbookService, VALID_TRIGGERS


def _taipei_today_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Taipei")).date().isoformat()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--trigger", choices=sorted(VALID_TRIGGERS), required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--current-model-id", default="rule-champion-v1")
    parser.add_argument("--training-as-of", default=None)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    runbook = MLRevalidationRunbookService().build(
        run_id=args.run_id,
        trigger=args.trigger,
        dataset_id=args.dataset_id,
        current_model_id=args.current_model_id,
        training_as_of=args.training_as_of or _taipei_today_iso(),
        owner=args.owner,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(runbook.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(runbook.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
