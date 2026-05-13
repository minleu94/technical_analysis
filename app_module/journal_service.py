"""Thin Journal service for Phase 4.1 MVP."""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from app_module.dtos.portfolio_dtos import JournalEntryDTO
from app_module.portfolio_store import PortfolioJsonlStore
from data_module.config import TWStockConfig

logger = logging.getLogger(__name__)


class JournalService:
    """Coordinates append-only journal entries."""

    def __init__(self, config: TWStockConfig):
        self.config = config
        self.store = PortfolioJsonlStore(config.output_root)

    def add_journal_entry(
        self,
        body: str,
        portfolio_id: str = "default",
        title: str = "",
        stock_code: str = "",
        linked_type: str = "",
        linked_id: str = "",
        tags: Optional[List[str]] = None,
        source_type: str = "",
        source_id: str = "",
        source_snapshot_hash: str = "",
        journal_id: Optional[str] = None,
    ) -> JournalEntryDTO:
        if not body.strip():
            raise ValueError("journal body is required")

        now = datetime.now().isoformat()
        entry = JournalEntryDTO(
            journal_id=journal_id or f"journal_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}",
            portfolio_id=portfolio_id,
            title=title,
            body=body,
            stock_code=stock_code,
            linked_type=linked_type,
            linked_id=linked_id,
            tags=tags or [],
            source_type=source_type,
            source_id=source_id,
            source_snapshot_hash=source_snapshot_hash,
            created_at=now,
            updated_at=now,
        )
        self.store.append_journal_entry(entry.to_dict())
        logger.info("[JournalService] added journal entry %s", entry.journal_id)
        return entry

    def list_journal_entries(
        self,
        portfolio_id: str = "default",
        stock_code: str = "",
        linked_id: str = "",
    ) -> List[JournalEntryDTO]:
        entries = [JournalEntryDTO.from_dict(item) for item in self.store.load_journal_entries()]
        entries = [entry for entry in entries if entry.portfolio_id == portfolio_id]
        if stock_code:
            entries = [entry for entry in entries if entry.stock_code == stock_code]
        if linked_id:
            entries = [entry for entry in entries if entry.linked_id == linked_id]
        return sorted(entries, key=lambda entry: entry.created_at, reverse=True)
