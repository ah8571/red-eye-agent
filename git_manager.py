"""
Git Manager — handles clone, branch, commit, push for each repo.

All tasks for a repo go on a single agent branch per run (e.g. agent/overnight-2026-04-15).
Each task is an individual commit, so you can revert specific tasks if needed.
One branch = one PR to review in the morning.
"""

import os
import re
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("agent.git")


class GitManager:
    """Manages git operations for a single repository."""

    def __init__(self, repo_config: dict):
        self.name = repo_config["name"]
        self.url = repo_config["url"]
        self.default_branch = repo_config.get("default_branch", "main")
        self.branch_prefix = repo_config.get("branch_prefix", "agent/")
        self.workspace_dir = Path(repo_config.get("workspace_dir", f"/workspace/{self.name}"))
        self.test_command = repo_config.get("test_command")
        self.install_command = repo_config.get("install_command")

    def _run(self, cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        """Run a shell command and return the result."""
        work_dir = cwd or self.workspace_dir
        logger.debug(f"[{self.name}] Running: {' '.join(cmd)} in {work_dir}")
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.error(f"[{self.name}] Command failed: {result.stderr.strip()}")
        return result

    def _inject_pat(self, url: str) -> str:
        """Inject GitHub PAT into the clone URL for authentication."""
        pat = os.environ.get("GITHUB_PAT", "")
        if not pat:
            return url
        # https://github.com/user/repo.git → https://x-access-token:<PAT>@github.com/user/repo.git
        if url.startswith("https://"):
            return url.replace("https://", f"https://x-access-token:{pat}@", 1)
        return url

    def ensure_cloned(self) -> bool:
        """Clone the repo if it doesn't exist yet. Returns True on success."""
        if (self.workspace_dir / ".git").exists():
            logger.info(f"[{self.name}] Repo already cloned at {self.workspace_dir}")
            return True

        logger.info(f"[{self.name}] Cloning {self.url} → {self.workspace_dir}")
        self.workspace_dir.parent.mkdir(parents=True, exist_ok=True)
        auth_url = self._inject_pat(self.url)
        result = self._run(
            ["git", "clone", auth_url, str(self.workspace_dir)],
            cwd=self.workspace_dir.parent,
        )
        if result.returncode != 0:
            logger.error(f"[{self.name}] Clone failed: {result.stderr}")
            return False

        # Configure git user for commits
        self._run(["git", "config", "user.name", "Autonomous Agent"])
        self._run(["git", "config", "user.email", "agent@localhost"])
        return True

    def pull_latest(self) -> bool:
        """Pull latest changes on the default branch."""
        logger.info(f"[{self.name}] Pulling latest {self.default_branch}")
        self._run(["git", "checkout", self.default_branch])
        result = self._run(["git", "pull", "origin", self.default_branch])
        return result.returncode == 0

    def ensure_run_branch(self, branch_name: str) -> str:
        """
        Create the run branch if it doesn't exist yet, or check it out if it does.
        Called once per repo at the start of a run.
        """
        # Check if branch already exists locally
        result = self._run(["git", "rev-parse", "--verify", branch_name])
        if result.returncode == 0:
            logger.info(f"[{self.name}] Checking out existing branch: {branch_name}")
            self._run(["git", "checkout", branch_name])
        else:
            logger.info(f"[{self.name}] Creating branch: {branch_name}")
            self._run(["git", "checkout", self.default_branch])
            self._run(["git", "checkout", "-b", branch_name])
        return branch_name

    def stage_and_commit(self, message: str) -> bool:
        """Stage all changes and commit."""
        # Check if there are changes to commit
        status = self._run(["git", "status", "--porcelain"])
        if not status.stdout.strip():
            logger.info(f"[{self.name}] No changes to commit")
            return False

        self._run(["git", "add", "-A"])
        result = self._run(["git", "commit", "-m", message])
        if result.returncode == 0:
            logger.info(f"[{self.name}] Committed: {message}")
            return True
        logger.error(f"[{self.name}] Commit failed: {result.stderr}")
        return False

    def push_branch(self, branch_name: str) -> bool:
        """Push the branch to origin."""
        logger.info(f"[{self.name}] Pushing {branch_name}")
        # Re-inject PAT for push URL
        auth_url = self._inject_pat(self.url)
        result = self._run(["git", "push", auth_url, branch_name])
        if result.returncode == 0:
            logger.info(f"[{self.name}] Pushed {branch_name}")
            return True
        logger.error(f"[{self.name}] Push failed: {result.stderr}")
        return False

    def run_tests(self) -> tuple[bool, str]:
        """Run the repo's test command. Returns (passed, output)."""
        if not self.test_command:
            logger.info(f"[{self.name}] No test command configured, skipping")
            return True, "No tests configured"

        logger.info(f"[{self.name}] Running tests: {self.test_command}")
        result = self._run(
            self.test_command.split(),
            timeout=300,
        )
        output = result.stdout + "\n" + result.stderr
        passed = result.returncode == 0
        if passed:
            logger.info(f"[{self.name}] Tests passed")
        else:
            logger.warning(f"[{self.name}] Tests failed")
        return passed, output.strip()

    def install_deps(self) -> bool:
        """Run the install command if configured."""
        if not self.install_command:
            return True
        logger.info(f"[{self.name}] Installing deps: {self.install_command}")
        result = self._run(self.install_command.split(), timeout=300)
        return result.returncode == 0

    def get_file_tree(self, max_depth: int = 3) -> str:
        """Get a file tree of the repo for context."""
        result = self._run(
            ["find", ".", "-maxdepth", str(max_depth),
             "-not", "-path", "./.git/*",
             "-not", "-path", "./node_modules/*",
             "-not", "-path", "./.venv/*",
             "-not", "-path", "./__pycache__/*"],
        )
        if result.returncode != 0:
            # Fallback for Windows or environments without find
            return self._get_file_tree_python(max_depth)
        return result.stdout.strip()

    def _get_file_tree_python(self, max_depth: int = 3) -> str:
        """Fallback file tree using Python's pathlib."""
        lines = []
        skip_dirs = {".git", "node_modules", ".venv", "__pycache__", ".next", "dist"}
        for path in sorted(self.workspace_dir.rglob("*")):
            rel = path.relative_to(self.workspace_dir)
            if any(part in skip_dirs for part in rel.parts):
                continue
            if len(rel.parts) > max_depth:
                continue
            lines.append(str(rel))
        return "\n".join(lines[:200])  # Cap output size

    def read_file(self, relative_path: str) -> str:
        """Read a file from the repo."""
        file_path = self.workspace_dir / relative_path
        if not file_path.resolve().is_relative_to(self.workspace_dir.resolve()):
            raise ValueError(f"Path traversal blocked: {relative_path}")
        return file_path.read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str):
        """Write content to a file in the repo."""
        file_path = self.workspace_dir / relative_path
        if not file_path.resolve().is_relative_to(self.workspace_dir.resolve()):
            raise ValueError(f"Path traversal blocked: {relative_path}")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"[{self.name}] Wrote {relative_path}")
