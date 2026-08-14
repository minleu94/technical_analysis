from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass(frozen=True)
class RuntimeEventCursor:
    """Append-only JSONL stream 的 byte cursor。``-1`` 表示先定位到檔尾。"""

    position: int


@dataclass(frozen=True)
class RuntimeEventReadBatch:
    """一批不跨越 cursor 的 JSONL event；壞行以計數揭露而非偽造事件。"""

    events: tuple[Dict[str, Any], ...]
    next_cursor: RuntimeEventCursor
    has_more: bool
    cursor_reset: bool = False
    invalid_line_count: int = 0
    read_state: str = "observed"
    diagnostic: str = ""


@dataclass(frozen=True)
class RuntimeEventReadResult:
    """事件檔尾端讀取結果，保留 I/O 與 JSON 完整性狀態。"""

    events: tuple[Dict[str, Any], ...]
    read_state: str
    diagnostic: str = ""
    invalid_line_count: int = 0

class IRuntimeStore(ABC):
    """
    Abstract interface defining the governance boundaries for Runtime Subsystem Storage.
    Ensures that orchestration and UI layers do not depend on direct file I/O or paths.
    """
    @abstractmethod
    def append_event(self, event_data: Dict[str, Any]) -> None:
        """Appends a new event to the append-only event stream."""
        pass
        
    @abstractmethod
    def read_latest_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Reads the latest events from the append-only log for replayability."""
        pass

    @abstractmethod
    def read_latest_events_result(self, limit: int = 100) -> RuntimeEventReadResult:
        """Reads latest events together with read integrity, without hiding I/O failure."""
        pass

    @abstractmethod
    def read_events_after(
        self,
        cursor: RuntimeEventCursor | None,
        limit: int = 50,
    ) -> RuntimeEventReadBatch:
        """從 byte cursor 讀取未發送事件；不可用事件數量作 watermark。"""
        pass
        
    @abstractmethod
    def read_current_task(self) -> Dict[str, Any]:
        """Reads the FSM's current task state."""
        pass
        
    @abstractmethod
    def read_runtime_context(self) -> Dict[str, Any]:
        """Reads the dynamic runtime context environment."""
        pass
        
    @abstractmethod
    def update_current_task(self, task_data: Dict[str, Any]) -> None:
        """Updates the FSM's current task state. Warning: Overwrites existing state."""
        pass
