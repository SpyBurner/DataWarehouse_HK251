import os
import csv
import json

def get_schemas(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            # Normalize path for uniform display
            display_path = file_path.replace('\\', '/')
            
            try:
                if file.endswith('.csv'):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        reader = csv.reader(f)
                        header = next(reader, [])
                        print(f"{display_path}:{', '.join(header)}")
                elif file.endswith('.json'):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        keys = []
                        if isinstance(data, dict):
                            keys = list(data.keys())
                        elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                            keys = list(data[0].keys())
                        print(f"{display_path}:{', '.join(keys)}")
            except Exception as e:
                print(f"{display_path}:Error reading file ({e})")

if __name__ == "__main__":
    target_dir = "Datasets"
    if os.path.exists(target_dir):
        get_schemas(target_dir)
    else:
        print(f"Directory {target_dir} not found.")