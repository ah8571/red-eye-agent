import unittest
import yaml
from agent.checklist import parse_markdown, parse_yaml_text, validate_checklist_dict


class TestParseMarkdown(unittest.TestCase):

    def test_valid_with_context(self):
        text = """## Section 1
- Task one description
  - context: file1.py, file2.py
- Task two description
  - context: web/app.py
"""
        result = parse_markdown(text, "test-repo")
        tasks = result["tasks"]
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["id"], 1)
        self.assertEqual(tasks[0]["repo"], "test-repo")
        self.assertEqual(tasks[0]["description"], "Task one description")
        self.assertEqual(tasks[0]["status"], "pending")
        self.assertEqual(tasks[0]["context_files"], ["file1.py", "file2.py"])
        self.assertEqual(tasks[1]["context_files"], ["web/app.py"])

    def test_without_context(self):
        text = """- Task one
- Task two
"""
        result = parse_markdown(text, "repo")
        tasks = result["tasks"]
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["context_files"], [])
        self.assertEqual(tasks[1]["context_files"], [])

    def test_empty_input(self):
        self.assertEqual(parse_markdown("", "repo"), {"tasks": []})
        self.assertEqual(parse_markdown("\n\n", "repo"), {"tasks": []})

    def test_ignores_headers_and_blanks(self):
        text = """# Main Header

## Subsection

- Task after blank
  - context: a.py
"""
        result = parse_markdown(text, "repo")
        tasks = result["tasks"]
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["description"], "Task after blank")
        self.assertEqual(tasks[0]["context_files"], ["a.py"])

    def test_multi_line_description(self):
        text = """- First line of task
  continuation line
  another continuation
- Second task
"""
        result = parse_markdown(text, "repo")
        tasks = result["tasks"]
        self.assertEqual(len(tasks), 2)
        self.assertIn("continuation line", tasks[0]["description"])
        self.assertEqual(tasks[1]["description"], "Second task")


class TestParseYamlText(unittest.TestCase):

    def test_valid_yaml(self):
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
        tasks = result["tasks"]
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["id"], 1)
        self.assertEqual(tasks[0]["description"], "Task one")
        self.assertEqual(tasks[0]["context_files"], ["file1.py"])
        self.assertEqual(tasks[1]["status"], "in_progress")

    def test_invalid_yaml_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_yaml_text("tasks: [invalid: yaml}")
        self.assertIn("Invalid YAML", str(ctx.exception))

    def test_missing_tasks_key_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_yaml_text("repo: test")
        self.assertIn("tasks", str(ctx.exception).lower())

    def test_tasks_not_list_raises(self):
        with self.assertRaises(ValueError) as ctx:
            parse_yaml_text("tasks: {id: 1}")
        self.assertIn("list", str(ctx.exception).lower())


class TestValidateChecklistDict(unittest.TestCase):

    def test_empty_dict(self):
        errors = validate_checklist_dict({})
        self.assertIn("Missing 'tasks' key", errors)

    def test_valid_dict(self):
        data = {
            "tasks": [
                {"id": 1, "repo": "r", "description": "d", "status": "pending", "context_files": []},
                {"id": 2, "repo": "r", "description": "d2", "status": "done", "context_files": ["a.py"]},
            ]
        }
        self.assertEqual(validate_checklist_dict(data), [])

    def test_duplicate_ids(self):
        data = {
            "tasks": [
                {"id": 1, "repo": "r", "description": "d", "status": "pending"},
                {"id": 1, "repo": "r", "description": "d2", "status": "pending"},
            ]
        }
        errors = validate_checklist_dict(data)
        self.assertTrue(any("Duplicate task id 1" in e for e in errors))

    def test_invalid_status(self):
        data = {
            "tasks": [
                {"id": 1, "repo": "r", "description": "d", "status": "invalid"},
            ]
        }
        errors = validate_checklist_dict(data)
        self.assertTrue(any("invalid status" in e for e in errors))

    def test_empty_description(self):
        data = {
            "tasks": [
                {"id": 1, "repo": "r", "description": "   ", "status": "pending"},
            ]
        }
        errors = validate_checklist_dict(data)
        self.assertTrue(any("description is empty" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
