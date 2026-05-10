import re
from pathlib import Path

def update_setting(file_path: Path, key: str, value: bool):
    """Updates a boolean setting in the python file using regex."""
    content = file_path.read_text(encoding="utf-8")
    
    # Check if current value already matches
    current_match = re.search(rf"{key}\s*=\s*(True|False)", content)
    if current_match and current_match.group(1) == str(value):
        return # No change needed

    # Match key = True/False
    pattern = rf"({key}\s*=\s*)(True|False)"
    replacement = rf"\g<1>{value}"
    
    new_content = re.sub(pattern, replacement, content)
    file_path.write_text(new_content, encoding="utf-8")
