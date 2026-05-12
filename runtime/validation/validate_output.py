import json
import sys
import os

def validate_dict(data, schema):
    """
    A lightweight, explainable JSON schema validator using only standard Python library.
    Ensures explainability-first by providing clear, understandable error messages.
    """
    errors = []
    
    # 1. Check required fields
    for req in schema.get("required", []):
        if req not in data:
            errors.append(f"Missing required field: '{req}'")
            
    # 2. Check properties and types
    properties = schema.get("properties", {})
    for key, value in data.items():
        if key in properties:
            prop_schema = properties[key]
            expected_type = prop_schema.get("type")
            
            # Type checking mapping
            type_map = {
                "string": str,
                "object": dict,
                "array": list,
                "boolean": bool,
                "integer": int,
            }
            
            if expected_type in type_map:
                if not isinstance(value, type_map[expected_type]):
                    errors.append(f"Field '{key}' has invalid type. Expected {expected_type}, got {type(value).__name__}")
            
            # Enum checking (Governance boundary constraint)
            if "enum" in prop_schema:
                if value not in prop_schema["enum"]:
                    errors.append(f"Field '{key}' value '{value}' not in allowed enum: {prop_schema['enum']}")
            
            # Nested object checking (Recursive validation)
            if expected_type == "object" and isinstance(value, dict) and "properties" in prop_schema:
                nested_errors = validate_dict(value, prop_schema)
                for err in nested_errors:
                    errors.append(f"{key}.{err}")
                    
    return errors

def main(output_file, schema_file="output_schema.json"):
    print(f"[{os.path.basename(__file__)}] Starting validation for {output_file}...")
    
    # Load Schema
    try:
        with open(schema_file, 'r', encoding='utf-8') as f:
            schema = json.load(f)
    except Exception as e:
        print(f"❌ Error loading schema: {e}")
        sys.exit(1)
        
    # Load Output JSON
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error parsing JSON output (LLM syntax error): {e}")
        print("💡 Action: Return formatting error to Agent.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error loading output file: {e}")
        sys.exit(1)
        
    # Execute Validation
    errors = validate_dict(data, schema)
    
    if errors:
        print("\n❌ Validation Failed (Hard-fail)!")
        print("Governance Boundaries Violated:")
        for err in errors:
            print(f"  - {err}")
        print("\n💡 Action: Do NOT apply state changes. Request Agent to regenerate output.")
        sys.exit(1)
        
    print("\n✅ Validation Passed! Output meets governance schema.")
    
    # Warning-only validations (Soft-fail / Explainability checks)
    summary = data.get("human_readable_summary", "")
    if len(summary) < 20:
        print("⚠️  Warning: 'human_readable_summary' is too short. Explainability might be compromised.")
        print("💡 Note: Logged for audit, but execution is allowed to proceed.")
        
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_output.py <path_to_output_json> [path_to_schema_json]")
        sys.exit(1)
        
    output_path = sys.argv[1]
    # Default schema is in the same directory as the script
    schema_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "output_schema.json")
    
    main(output_path, schema_path)
