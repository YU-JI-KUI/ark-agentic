
import os
import json

MOCK_DATA_DIR = "src/ark_agentic/agents/securities/mock_data"

def convert_to_str(obj):
    if isinstance(obj, dict):
        return {k: convert_to_str(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_str(v) for v in obj]
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return str(obj)
    return obj

def main():
    for root, dirs, files in os.walk(MOCK_DATA_DIR):
        for file in files:
            if file.endswith(".json"):
                path = os.path.join(root, file)
                print(f"Processing {path}...")
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                    
                    new_data = convert_to_str(data)
                    
                    with open(path, "w") as f:
                        json.dump(new_data, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    print(f"Error processing {path}: {e}")

if __name__ == "__main__":
    main()
