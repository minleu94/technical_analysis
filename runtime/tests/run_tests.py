import json
import os
import sys
import datetime
import uuid

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.append(os.path.join(BASE_DIR, "validation"))

from validate_output import validate_dict

# ---------------------------------------------------------
# Event Logging Prototype (Append-only)
# ---------------------------------------------------------
EVENTS_DIR = os.path.join(BASE_DIR, "events")
os.makedirs(EVENTS_DIR, exist_ok=True)
EVENT_LOG_FILE = os.path.join(EVENTS_DIR, "runtime_events.jsonl")

def log_event(actor, event_type, payload):
    """
    Append-only Event Logging.
    Records every action, decision, and validation failure for replayability.
    """
    event = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "actor": actor,
        "event_type": event_type,
        "payload": payload
    }
    with open(EVENT_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    return event

# ---------------------------------------------------------
# Registry Governance Validation
# ---------------------------------------------------------
def validate_registry_action(data, registry):
    """
    Checks if the structured_payload contains a forbidden action for this specific agent.
    """
    agent_id = data.get("agent_id")
    if not agent_id or agent_id not in registry.get("agents", {}):
        return [f"Agent '{agent_id}' not found in registry."]
        
    forbidden = registry["agents"][agent_id].get("forbidden_actions", [])
    payload = data.get("structured_payload", {})
    action = payload.get("action")
    
    if action in forbidden:
        return [f"Action '{action}' is strictly FORBIDDEN for agent '{agent_id}'."]
    return []

# ---------------------------------------------------------
# Shakeout Test Runner
# ---------------------------------------------------------
def run_test(test_name, file_path, schema, registry):
    print(f"\n{'='*50}\n▶ Running Test: {test_name}")
    log_event("system", "test_start", {"test_name": test_name, "file": file_path})
    
    # 1. JSON Parsing Check
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            data = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"❌ 解析失敗: Malformed JSON ({e})")
        log_event("system", "validation_rejected", {
            "reason": "JSONDecodeError", 
            "details": str(e), 
            "raw_snippet": content[:50] + "..."
        })
        return False
        
    log_event(data.get("agent_id", "unknown"), "agent_output_received", data)
    
    # 2. Schema Validation Check
    schema_errors = validate_dict(data, schema)
    if schema_errors:
        print("❌ 驗證失敗: Schema Boundary Violated")
        for err in schema_errors:
            print(f"  - {err}")
        log_event("system", "validation_rejected", {
            "reason": "SchemaViolation", 
            "errors": schema_errors
        })
        return False
        
    # 3. Registry Governance Check
    registry_errors = validate_registry_action(data, registry)
    if registry_errors:
        print("❌ 驗證失敗: Registry Governance Violated")
        for err in registry_errors:
            print(f"  - {err}")
        log_event("system", "validation_rejected", {
            "reason": "GovernanceViolation", 
            "errors": registry_errors
        })
        return False
        
    print("✅ 驗證通過: Output conforms to all governance rules.")
    log_event("system", "validation_approved", {
        "agent_id": data.get("agent_id"),
        "action": data.get("structured_payload", {}).get("action")
    })
    return True

if __name__ == "__main__":
    print("Starting Runtime MVP Shakeout Testing...")
    
    # Load Schema & Registry
    SCHEMA_FILE = os.path.join(BASE_DIR, "validation", "output_schema.json")
    REGISTRY_FILE = os.path.join(BASE_DIR, "registry", "agents_registry.json")
    
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        registry = json.load(f)
        
    # Define test cases
    tests_dir = os.path.join(BASE_DIR, "tests")
    tests = [
        "test_01_success.json",
        "test_02_malformed.json",
        "test_03_missing_rollback.json",
        "test_04_invalid_intent.json",
        "test_05_forbidden_action.json"
    ]
    
    for t in tests:
        test_path = os.path.join(tests_dir, t)
        if os.path.exists(test_path):
            run_test(t, test_path, schema, registry)
            
    print(f"\n✅ All tests executed. Audit log appended to: {EVENT_LOG_FILE}")
