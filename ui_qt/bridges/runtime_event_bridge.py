from PySide6.QtCore import QObject, Signal
from app_module.dtos.runtime_dtos import RuntimeEventDTO, RuntimeStateSnapshotDTO, RuntimeHealthSnapshotDTO
from app_module.runtime_services.event_bus import EventBus

class QtRuntimeBridge(QObject):
    """
    Acts as the boundary adaptor between pure Python EventBus and PyQt6 Signals.
    Strictly isolated in the UI layer. Ensures ui_qt relies only on Qt paradigms
    while app_module stays framework-agnostic.
    """
    # Define Qt Signals that emit our pure DTOs
    event_received = Signal(RuntimeEventDTO)
    state_updated = Signal(RuntimeStateSnapshotDTO)
    health_updated = Signal(RuntimeHealthSnapshotDTO)
    
    def __init__(self, event_bus: EventBus, parent=None):
        super().__init__(parent)
        self._event_bus = event_bus
        
        # Subscribe pure Python callbacks to the EventBus
        self._event_bus.subscribe_events(self._on_event_received)
        self._event_bus.subscribe_state(self._on_state_updated)
        self._event_bus.subscribe_health(self._on_health_updated)
        
    def _on_event_received(self, dto: RuntimeEventDTO) -> None:
        """Convert pure callback to Qt Signal emission"""
        self.event_received.emit(dto)
        
    def _on_state_updated(self, dto: RuntimeStateSnapshotDTO) -> None:
        self.state_updated.emit(dto)
        
    def _on_health_updated(self, dto: RuntimeHealthSnapshotDTO) -> None:
        self.health_updated.emit(dto)
