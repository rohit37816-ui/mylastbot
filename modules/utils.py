import json
from pathlib import Path
import os

def atomic_write_json(file_path: Path, data: dict):
    tmp_file = file_path.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_file, file_path)

def atomic_read_json(file_path: Path) -> dict:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        corrupt_path = file_path.with_suffix(".corrupt.bak")
        os.rename(file_path, corrupt_path)
        return {}
