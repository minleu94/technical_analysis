import json
import os
from typing import List, Dict, Any
from runtime.interfaces.store_interface import IRuntimeStore

class LocalFileStore(IRuntimeStore):
    """
    Concrete implementation of IRuntimeStore using local JSON and JSONL files.
    This class handles the pure I/O mechanics and shields the Orchestration layer.
    """
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.events_file = os.path.join(self.base_dir, "events", "runtime_events.jsonl")
        self.task_file = os.path.join(self.base_dir, "state", "current_task.json")
        self.context_file = os.path.join(self.base_dir, "state", "runtime_context.json")
        
        # Ensure directories exist
        os.makedirs(os.path.dirname(self.events_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.task_file), exist_ok=True)
        
    def append_event(self, event_data: Dict[str, Any]) -> None:
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_data, ensure_ascii=False) + "\n")
            
    def read_latest_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        if not os.path.exists(self.events_file):
            return []
        
        # MVP Implementation: Read all and slice. 
        # Future-ready: Could be replaced by efficient tailing for huge logs.
        try:
            with open(self.events_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            events = []
            for line in lines[-limit:]:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return events
        except Exception:
            return []
        
    def _read_json_file(self, file_path: str) -> Dict[str, Any]:
        if not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def read_current_task(self) -> Dict[str, Any]:
        return self._read_json_file(self.task_file)
        
    def read_runtime_context(self) -> Dict[str, Any]:
        return self._read_json_file(self.context_file)
        
    def update_current_task(self, task_data: Dict[str, Any]) -> None:
        with open(self.task_file, "w", encoding="utf-8") as f:
            json.dump(task_data, f, ensure_ascii=False, indent=2)
