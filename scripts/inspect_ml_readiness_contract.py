from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_module.ml_readiness_contract import MLReadinessContractReport, MLReadinessContractService


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="輸出 shadow-only ML readiness contract；不訓練 production model。")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = MLReadinessContractService().build_report()
    rendered = (
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_ml_readiness_contract_markdown(report)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def render_ml_readiness_contract_markdown(report: MLReadinessContractReport) -> str:
    payload = report.to_dict()
    lines = [
        "# ML Readiness Contract",
        "",
        f"- shadow_only={str(payload['shadow_only']).lower()}",
        "- 不訓練 production model",
        "- 不取代 rule-generated signals",
        "- 不改推薦 threshold",
        "- 不執行 auto lifecycle action",
        "- 不提供 trading advice",
        "",
        "## Allowed Roles",
        "",
    ]
    lines.extend(f"- {role}" for role in payload["allowed_ml_roles"])
    lines.extend(["", "## Forbidden Actions", ""])
    lines.extend(f"- {action}" for action in payload["forbidden_actions"])
    lines.extend(["", "## Preconditions", ""])
    lines.extend(f"- {item}" for item in payload["required_preconditions"])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in payload["limitations"])
    return "\n".join(lines)


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
