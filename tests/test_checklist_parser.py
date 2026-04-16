import pytest
import yaml
from checklist_parser import parse_markdown, parse_yaml_text, validate_checklist_dict


def test_parse_markdown_valid_with_context():
    text = """## Section 1
- Task one description
  - context: file1.py, file2.py
- Task two description
  - context: web/app.py
"""
    repo = "test-repo"
    result = parse_markdown(text, repo)
    assert "tasks" in result
    tasks = result["tasks"]
    assert len(tasks) == 2
    assert tasks[0]["id"] == 1
    assert tasks[0]["repo"] == repo
    assert tasks[0]["description"] == "Task one description"
    assert tasks[0]["status"] == "pending"
    assert tasks[0]["context_files"] == ["file1.py", "file2.py"]
    assert tasks[1]["id"] == 2
    assert tasks[1]["description"] == "Task two description"
    assert tasks[1]["context_files"] == ["web/app.py"]


def test_parse_markdown_multi_line_description():
    text = """- First line of task
  continuation line
  another continuation
- Second task
"""
    repo = "repo"
    result = parse_markdown(text, repo)
    tasks = result["tasks"]
    assert len(tasks) == 2
    assert tasks[0]["description"] == "First line of task\n  continuation line\n  another continuation"
    assert tasks[0]["context_files"] == []
    assert tasks[1]["description"] == "Second task"


def test_parse_markdown_without_context():
    text = """- Task one
- Task two
"""
    repo = "repo"
    result = parse_markdown(text, repo)
    tasks = result["tasks"]
    assert len(tasks) == 2
    assert tasks[0]["context_files"] == []
    assert tasks[1]["context_files"] == []


def test_parse_markdown_empty_input():
    result = parse_markdown("", "repo")
    assert result == {"tasks": []}
    result2 = parse_markdown("\n\n", "repo")
    assert result2 == {"tasks": []}


def test_parse_markdown_ignores_headers_and_blanks():
    text = """# Main Header

## Subsection

- Task after blank
  - context: a.py
"""
    result = parse_markdown(text, "repo")
    tasks = result["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["description"] == "Task after blank"
    assert tasks[0]["context_files"] == ["a.py"]


def test_parse_markdown_context_without_task_warns(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    text = "  - context: file.py"
    result = parse_markdown(text, "repo")
    assert result == {"tasks": []}
    assert "Context line without preceding task" in caplog.text


def test_parse_markdown_validation_fails_on_duplicate_ids():
    # parse_markdown generates sequential IDs, so duplicates shouldn't happen
    # but we can test validation separately
    data = {
        "tasks": [
            {"id": 1, "repo": "r", "description": "d", "status": "pending"},
            {"id": 1, "repo": "r", "description": "d2", "status": "pending"},
        ]
    }
    errors = validate_checklist_dict(data)
    assert "Duplicate task id 1" in errors


def test_parse_yaml_text_valid():
    yaml_text = """
tasks:
  - id: 1
    repo: test-repo
    description: Task one
    status: pending
    context_files:
      - file1.py
  - id: 2
    repo: test-repo
    description: Task two
    status: in_progress
"""
    result = parse_yaml_text(yaml_text)
    assert "tasks" in result
    tasks = result["tasks"]
    assert len(tasks) == 2
    assert tasks[0]["id"] == 1
    assert tasks[0]["description"] == "Task one"
    assert tasks[0]["status"] == "pending"
    assert tasks[0]["context_files"] == ["file1.py"]
    assert tasks[1]["id"] == 2
    assert tasks[1]["status"] == "in_progress"


def test_parse_yaml_text_invalid_yaml():
    with pytest.raises(ValueError) as exc:
        parse_yaml_text("tasks: [invalid: yaml}")
    assert "Invalid YAML" in str(exc.value)


def test_parse_yaml_text_missing_tasks_key():
    with pytest.raises(ValueError) as exc:
        parse_yaml_text("repo: test")
    assert "Missing 'tasks' key" in str(exc.value)


def test_parse_yaml_text_tasks_not_list():
    with pytest.raises(ValueError) as exc:
        parse_yaml_text("tasks: {id: 1}")
    assert "'tasks' must be a list" in str(exc.value)


def test_parse_yaml_text_task_missing_field():
    yaml_text = """
tasks:
  - id: 1
    repo: test
    # missing description
    status: pending
"""
    with pytest.raises(ValueError) as exc:
        parse_yaml_text(yaml_text)
    assert "missing 'description'" in str(exc.value).lower()


def test_validate_checklist_dict_empty():
    errors = validate_checklist_dict({})
    assert errors == ["Missing 'tasks' key"]


def test_validate_checklist_dict_valid():
    data = {
        "tasks": [
            {"id": 1, "repo": "r", "description": "d", "status": "pending", "context_files": []},
            {"id": 2, "repo": "r", "description": "d2", "status": "done", "context_files": ["a.py"]},
        ]
    }
    errors = validate_checklist_dict(data)
    assert errors == []


def test_validate_checklist_dict_invalid_status():
    data = {
        "tasks": [
            {"id": 1, "repo": "r", "description": "d", "status": "invalid", "context_files": []},
        ]
    }
    errors = validate_checklist_dict(data)
    assert "invalid status" in errors[0]


def test_validate_checklist_dict_empty_description():
    data = {
        "tasks": [
            {"id": 1, "repo": "r", "description": "   ", "status": "pending", "context_files": []},
        ]
    }
    errors = validate_checklist_dict(data)
    assert "description is empty" in errors[0]
