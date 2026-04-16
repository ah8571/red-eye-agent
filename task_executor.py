"""
Task Executor ΓÇö runs a single task through the full lifecycle:

1. Read task from checklist
2. Create a git branch
3. Build context (file tree, relevant files)
4. Send to LLM with instructions
5. Apply the LLM's code changes
6. Run tests
7. Commit and push (or mark failed)
"""

import json
import logging
import signal
import time
from pathlib import Path

from git_manager import GitManager
from llm_client import LLMClient, BudgetExceededError

logger = logging.getLogger("agent.executor")

PROTECTED_FILES = [
    "agent_runner.py",
    "task_executor.py",
    "git_manager.py",
    "llm_client.py",
    "logger_setup.py",
    ".env",
    ".gitignore"
]

SYSTEM_PROMPT = """You are an autonomous coding agent working on a repository.
You will receive a task description and context about the codebase (file tree, relevant files).

Your job is to produce the exact file changes needed to complete the task.

RESPOND WITH VALID JSON ONLY. Use this format:
{
  "plan": "Brief description of your approach",
  "changes": [
    {
      "action": "edit",
      "file": "path/to/file.py",
      "search": "exact existing code to find",
      "replace": "new code to replace it with"
    },
    {
      "action": "create",
      "file": "path/to/new_file.py",
      "content": "full file content"
    },
    {
      "action": "delete",
      "file": "path/to/old_file.py"
    }
  ],
  "commit_message": "descriptive commit message",
  "notes": "anything the reviewer should know"
}

Rules:
- For "edit" actions, use "search" and "replace" fields. "search" must be an exact substring of the current file content. "replace" is the text that will replace it. Use multiple edit entries for multiple changes to the same file.
- For "create" actions, provide the full file content in "content".
- Only touch files that need to change.
- Write clean, idiomatic code.
- If a test_command exists, make sure your changes won't break tests.
- If the task is unclear, do your best interpretation and explain in "notes".
"""


