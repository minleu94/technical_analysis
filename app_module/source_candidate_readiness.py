from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SOURCE_CANDIDATES = ("institutional_flows", "credit_transactions", "tdcc_shareholding")

ACCESS_BOUNDARY = {
    "writes_allowed": False,
    "production_scheduler_allowed": False,
    "scoring_engine_write_allowed": False,
    "investment_effectiveness_claim": False,
}

REPORT_LIMITATIONS = (
    "candidate-only dry-run：只檢查來源候選 readiness，不接入正式策略訊號。",
    "不寫 production DB、不啟用 scheduler、不改 ScoringEngine、不改推薦 threshold 或權重。",
    "decision-time feature 必須有 explicit available_date，且 available_date 不得晚於 decision_date。",
    "缺資料、缺 table、缺 available_date 或 future available_date 只輸出 diagnostics，不補值、不靜默通過。",
)

SOURCE_LABELS = {
    "institutional_flows": "三大法人 source candidate",
    "credit_transactions": "信用交易 source candidate",
    "tdcc_shareholding": "TDCC / 集保庫存 source candidate",
}

REQUIRED_FIELDS = {
    "institutional_flows": (
        "foreign_investor_buy",
        "foreign_investor_sell",
        "foreign_investor_net",
        "investment_trust_buy",
        "investment_trust_sell",
        "investment_trust_net",
        "dealer_buy",
        "dealer_sell",
        "dealer_net",
    ),
    "credit_transactions": ("margin_purchase", "margin_balance", "short_sale", "short_balance"),
    "tdcc_shareholding": (),
}

OPTIONAL_FIELDS = {
    "institutional_flows": (),
    "credit_transactions": ("financing", "securities_lending"),
    "tdcc_shareholding": ("shareholding_tiers", "large_holder_ratio_bp", "retail_holder_ratio_bp", "dispersion_index_bp"),
}

TDCC_CANDIDATE_FIELDS = OPTIONAL_FIELDS["tdcc_shareholding"]

COLUMN_ALIASES = {
    "stock_code": ("stock_code", "symbol", "證券代號", "股票代號"),
    "decision_date": ("decision_date", "as_of_date", "date", "日期"),
    "available_date": ("available_date", "可得日", "公告日"),
    "source_version": ("source_version", "來源版本"),
    "quality": ("quality", "source_quality", "資料品質"),
    "foreign_investor_buy": ("foreign_investor_buy", "外資買進", "外資買超買進"),
    "foreign_investor_sell": ("foreign_investor_sell", "外資賣出", "外資買超賣出"),
    "foreign_investor_net": ("foreign_investor_net", "foreign_investor_net_buy_sell", "外資買賣超", "外資淨買賣"),
    "investment_trust_buy": ("investment_trust_buy", "投信買進"),
    "investment_trust_sell": ("investment_trust_sell", "投信賣出"),
    "investment_trust_net": ("investment_trust_net", "investment_trust_net_buy_sell", "投信買賣超", "投信淨買賣"),
    "dealer_buy": ("dealer_buy", "自營商買進"),
    "dealer_sell": ("dealer_sell", "自營商賣出"),
    "dealer_net": ("dealer_net", "dealer_net_buy_sell", "自營商買賣超", "自營商淨買賣"),
    "margin_purchase": ("margin_purchase", "融資買進", "融資買進張數"),
    "margin_balance": ("margin_balance", "融資餘額", "margin_balance_volume"),
    "short_sale": ("short_sale", "融券賣出", "融券賣出張數"),
    "short_balance": ("short_balance", "融券餘額", "short_balance_volume"),
    "financing": ("financing", "資金融通"),
    "securities_lending": ("securities_lending", "借券", "securities_lending_balance"),
    "shareholding_tiers": ("shareholding_tiers", "持股級距", "股權分散"),
    "large_holder_ratio_bp": ("large_holder_ratio_bp", "大戶比例_bp", "大戶比例基點"),
    "retail_holder_ratio_bp": ("retail_holder_ratio_bp", "散戶比例_bp", "散戶比例基點"),
    "dispersion_index_bp": ("dispersion_index_bp", "分散度_bp", "股權分散度基點"),
}


