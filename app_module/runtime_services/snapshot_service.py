from runtime.interfaces.store_interface import IRuntimeStore
from app_module.dtos.runtime_dtos import RuntimeStateSnapshotDTO, RuntimeTransitionDTO

class RuntimeSnapshotService:
    """
    Service responsible for aggregating raw runtime states from IRuntimeStore
    and translating them into standardized DTOs for the UI.
    """
    def __init__(self, store: IRuntimeStore):
        self.store = store
        
    def get_snapshot(self) -> RuntimeStateSnapshotDTO:
        task_data = self.store.read_current_task()
        context_data = self.store.read_runtime_context()
        
        return RuntimeStateSnapshotDTO(
            task_objective=task_data.get("objective", "No task assigned"),
            task_status=task_data.get("status", "IDLE"),
            active_context_files=context_data.get("active_files", []),
            recent_transitions=[] # To be populated by analyzing the event stream log in future refinements
        )
