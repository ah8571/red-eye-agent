import yaml
import re
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def parse_markdown(text: str, repo: str) -> dict:
    """
    Convert markdown text into a checklist dict.
    
    Format:
    - Lines starting with "- " are task descriptions.
    - Indented lines starting with "  - context:" followed by a comma-separated list of filenames are context_files for the preceding task.
    - Lines starting with "## " or "# " are section headers and should be ignored.
    - Blank lines are ignored.
    - Multi-line task descriptions: if a line does not start with "- " or "  - context:" and is not a heading or blank, it is appended to the previous task's description.
    
    Returns:
        {"tasks": [{"id": 1, "repo": repo, "description": "...", "status": "pending", "context_files": ["file1.py", "file2.py"]}]}
    """
    tasks = []
    current_task = None
    lines = text.splitlines()
    task_counter = 1
    
    for line in lines:
        stripped = line.rstrip()
        # Skip blank lines
        if not stripped:
            continue
        # Skip section headers
        if stripped.startswith("# ") or stripped.startswith("## "):
            continue
        # Check for context line
        if stripped.startswith("  - context:"):
            if current_task is None:
                logger.warning("Context line without preceding task: %s", line)
                continue
            # Extract filenames after "context:"
            context_part = stripped[len("  - context:"):].strip()
            if context_part:
                # Split by commas, strip whitespace, filter empty
                files = [f.strip() for f in context_part.split(",") if f.strip()]
                current_task["context_files"].extend(files)
            continue
        # Check for new task
        if stripped.startswith("- "):
            # Save previous task if exists
            if current_task is not None:
                tasks.append(current_task)
            # Start new task
            description = stripped[2:].strip()
            current_task = {
                "id": task_counter,
                "repo": repo,
                "description": description,
                "status": "pending",
                "context_files": []
            }
            task_counter += 1
            continue
        # If line is not a header, blank, context, or new task, append to current task description
        if current_task is not None:
            # Append as continuation line, preserving original line break
            current_task["description"] += "\n" + stripped
        else:
            logger.warning("Ignoring line without preceding task: %s", line)
    
    # Add the last task if exists
    if current_task is not None:
        tasks.append(current_task)
    
    result = {"tasks": tasks}
    # Validate the generated checklist
    errors = validate_checklist_dict(result)
    if errors:
        raise ValueError("Markdown validation errors: " + "; ".join(errors))
    return result


def parse_yaml_text(text: str) -> dict:
    """
    Parse raw YAML text into a checklist dict.
    
    Validates that the parsed dict has a "tasks" key that is a list
    where each item has "id", "repo", "description", and "status" keys.
    
    Raises ValueError with descriptive message on any validation failure.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {e}")
    
    if not isinstance(data, dict):
        raise ValueError("YAML must parse to a dictionary")
    
    errors = validate_checklist_dict(data)
    if errors:
        raise ValueError("YAML validation errors: " + "; ".join(errors))
    
    return data


def validate_checklist_dict(data: dict) -> List[str]:
    """
    Validate a checklist dict.
    
    Checks:
    - tasks key exists and is a list
    - each task has id (int), repo (str), description (str), status (str)
    - status is one of allowed values
    - task IDs are unique
    - descriptions are not empty
    
    Returns list of error messages (empty = valid).
    """
    errors = []
    
    if "tasks" not in data:
        errors.append("Missing 'tasks' key")
        return errors
    
    tasks = data["tasks"]
    if not isinstance(tasks, list):
        errors.append("'tasks' must be a list")
        return errors
    
    allowed_statuses = {"pending", "in_progress", "done", "failed", "timeout", "budget_exceeded"}
    seen_ids = set()
    
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            errors.append(f"Task at index {i} is not a dictionary")
            continue
        
        # Required fields
        required = [("id", int), ("repo", str), ("description", str), ("status", str)]
        for field, typ in required:
            if field not in task:
                errors.append(f"Task {i+1} missing '{field}'")
            elif not isinstance(task[field], typ):
                errors.append(f"Task {i+1} '{field}' must be {typ.__name__}")
        
        # Check ID uniqueness
        if "id" in task and isinstance(task["id"], int):
            if task["id"] in seen_ids:
                errors.append(f"Duplicate task id {task['id']}")
            seen_ids.add(task["id"])
        
        # Validate status
        if "status" in task and isinstance(task["status"], str):
            if task["status"] not in allowed_statuses:
                errors.append(f"Task {i+1} invalid status '{task['status']}'; must be one of {sorted(allowed_statuses)}")
        
        # Description non-empty
        if "description" in task and isinstance(task["description"], str):
            if not task["description"].strip():
                errors.append(f"Task {i+1} description is empty")
        
        # Ensure context_files exists and is list
        if "context_files" not in task:
            task["context_files"] = []
        elif not isinstance(task["context_files"], list):
            errors.append(f"Task {i+1} 'context_files' must be a list")
        else:
            # Ensure all context files are strings
            for j, f in enumerate(task["context_files"]):
                if not isinstance(f, str):
                    errors.append(f"Task {i+1} context file at index {j} must be string")
    
    return errors