@dataclass(frozen=True)
class SourceCandidateRow:
    source_id: str
    symbol: str | None = None
    decision_date: str | None = None
    available_date: str | None = None
    source_version: str = ""
    quality: str = "missing"
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "symbol": self.symbol,
            "decision_date": self.decision_date,
            "available_date": self.available_date,
            "source_version": self.source_version,
            "quality": self.quality,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class SourceCandidateReadinessItem:
    source_id: str
    label: str
    status: str
    decision_ready: bool
    row_count: int
    accepted_row_count: int
    blocked_row_count: int
    diagnostics: tuple[str, ...]
    coverage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "label": self.label,
            "status": self.status,
            "decision_ready": self.decision_ready,
            "row_count": self.row_count,
            "accepted_row_count": self.accepted_row_count,
            "blocked_row_count": self.blocked_row_count,
            "diagnostics": list(self.diagnostics),
            "coverage": dict(self.coverage),
        }


@dataclass(frozen=True)
class SourceCandidateReadinessReport:
    generated_at: str
    decision_date: str
    source_mode: str
    items: tuple[SourceCandidateReadinessItem, ...]
    access_boundary: dict[str, bool]
    limitations: tuple[str, ...]
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "decision_date": self.decision_date,
            "source_mode": self.source_mode,
            "items": [item.to_dict() for item in self.items],
            "access_boundary": dict(self.access_boundary),
            "limitations": list(self.limitations),
            "diagnostics": list(self.diagnostics),
        }


