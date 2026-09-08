"""以當下 clock 發布 PIT formal sector sidecar 並執行 assembler readback。

這個入口不接受日期或 decision timestamp 覆寫；它只會使用執行當下的
UTC clock。cutoff、source custody、license scope 或 coverage 任一未成立時，
publisher 只保存 blocked receipt 並回傳非零狀態，不會把 candidate 當成
Formal input。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_pit_sector_publisher import (  # noqa: E402
    publish_formal_pit_sector_sidecar,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-path", type=Path, required=True)
    parser.add_argument("--denominator-path", type=Path, required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    decision_at = datetime.now(timezone.utc)
    try:
        result = publish_formal_pit_sector_sidecar(
            handoff_path=args.handoff_path,
            denominator_path=args.denominator_path,
            publication_root=args.publication_root,
            decision_at=decision_at,
            now=decision_at,
        )
    except Exception as error:  # noqa: BLE001 - emit bounded operational blocker
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "producer": "scripts.publish_formal_pit_sector_sidecar",
                    "reason": str(error).splitlines()[0][:300],
                    "formal_ready": False,
                    "candidate_only": True,
                    "formal_oos_allowed": False,
                    "production_action_allowed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "formal_source_publication" else 2


if __name__ == "__main__":
    raise SystemExit(main())
