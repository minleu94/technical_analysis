"""Evidence rehearsal 的唯讀 SQLite source probe 與隔離 working-copy 建立器。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType
from typing import Mapping


_TABLE_WHITELIST = (
    "daily_prices",
    "technical_indicators",
    "market_indices",
    "industry_indices",
    "institutional_flows",
    "credit_transactions",
    "tdcc_shareholding",
    "fundamental_monthly_revenues",
    "fundamental_statement_items",
)


@dataclass(frozen=True)
class EvidenceRehearsalSourceSnapshot:
    source_alias: str
    decision_date: str
    opened: bool
    access_mode: str
    schema_fingerprint: str
    table_row_counts: Mapping[str, int]
    p0_observations: tuple[object, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        date.fromisoformat(self.decision_date)
        object.__setattr__(
            self, "table_row_counts", MappingProxyType(dict(self.table_row_counts))
        )
        object.__setattr__(self, "p0_observations", tuple(self.p0_observations))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))

    def to_dict(self) -> dict[str, object]:
        return {
            "source_alias": self.source_alias,
            "decision_date": self.decision_date,
            "opened": self.opened,
            "access_mode": self.access_mode,
            "schema_fingerprint": self.schema_fingerprint,
            "table_row_counts": dict(self.table_row_counts),
            "p0_observations": list(self.p0_observations),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class EvidenceRehearsalWorkingCopyFacts:
    created: bool
    write_performed: bool
    source_write_performed: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


class EvidenceRehearsalSourceReader:
    """只以 URI ``mode=ro`` 開啟 source；所有寫入只落在 working copy。"""

    def read(
        self, source_db: str | Path, *, decision_date: str
    ) -> EvidenceRehearsalSourceSnapshot:
        date.fromisoformat(decision_date)
        source = Path(source_db).expanduser().resolve()
        schema: list[dict[str, object]] = []
        counts: dict[str, int] = {}
        diagnostics: list[str] = []
        with self.open_read_only(source) as connection:
            existing_tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            for table_name in _TABLE_WHITELIST:
                if table_name not in existing_tables:
                    diagnostics.append(f"schema_missing:{table_name}")
                    continue
                quoted = _quote_identifier(table_name)
                columns = [
                    {
                        "cid": int(row[0]),
                        "name": str(row[1]),
                        "type": str(row[2]),
                        "notnull": int(row[3]),
                        "default": row[4],
                        "pk": int(row[5]),
                    }
                    for row in connection.execute(f"PRAGMA table_info({quoted})")
                ]
                schema.append({"table": table_name, "columns": columns})
                counts[table_name] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
                )
        canonical = json.dumps(
            schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return EvidenceRehearsalSourceSnapshot(
            source_alias=source.name,
            decision_date=decision_date,
            opened=True,
            access_mode="sqlite_uri_mode_ro_query_only",
            schema_fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            table_row_counts=counts,
            diagnostics=tuple(diagnostics),
        )

    def backup_to_working_copy(
        self,
        source_db: str | Path,
        working_copy_db: str | Path,
        *,
        overwrite: bool = False,
    ) -> EvidenceRehearsalWorkingCopyFacts:
        source = Path(source_db).expanduser().resolve()
        target = Path(working_copy_db).expanduser().resolve()
        if source == target:
            raise ValueError("working-copy DB must differ from source DB")
        if target.exists() and not overwrite:
            raise FileExistsError(f"working copy already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        try:
            with self.open_read_only(source) as source_connection:
                with sqlite3.connect(target) as target_connection:
                    source_connection.backup(target_connection)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return EvidenceRehearsalWorkingCopyFacts(
            created=True,
            write_performed=True,
        )

    @staticmethod
    def open_read_only(source_db: str | Path) -> sqlite3.Connection:
        source = Path(source_db).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(str(source))
        uri = f"{source.as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only = ON")
        query_only = int(connection.execute("PRAGMA query_only").fetchone()[0])
        if query_only != 1:
            connection.close()
            raise sqlite3.OperationalError("source connection is not query-only")
        return connection


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'
