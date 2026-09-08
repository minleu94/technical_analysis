"""獨立以 Decimal 核對 daily-price overlay impact 的 h20 return evidence。

此工具只讀 impact JSON，不讀取或寫入 D 槽來源，也不重新計算 feature 或
label。它重新以 artifact 保存的 entry／exit／benchmark 價格核對整數 bp
與 25+55 bp 成本，輸出一份不可覆寫的 audit JSON。
"""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_module.ml_daily_price_overlay_consumer import (  # noqa: E402
    DailyPriceOverlayConsumerError,
    load_daily_price_overlay_impact,
)


AUDIT_SCHEMA_VERSION = "portfolio-ml-daily-price-overlay-impact-audit.v1"
BUY_COST_BP = 25
SELL_COST_BP = 55
TRANSACTION_COST_BP = BUY_COST_BP + SELL_COST_BP
_SHA256_PREFIX = "sha256:"


class OverlayImpactAuditError(ValueError):
    """impact return evidence 不符合獨立 Decimal audit 契約。"""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _payload_hash(value: object) -> str:
    return _SHA256_PREFIX + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return _SHA256_PREFIX + digest.hexdigest()


def _decimal(value: object, *, field_name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise OverlayImpactAuditError(f"{field_name} is missing")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OverlayImpactAuditError(f"{field_name} is not Decimal") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise OverlayImpactAuditError(f"{field_name} is not positive finite Decimal")
    return parsed


def _return_bp(start: Decimal, end: Decimal) -> int:
    return int(
        (((end / start) - Decimal(1)) * Decimal(10_000)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_EVEN,
        )
    )


def _required_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OverlayImpactAuditError(f"{field_name} is not an integer")
    return value


def audit_overlay_impact(
    *,
    impact_path: Path,
    output_path: Path,
) -> Path:
    """獨立核對每列 candidate label evidence，並原子保存 audit。"""

    impact_resolved = impact_path.resolve()
    try:
        payload = load_daily_price_overlay_impact(impact_resolved)
    except (DailyPriceOverlayConsumerError, OSError, ValueError) as exc:
        raise OverlayImpactAuditError("impact artifact cannot be verified") from exc
    if payload.get("schema_version") != "portfolio-ml-daily-price-overlay-impact.v2":
        raise OverlayImpactAuditError("Decimal audit requires impact v2")
    impacts = payload.get("impacts")
    if not isinstance(impacts, list) or not impacts:
        raise OverlayImpactAuditError("impact rows are missing")

    verified_rows = 0
    for index, raw_impact in enumerate(impacts):
        if not isinstance(raw_impact, Mapping):
            raise OverlayImpactAuditError(f"impact row {index} is invalid")
        labels = raw_impact.get("labels")
        if not isinstance(labels, Mapping):
            raise OverlayImpactAuditError(f"impact row {index} labels are missing")
        candidate = labels.get("candidate")
        if not isinstance(candidate, Mapping):
            raise OverlayImpactAuditError(f"impact row {index} candidate label is missing")
        evidence = candidate.get("return_evidence")
        if not isinstance(evidence, Mapping):
            raise OverlayImpactAuditError(
                f"impact row {index} return evidence is missing"
            )
        entry = _decimal(
            evidence.get("stock_entry_open"),
            field_name=f"impacts[{index}].stock_entry_open",
        )
        exit_close = _decimal(
            evidence.get("stock_exit_close"),
            field_name=f"impacts[{index}].stock_exit_close",
        )
        benchmark_entry = _decimal(
            evidence.get("benchmark_entry_open"),
            field_name=f"impacts[{index}].benchmark_entry_open",
        )
        benchmark_exit = _decimal(
            evidence.get("benchmark_exit_close"),
            field_name=f"impacts[{index}].benchmark_exit_close",
        )
        stock_return = _return_bp(entry, exit_close)
        benchmark_return = _return_bp(benchmark_entry, benchmark_exit)
        if _required_int(
            evidence.get("stock_return_bp"),
            field_name=f"impacts[{index}].stock_return_bp",
        ) != stock_return:
            raise OverlayImpactAuditError(
                f"impact row {index} stock return evidence mismatch"
            )
        if _required_int(
            evidence.get("benchmark_return_bp"),
            field_name=f"impacts[{index}].benchmark_return_bp",
        ) != benchmark_return:
            raise OverlayImpactAuditError(
                f"impact row {index} benchmark return evidence mismatch"
            )
        if evidence.get("buy_cost_bp") != BUY_COST_BP or evidence.get("sell_cost_bp") != SELL_COST_BP:
            raise OverlayImpactAuditError(f"impact row {index} cost components mismatch")
        if evidence.get("transaction_cost_bp") != TRANSACTION_COST_BP:
            raise OverlayImpactAuditError(f"impact row {index} transaction cost mismatch")
        expected_excess = stock_return - benchmark_return - TRANSACTION_COST_BP
        if candidate.get("benchmark_excess_return_bp") != expected_excess:
            raise OverlayImpactAuditError(
                f"impact row {index} candidate excess return mismatch"
            )
        verified_rows += 1

    body: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "verified_decimal_return_evidence",
        "read_only": True,
        "impact_path": str(impact_resolved),
        "impact_file_sha256": _file_sha256(impact_resolved),
        "impact_hash": payload["impact_hash"],
        "rows_verified": verified_rows,
        "cost_policy": {
            "buy_cost_bp": BUY_COST_BP,
            "sell_cost_bp": SELL_COST_BP,
            "transaction_cost_bp": TRANSACTION_COST_BP,
        },
        "arithmetic": {
            "numeric_type": "Decimal",
            "rounding": "ROUND_HALF_EVEN to integer bp",
            "formula": "stock_return_bp - benchmark_return_bp - transaction_cost_bp",
        },
        "source_not_mutated": True,
    }
    body["audit_hash"] = _payload_hash(body)
    output = output_path.resolve()
    if output == impact_resolved or impact_resolved in output.parents:
        raise OverlayImpactAuditError("audit output must be outside impact source")
    if output.exists():
        try:
            if os.path.samefile(output, impact_resolved):
                raise OverlayImpactAuditError(
                    "audit output aliases the impact source"
                )
        except FileNotFoundError:
            pass
    encoded = (_canonical_json(body) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.read_bytes() != encoded:
            raise FileExistsError(
                f"audit output already exists with different content: {output}"
            )
        return output
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = audit_overlay_impact(
        impact_path=args.impact,
        output_path=args.output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "output_path": str(output),
                "audit_hash": payload["audit_hash"],
                "impact_hash": payload["impact_hash"],
                "rows_verified": payload["rows_verified"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
