from runtime.store.local_file_store import LocalFileStore
from app_module.runtime_services.event_bus import EventBus
from app_module.runtime_services.snapshot_service import RuntimeSnapshotService
from app_module.runtime_services.health_service import RuntimeHealthService
import os

class RuntimeController:
    """
    Orchestrator that ties together the Store, Services, and EventBus.
    Provides a simple polling interface for the MVP to trigger state updates
    without tightly coupling the UI to the threading model.
    """
    def __init__(self, base_dir: str):
        self.store = LocalFileStore(base_dir)
        self.event_bus = EventBus()
        self.snapshot_service = RuntimeSnapshotService(self.store)
        self.health_service = RuntimeHealthService(self.store)
        
        self.last_event_count = 0
        
    def poll_updates(self) -> None:
        """Called periodically by the outer application loop to simulate streaming."""
        # 1. State Update
        state_dto = self.snapshot_service.get_snapshot()
        self.event_bus.publish_state(state_dto)
        
        # 2. Health Update
        health_dto = self.health_service.get_health_snapshot()
        self.event_bus.publish_health(health_dto)
        
        # 3. New Events Stream (Append-only simulation)
        all_events = self.store.read_latest_events(50)
        current_count = len(all_events)
        
        if current_count > self.last_event_count:
            new_events = all_events[self.last_event_count:]
            from app_module.dtos.runtime_dtos import RuntimeEventDTO, GovernanceSeverity
            from datetime import datetime
            
            for e in new_events:
                sev_str = e.get("severity", "INFO")
                try:
                    severity = GovernanceSeverity[sev_str.upper()]
                except KeyError:
                    severity = GovernanceSeverity.INFO
                    
                dto = RuntimeEventDTO(
                    event_id=e.get("event_id", ""),
                    timestamp=datetime.utcnow(), # fallback simplified parsing
                    actor=e.get("actor", "system"),
                    event_type=e.get("event_type", ""),
                    severity=severity,
                    human_readable_message=str(e.get("payload", {}).get("reason", e.get("event_type", ""))),
                    payload_preview=e.get("payload", {})
                )
                self.event_bus.publish_event(dto)
                
            self.last_event_count = current_count