class SourceCandidateReadinessService:
    """Read-only readiness dry-run for Phase 3C institutional / credit / TDCC candidates."""

    def __init__(
        self,
        *,
        rows: Iterable[SourceCandidateRow] = (),
        decision_date: str,
        source_mode: str = "in_memory",
        missing_sources: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.rows = tuple(rows)
        self.decision_date = str(decision_date)
        self.source_mode = source_mode
        self.missing_sources = missing_sources or {}

    @classmethod
    def from_sqlite(cls, db_path: Path | str, *, decision_date: str) -> "SourceCandidateReadinessService":
        path = Path(db_path)
        if not path.exists():
            missing_db_sources: dict[str, tuple[str, ...]] = {
                source_id: ("source_not_ingested", "missing_db") for source_id in SOURCE_CANDIDATES
            }
            return cls(
                rows=(),
                decision_date=decision_date,
                source_mode="read_only_sqlite",
                missing_sources=missing_db_sources,
            )

        rows: list[SourceCandidateRow] = []
        missing_table_sources: dict[str, tuple[str, ...]] = {}
        uri = f"file:{path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            table_names = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            for source_id in SOURCE_CANDIDATES:
                if source_id not in table_names:
                    missing_table_sources[source_id] = ("source_not_ingested", "missing_table")
                    continue
                rows.extend(_load_source_rows(conn, source_id, decision_date))
        return cls(
            rows=rows,
            decision_date=decision_date,
            source_mode="read_only_sqlite",
            missing_sources=missing_table_sources,
        )

    def build_report(self) -> SourceCandidateReadinessReport:
        items = tuple(self._build_item(source_id) for source_id in SOURCE_CANDIDATES)
        report_diagnostics = tuple(
            sorted({diagnostic for item in items for diagnostic in item.diagnostics if diagnostic in {"missing_db"}})
        )
        return SourceCandidateReadinessReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            decision_date=self.decision_date,
            source_mode=self.source_mode,
            items=items,
            access_boundary=dict(ACCESS_BOUNDARY),
            limitations=REPORT_LIMITATIONS,
            diagnostics=report_diagnostics,
        )

    def _build_item(self, source_id: str) -> SourceCandidateReadinessItem:
        rows = tuple(row for row in self.rows if row.source_id == source_id)
        missing_diagnostics = tuple(self.missing_sources.get(source_id, ()))
        if not rows:
            diagnostics = _unique((*missing_diagnostics, "source_not_ingested") if missing_diagnostics else ("source_not_ingested",))
            return SourceCandidateReadinessItem(
                source_id=source_id,
                label=SOURCE_LABELS[source_id],
                status="degraded",
                decision_ready=False,
                row_count=0,
                accepted_row_count=0,
                blocked_row_count=0,
                diagnostics=diagnostics,
                coverage=_coverage(source_id, ()),
            )

        accepted = 0
        blocked = 0
        item_diagnostics: list[str] = list(missing_diagnostics)
        accepted_payload_fields: list[str] = []

        for row in rows:
            row_diagnostics = self._row_diagnostics(row)
            if any(_is_blocking_diagnostic(diagnostic) for diagnostic in row_diagnostics):
                blocked += 1
            else:
                accepted += 1
                accepted_payload_fields.extend(str(key) for key, value in row.payload.items() if value is not None)
            item_diagnostics.extend(row_diagnostics)

        decision_ready = accepted > 0
        status = "decision_ready_candidate" if decision_ready and blocked == 0 else "degraded"
        return SourceCandidateReadinessItem(
            source_id=source_id,
            label=SOURCE_LABELS[source_id],
            status=status,
            decision_ready=decision_ready,
            row_count=len(rows),
            accepted_row_count=accepted,
            blocked_row_count=blocked,
            diagnostics=_unique(item_diagnostics),
            coverage=_coverage(source_id, accepted_payload_fields),
        )

    def _row_diagnostics(self, row: SourceCandidateRow) -> tuple[str, ...]:
        diagnostics: list[str] = []
        available = _parse_date(row.available_date)
        decision = _parse_date(row.decision_date or self.decision_date)
        if available is None:
            diagnostics.append("missing_available_date")
        elif decision is not None and available > decision:
            diagnostics.append("future_data_blocked")

        if row.quality not in {"observed", "governed", "verified"}:
            diagnostics.append(f"source_quality_degraded:{row.quality}")

        required = REQUIRED_FIELDS[row.source_id]
        missing_required = tuple(field_name for field_name in required if row.payload.get(field_name) is None)
        diagnostics.extend(f"missing_required_source:{field_name}" for field_name in missing_required)

        if row.source_id == "tdcc_shareholding" and not any(row.payload.get(field_name) is not None for field_name in TDCC_CANDIDATE_FIELDS):
            diagnostics.append("source_not_ingested")
            diagnostics.append("missing_required_source:tdcc_candidate_payload")

        optional = OPTIONAL_FIELDS[row.source_id]
        diagnostics.extend(f"missing_optional_source:{field_name}" for field_name in optional if row.payload.get(field_name) is None)
        return tuple(diagnostics)


def build_sample_source_candidate_report(*, decision_date: str) -> SourceCandidateReadinessReport:
    return SourceCandidateReadinessService(
        rows=sample_source_candidate_rows(decision_date=decision_date),
        decision_date=decision_date,
        source_mode="sample_only",
    ).build_report()


def sample_source_candidate_rows(*, decision_date: str) -> tuple[SourceCandidateRow, ...]:
    return (
        SourceCandidateRow(
            source_id="institutional_flows",
            symbol="2330",
            decision_date=decision_date,
            available_date=decision_date,
            source_version="phase3c-sample-v1",
            quality="observed",
            payload={
                "foreign_investor_buy": 1200,
                "foreign_investor_sell": 900,
                "foreign_investor_net": 300,
                "investment_trust_buy": 240,
                "investment_trust_sell": 180,
                "investment_trust_net": 60,
                "dealer_buy": 150,
                "dealer_sell": 130,
                "dealer_net": 20,
            },
        ),
        SourceCandidateRow(
            source_id="credit_transactions",
            symbol="2330",
            decision_date=decision_date,
            available_date=decision_date,
            source_version="phase3c-sample-v1",
            quality="observed",
            payload={
                "margin_purchase": 100,
                "margin_balance": 2500,
                "short_sale": 20,
                "short_balance": 400,
            },
        ),
        SourceCandidateRow(
            source_id="tdcc_shareholding",
            symbol="2330",
            decision_date=decision_date,
            available_date=decision_date,
            source_version="phase3c-sample-weekly-v1",
            quality="observed",
            payload={
                "shareholding_tiers": "weekly_distribution_available",
                "large_holder_ratio_bp": 6200,
                "retail_holder_ratio_bp": 1800,
                "dispersion_index_bp": 4400,
            },
        ),
    )