class TaskExecutor:
    """Executes a single task against a repo."""

    def __init__(self, llm: LLMClient, git: GitManager, config: dict, branch_name: str):
        self.llm = llm
        self.git = git
        self.config = config
        self.branch_name = branch_name
        self.task_timeout = config.get("timeouts", {}).get("task_timeout_seconds", 900)
        self._current_context = None  # store context for potential retry

    def execute(self, task: dict) -> dict:
        """
        Run a single task end-to-end.

        Args:
            task: Dict with id, description, repo, and optional context_files.

        Returns:
            Result dict with status, branch, log, timing info.
        """
        task_id = task["id"]
        description = task["description"]
        context_files = task.get("context_files", [])
        start_time = time.time()

        result = {
            "task_id": task_id,
            "status": "failed",
            "branch": None,
            "commit_message": None,
            "plan": None,
            "notes": None,
            "tests_passed": None,
            "test_output": None,
            "error": None,
            "elapsed_seconds": 0,
        }

        try:
            # Enforce task timeout
            def _timeout_handler(signum, frame):
                raise TimeoutError(f"Task {task_id} exceeded {self.task_timeout}s timeout")

            # signal.alarm only works on Unix; on Windows we rely on subprocess timeouts
            if hasattr(signal, "SIGALRM"):
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(self.task_timeout)

            # Step 1: Starting task on the run branch
            logger.info(f"Task {task_id}: Starting ΓÇö {description}")
            result["branch"] = self.branch_name

            # Step 2: Install deps if needed
            self.git.install_deps()

            # Step 3: Build context for the LLM
            context = self._build_context(description, context_files)
            self._current_context = context  # store for retry

            # Step 4: Call LLM
            logger.info(f"Task {task_id}: Sending to LLM")
            messages = [{"role": "user", "content": context}]
            response_text = self.llm.chat(messages, system_prompt=SYSTEM_PROMPT)

            # Step 5: Parse and apply changes
            changes = self._parse_response(response_text, context)
            result["plan"] = changes.get("plan", "")
            result["notes"] = changes.get("notes", "")
            result["commit_message"] = changes.get("commit_message", f"Task {task_id}: {description}")

            self._apply_changes(changes)

            # Step 6: Run tests
            tests_passed, test_output = self.git.run_tests()
            result["tests_passed"] = tests_passed
            result["test_output"] = test_output

            if not tests_passed:
                # Try one fix cycle: send test output back to LLM
                logger.warning(f"Task {task_id}: Tests failed, attempting fix")
                fix_result = self._attempt_fix(description, test_output, context_files)
                if fix_result:
                    tests_passed2, test_output2 = self.git.run_tests()
                    result["tests_passed"] = tests_passed2
                    result["test_output"] = test_output2
                    if not tests_passed2:
                        result["status"] = "failed"
                        result["error"] = "Tests still failing after fix attempt"
                        self._finalize(result, self.branch_name, start_time, commit=True)
                        return result

            # Step 7: Commit and push
            committed = self.git.stage_and_commit(result["commit_message"])
            if committed:
                pushed = self.git.push_branch(self.branch_name)
                if not pushed:
                    result["error"] = "Push failed"
                    result["status"] = "failed"
                    self._finalize(result, self.branch_name, start_time)
                    return result

            result["status"] = "done"

        except BudgetExceededError as e:
            result["error"] = str(e)
            result["status"] = "budget_exceeded"
            logger.error(f"Task {task_id}: {e}")

        except TimeoutError as e:
            result["error"] = str(e)
            result["status"] = "timeout"
            logger.error(f"Task {task_id}: {e}")

        except Exception as e:
            result["error"] = str(e)
            result["status"] = "failed"
            logger.exception(f"Task {task_id}: Unexpected error")

        finally:
            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)

        self._finalize(result, result.get("branch"), start_time)
        return result

    def _build_context(self, description: str, context_files: list[str]) -> str:
        """Assemble context string for the LLM."""
        parts = [f"## Task\n{description}\n"]

        # File tree
        file_tree = self.git.get_file_tree()
        parts.append(f"## Repository file tree\n```\n{file_tree}\n```\n")

        # Specific context files
        for fpath in context_files:
            try:
                content = self.git.read_file(fpath)
                parts.append(f"## File: {fpath}\n```\n{content}\n```\n")
            except Exception as e:
                parts.append(f"## File: {fpath}\n(Could not read: {e})\n")

        return "\n".join(parts)

    def _parse_response(self, response_text: str, original_context: str) -> dict:
        """
        Parse JSON response from LLM, handling markdown code fences.
        If the response is not valid JSON, send one follow-up message asking for valid JSON.
        Only retry once.
        """
        text = response_text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            # Remove first line (```json) and last line (```)
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM response was not valid JSON, attempting retry: {e}")
            logger.debug(f"Raw response:\n{response_text[:500]}")
            # Retry once
            return self._retry_parse(original_context, response_text)

    def _retry_parse(self, original_context: str, previous_response: str) -> dict:
        """Send follow-up message asking for valid JSON and parse again."""
        logger.info("Retrying LLM parse with follow-up message")
        follow_up = (
            f"{original_context}\n\n"
            f"## Previous Invalid Response\n"
            f"Your previous response was not valid JSON. Please respond with valid JSON only following the exact schema.\n"
            f"Your previous response:\n"
            f"```\n{previous_response[:1000]}\n```"
        )
        messages = [
            {"role": "user", "content": original_context},
            {"role": "assistant", "content": previous_response},
            {"role": "user", "content": follow_up},
        ]
        response_text = self.llm.chat(messages, system_prompt=SYSTEM_PROMPT)
        text = response_text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Second LLM response also invalid JSON: {e}")
            logger.debug(f"Raw retry response:\n{response_text[:500]}")
            raise ValueError(f"LLM response was not valid JSON after retry: {e}")

    def _apply_changes(self, changes: dict):
        """Apply file changes from the LLM response."""
        for change in changes.get("changes", []):
            action = change.get("action")
            file_path = change.get("file")

            # Build full path and check for path traversal
            full_path = self.git.workspace_dir / file_path
            try:
                resolved = full_path.resolve()
                if not resolved.is_relative_to(self.git.workspace_dir.resolve()):
                    logger.warning(f"Path traversal blocked for {action} on {file_path}")
                    continue
            except Exception as e:
                logger.warning(f"Path resolution failed for {file_path}: {e}")
                continue

            # Check if file is protected
            is_protected = file_path in PROTECTED_FILES
            if is_protected and action == "delete":
                logger.warning(f"Blocked delete of protected file: {file_path}")
                continue
            if is_protected and action == "edit":
                logger.info(f"Editing protected file: {file_path}")

            if action == "create":
                content = change.get("content", "")
                self.git.write_file(file_path, content)
                logger.info(f"Applied {action}: {file_path}")

            elif action == "edit":
                search = change.get("search")
                replace = change.get("replace")
                content = change.get("content")

                if search is not None and replace is not None:
                    # Search-and-replace mode
                    try:
                        current = self.git.read_file(file_path)
                    except Exception as e:
                        logger.warning(f"Cannot read {file_path} for edit: {e}")
                        continue
                    if search not in current:
                        logger.warning(f"Search string not found in {file_path}, skipping edit")
                        continue
                    updated = current.replace(search, replace, 1)
                    self.git.write_file(file_path, updated)
                    logger.info(f"Applied edit (search/replace): {file_path}")
                elif content is not None:
                    # Fallback: full file content mode
                    self.git.write_file(file_path, content)
                    logger.info(f"Applied edit (full content): {file_path}")
                else:
                    logger.warning(f"Edit for {file_path} missing both search/replace and content")

            elif action == "delete":
                if full_path.exists():
                    full_path.unlink()
                    logger.info(f"Deleted: {file_path}")

            else:
                logger.warning(f"Unknown action '{action}' for {file_path}")

    def _attempt_fix(self, description: str, test_output: str, context_files: list[str]) -> bool:
        """Send test failure back to LLM for a fix attempt."""
        context = self._build_context(description, context_files)
        fix_prompt = (
            f"{context}\n\n"
            f"## Test Failure\n"
            f"The changes you made caused test failures. Here is the output:\n"
            f"```\n{test_output[:3000]}\n```\n\n"
            f"Please fix the code. Respond with the same JSON format."
        )

        try:
            messages = [{"role": "user", "content": fix_prompt}]
            response_text = self.llm.chat(messages, system_prompt=SYSTEM_PROMPT)
            changes = self._parse_response(response_text, context)
            self._apply_changes(changes)
            return True
        except Exception as e:
            logger.error(f"Fix attempt failed: {e}")
            return False

    def _finalize(self, result: dict, branch_name: str | None, start_time: float, commit: bool = False):
        """Final bookkeeping."""
        result["elapsed_seconds"] = round(time.time() - start_time, 1)
        status_icon = "Γ£ô" if result["status"] == "done" else "Γ£ù"
        logger.info(
            f"Task {result['task_id']} {status_icon} [{result['status']}] "
            f"in {result['elapsed_seconds']}s ΓÇö branch: {branch_name}"
        )
        if commit and branch_name:
            self.git.stage_and_commit(
                f"Task {result['task_id']}: WIP (tests failing) ΓÇö {result.get('commit_message', '')}"
            )
            self.git.push_branch(branch_name)
