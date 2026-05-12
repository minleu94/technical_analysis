from abc import ABC, abstractmethod
from typing import List, Dict, Any

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
