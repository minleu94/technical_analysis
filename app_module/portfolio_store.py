"""Append-only JSONL storage for the Phase 4.1 Portfolio MVP."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


class PortfolioJsonlStore:
    """Small storage adapter kept behind app_module services."""

    def __init__(self, output_root: Path):
        self.portfolio_dir = Path(output_root) / "portfolio"
        self.portfolio_dir.mkdir(parents=True, exist_ok=True)
        self.trades_file = self.portfolio_dir / "trades.jsonl"
        self.journal_file = self.portfolio_dir / "journal_entries.jsonl"

    def append_trade(self, trade: Dict[str, Any]) -> None:
        self._append_jsonl(self.trades_file, trade)

    def load_trades(self) -> List[Dict[str, Any]]:
        return list(self._read_jsonl(self.trades_file))

    def append_journal_entry(self, entry: Dict[str, Any]) -> None:
        self._append_jsonl(self.journal_file, entry)

    def load_journal_entries(self) -> List[Dict[str, Any]]:
        return list(self._read_jsonl(self.journal_file))

    def overwrite_trades(self, trades: List[Dict[str, Any]]) -> None:
        """重寫所有交易紀錄"""
        self.trades_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.trades_file, "w", encoding="utf-8") as handle:
            for item in trades:
                handle.write(json.dumps(_json_safe(item), ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def overwrite_journal_entries(self, entries: List[Dict[str, Any]]) -> None:
        """重寫所有日記紀錄"""
        self.journal_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.journal_file, "w", encoding="utf-8") as handle:
            for item in entries:
                handle.write(json.dumps(_json_safe(item), ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def _append_jsonl(self, path: Path, item: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_safe(item), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    def _read_jsonl(self, path: Path) -> Iterable[Dict[str, Any]]:
        if not path.exists():
            return []

        records = []
        with open(path, "r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
        return records
