"""建立下一個自然台北交易日的 Formal／Paper candidate runtime 設定。

這是 scheduler 可呼叫的 Python process boundary。日期只由目前 UTC clock
與 caller pin 的官方 calendar bundle 決定；不接受日期、latest scan 或來源
覆寫參數，也不更新 Windows Task Scheduler 或任何 controlled path。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_module.formal_runtime_roll_forward import main as _main


def main(argv: Sequence[str] | None = None) -> int:
    return _main(argv)


if __name__ == "__main__":  # pragma: no cover - process boundary
    raise SystemExit(main(sys.argv[1:]))