def render_source_candidate_markdown(report: SourceCandidateReadinessReport) -> str:
    payload = report.to_dict()
    boundary = payload["access_boundary"]
    lines = [
        "# Phase 3C Source Candidate Readiness",
        "",
        "- candidate-only=true",
        f"- source_mode=`{payload['source_mode']}`",
        f"- decision_date=`{payload['decision_date']}`",
        f"- writes_allowed={str(boundary['writes_allowed']).lower()}",
        f"- production_scheduler_allowed={str(boundary['production_scheduler_allowed']).lower()}",
        f"- scoring_engine_write_allowed={str(boundary['scoring_engine_write_allowed']).lower()}",
        f"- investment_effectiveness_claim={str(boundary['investment_effectiveness_claim']).lower()}",
        "",
        "此報告只檢查三大法人、信用交易與 TDCC / 集保庫存來源候選狀態，不是交易建議，也不代表任何投資有效性。",
        "",
        "| source_id | label | status | decision_ready | rows | accepted | blocked | diagnostics |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in payload["items"]:
        diagnostics = ", ".join(item["diagnostics"])
        lines.append(
            "| {source_id} | {label} | {status} | {decision_ready} | {row_count} | {accepted_row_count} | {blocked_row_count} | {diagnostics} |".format(
                source_id=item["source_id"],
                label=item["label"],
                status=item["status"],
                decision_ready=str(item["decision_ready"]).lower(),
                row_count=item["row_count"],
                accepted_row_count=item["accepted_row_count"],
                blocked_row_count=item["blocked_row_count"],
                diagnostics=diagnostics,
            )
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in payload["limitations"])
    return "\n".join(lines)


def _load_source_rows(conn: sqlite3.Connection, source_id: str, decision_date: str) -> tuple[SourceCandidateRow, ...]:
    table_columns = [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({source_id})")]
    rows: list[SourceCandidateRow] = []
    for sqlite_row in conn.execute(f"SELECT * FROM {source_id}"):
        raw = dict(sqlite_row)
        payload = {
            field_name: _first_present(raw, COLUMN_ALIASES[field_name])
            for field_name in (*REQUIRED_FIELDS[source_id], *OPTIONAL_FIELDS[source_id])
        }
        rows.append(
            SourceCandidateRow(
                source_id=source_id,
                symbol=_first_present(raw, COLUMN_ALIASES["stock_code"]),
                decision_date=_first_present(raw, COLUMN_ALIASES["decision_date"]) or decision_date,
                available_date=_first_present(raw, COLUMN_ALIASES["available_date"]),
                source_version=str(_first_present(raw, COLUMN_ALIASES["source_version"]) or ""),
                quality=str(_first_present(raw, COLUMN_ALIASES["quality"]) or "missing"),
                payload=payload,
            )
        )
    if "available_date" not in table_columns and "可得日" not in table_columns and "公告日" not in table_columns:
        return tuple(rows)
    return tuple(rows)


def _first_present(row: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _coverage(source_id: str, payload_fields: Iterable[str]) -> dict[str, Any]:
    present = tuple(sorted(set(payload_fields)))
    required = REQUIRED_FIELDS[source_id]
    optional = OPTIONAL_FIELDS[source_id]
    return {
        "required_fields": list(required),
        "required_fields_present": [field_name for field_name in required if field_name in present],
        "optional_fields": list(optional),
        "optional_fields_present": [field_name for field_name in optional if field_name in present],
        "candidate_fields_present": list(present),
    }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_blocking_diagnostic(diagnostic: str) -> bool:
    return diagnostic in {"missing_available_date", "future_data_blocked", "source_not_ingested"} or diagnostic.startswith(
        "missing_required_source:"
    )


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))
