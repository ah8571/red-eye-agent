"""
Agent Runner — main orchestrator.

Loads config + checklist, runs tasks serially per-repo, logs everything,
and produces a summary when done.

Usage:
    python agent_runner.py                     # Run all pending tasks
    python agent_runner.py --dry-run           # Plan only, no changes
    python agent_runner.py --status            # Show checklist status and exit
    python agent_runner.py --task 3            # Run only task 3
    python agent_runner.py --repo my-app       # Run tasks for one repo only
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from git_manager import GitManager
from llm_client import LLMClient, BudgetExceededError
from task_executor import TaskExecutor
from logger_setup import setup_logging, get_task_logger
from report import generate_report

logger = logging.getLogger("agent.runner")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_config(config: dict) -> list[str]:
    """Validate configuration structure.
    
    Returns a list of error messages. Empty list means config is valid.
    """
    errors = []
    
    # (a) default_provider is one of "openai", "anthropic", "deepseek"
    allowed_providers = {"openai", "anthropic", "deepseek"}
    default_provider = config.get("default_provider")
    if default_provider not in allowed_providers:
        errors.append(
            f"Invalid default_provider: '{default_provider}'. "
            f"Must be one of {', '.join(sorted(allowed_providers))}."
        )
    
    # (b) models section has a config entry for the default_provider
    models = config.get("models")
    if not isinstance(models, dict):
        errors.append("Missing or invalid 'models' section (must be a dictionary).")
    elif default_provider and default_provider not in models:
        errors.append(
            f"Missing model configuration for default_provider '{default_provider}' in 'models' section."
        )
    
    # (c) budget has max_cost_per_run as a positive number
    budget = config.get("budget")
    if not isinstance(budget, dict):
        errors.append("Missing or invalid 'budget' section (must be a dictionary).")
    else:
        max_cost = budget.get("max_cost_per_run")
        if max_cost is None:
            errors.append("Missing 'max_cost_per_run' in budget section.")
        elif not isinstance(max_cost, (int, float)):
            errors.append("'max_cost_per_run' must be a number.")
        elif max_cost <= 0:
            errors.append("'max_cost_per_run' must be a positive number.")
    
    # (d) repos is a non-empty list where each entry has "name" and "url" keys
    repos = config.get("repos")
    if not isinstance(repos, list):
        errors.append("'repos' must be a list.")
    elif len(repos) == 0:
        errors.append("'repos' list cannot be empty.")
    else:
        for i, repo in enumerate(repos):
            if not isinstance(repo, dict):
                errors.append(f"Repo entry at index {i} is not a dictionary.")
                continue
            if "name" not in repo:
                errors.append(f"Repo entry at index {i} missing 'name' key.")
            if "url" not in repo:
                errors.append(f"Repo entry at index {i} missing 'url' key.")
    
    return errors


def load_checklist(path: str = "checklist.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_checklist(checklist: dict, path: str = "checklist.yaml"):
    """Validate checklist structure and content.
    
    Checks:
    - The file has a "tasks" key that is a list.
    - Each task has required fields: id (int), repo (str), description (str), status (str).
    - All task IDs are unique.
    - Status values are one of the allowed values.
    
    If validation fails, log a clear error and exit with code 1.
    """
    allowed_statuses = {"pending", "in_progress", "done", "failed", "timeout", "budget_exceeded", "dry_run"}
    
    # Check if 'tasks' key exists and is a list
    if "tasks" not in checklist:
        logger.error(f"Checklist validation failed: Missing 'tasks' key in {path}")
        sys.exit(1)
    
    tasks = checklist["tasks"]
    if not isinstance(tasks, list):
        logger.error(f"Checklist validation failed: 'tasks' must be a list in {path}")
        sys.exit(1)
    
    # Check each task
    seen_ids = set()
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            logger.error(f"Checklist validation failed: Task at index {i} is not a dictionary in {path}")
            sys.exit(1)
        
        # Required fields
        required_fields = ["id", "repo", "description", "status"]
        for field in required_fields:
            if field not in task:
                logger.error(f"Checklist validation failed: Task {task.get('id', f'index {i}')} missing required field '{field}' in {path}")
                sys.exit(1)
        
        # id must be int
        if not isinstance(task["id"], int):
            logger.error(f"Checklist validation failed: Task {task['id']} 'id' must be an integer in {path}")
            sys.exit(1)
        
        # repo must be str
        if not isinstance(task["repo"], str):
            logger.error(f"Checklist validation failed: Task {task['id']} 'repo' must be a string in {path}")
            sys.exit(1)
        
        # description must be str
        if not isinstance(task["description"], str):
            logger.error(f"Checklist validation failed: Task {task['id']} 'description' must be a string in {path}")
            sys.exit(1)
        
        # status must be str and allowed value
        if not isinstance(task["status"], str):
            logger.error(f"Checklist validation failed: Task {task['id']} 'status' must be a string in {path}")
            sys.exit(1)
        
        if task["status"] not in allowed_statuses:
            logger.error(f"Checklist validation failed: Task {task['id']} has invalid status '{task['status']}'. Allowed values: {', '.join(sorted(allowed_statuses))} in {path}")
            sys.exit(1)
        
        # Check uniqueness of id
        task_id = task["id"]
        if task_id in seen_ids:
            logger.error(f"Checklist validation failed: Duplicate task ID {task_id} in {path}")
            sys.exit(1)
        seen_ids.add(task_id)
    
    logger.info(f"Checklist validation passed for {path}")


def save_checklist(data: dict, path: str = "checklist.yaml"):
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def build_repo_map(config: dict) -> dict[str, GitManager]:
    """Create a GitManager for each configured repo."""
    repos = {}
    for repo_cfg in config.get("repos", []):
        repos[repo_cfg["name"]] = GitManager(repo_cfg)
    return repos


def show_status(checklist: dict):
    """Print checklist status table and summary counts."""
    tasks = checklist.get("tasks", [])
    
    if not tasks:
        print("No tasks in checklist.")
        return
    
    # Table header
    header = f"{'ID':<4} {'Repo':<20} {'Status':<15} Description"
    print(header)
    print("-" * len(header))
    
    # Counters
    counts = {
        "pending": 0,
        "in_progress": 0,
        "done": 0,
        "failed": 0,
        "timeout": 0,
        "budget_exceeded": 0,
        "dry_run": 0,
    }
    
    for task in tasks:
        task_id = task["id"]
        repo = task["repo"]
        status = task["status"]
        description = task["description"]
        
        # Truncate description to 60 chars
        if len(description) > 60:
            description = description[:57] + "..."
        
        # Update counts
        if status in counts:
            counts[status] += 1
        
        # Print row
        print(f"{task_id:<4} {repo:<20} {status:<15} {description}")
    
    # Summary
    print("\nSummary:")
    for status, count in counts.items():
        if count > 0:
            print(f"  {status}: {count}")
    
    total = len(tasks)
    print(f"\nTotal tasks: {total}")


def run(args):
    """Main run loop."""
    load_dotenv()

    config = load_config(args.config)
    
    # Validate config
    config_errors = validate_config(config)
    if config_errors:
        logger.error("Configuration validation failed:")
        for err in config_errors:
            logger.error(f"  - {err}")
        sys.exit(1)
    
    checklist = load_checklist(args.checklist)
    
    # Validate checklist
    validate_checklist(checklist, args.checklist)

    # If --status flag is set, show status and exit
    if args.status:
        show_status(checklist)
        return

    # Setup logging
    log_cfg = config.get("logging", {})
    log_dir = setup_logging(
        log_dir=log_cfg.get("log_dir", "./logs"),
        level=log_cfg.get("level", "INFO"),
    )

    logger.info("=" * 60)
    logger.info("Autonomous Agent Runner — starting")
    logger.info(f"Config: {args.config} | Checklist: {args.checklist}")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN — no changes will be made")

    # Initialize LLM client
    llm = LLMClient(config)

    # Build repo managers
    repos = build_repo_map(config)

    # Filter tasks
    tasks = checklist.get("tasks", [])
    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]
        if not tasks:
            logger.error(f"Task {args.task} not found in checklist")
            sys.exit(1)
    if args.repo:
        tasks = [t for t in tasks if t.get("repo") == args.repo]
        if not tasks:
            logger.error(f"No tasks found for repo '{args.repo}'")
            sys.exit(1)

    # Only run pending tasks
    pending = [t for t in tasks if t.get("status", "pending") == "pending"]
    logger.info(f"Tasks: {len(pending)} pending out of {len(tasks)} total")

    if not pending:
        logger.info("Nothing to do — all tasks are complete or in progress")
        return

    # Clone repos and create run branches
    from datetime import datetime as _dt
    run_date = _dt.now().strftime("%Y-%m-%d")
    repo_branches: dict[str, str] = {}  # repo_name → branch_name

    needed_repos = {t["repo"] for t in pending if t.get("repo")}
    for repo_name in needed_repos:
        if repo_name not in repos:
            logger.error(f"Repo '{repo_name}' referenced in tasks but not configured")
            sys.exit(1)
        git = repos[repo_name]
        if not git.ensure_cloned():
            logger.error(f"Failed to clone {repo_name}, aborting")
            sys.exit(1)
        # Pull latest and create a single branch for this repo's run
        git.pull_latest()
        branch_name = f"{git.branch_prefix}overnight-{run_date}"
        git.ensure_run_branch(branch_name)
        repo_branches[repo_name] = branch_name
        logger.info(f"Repo '{repo_name}' → branch '{branch_name}'")

    # Execute tasks serially
    results = []
    for task in pending:
        task_id = task["id"]
        repo_name = task["repo"]
        git = repos[repo_name]
        branch_name = repo_branches[repo_name]

        # Per-task log handler
        task_handler = get_task_logger(log_dir, task_id)

        logger.info(f"\n{'─' * 50}")
        logger.info(f"Task {task_id}: {task['description']}")
        logger.info(f"Repo: {repo_name} | Branch: {branch_name}")
        logger.info(f"{'─' * 50}")

        if args.dry_run:
            logger.info(f"[DRY RUN] Would execute task {task_id}")
            # Update status in checklist
            task["status"] = "dry_run"
            results.append({"task_id": task_id, "status": "dry_run"})
            logging.getLogger().removeHandler(task_handler)
            continue

        # Mark in progress
        task["status"] = "in_progress"
        save_checklist(checklist, args.checklist)

        # Execute
        executor = TaskExecutor(llm, git, config, branch_name)
        try:
            result = executor.execute(task)
        except BudgetExceededError as e:
            logger.error(f"Budget exceeded — stopping run: {e}")
            task["status"] = "budget_exceeded"
            save_checklist(checklist, args.checklist)
            break

        # Update checklist
        task["status"] = result["status"]
        task["branch"] = result.get("branch")
        task["log_file"] = f"logs/task_{task_id}.log"
        save_checklist(checklist, args.checklist)

        results.append(result)

        # Remove per-task handler
        logging.getLogger().removeHandler(task_handler)
        task_handler.close()

    # Summary
    _print_summary(results, llm)

    # Save results JSON
    results_file = log_dir / "results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Results saved to {results_file}")
    
    # Generate run report
    try:
        # Prepare usage stats object with required attributes
        class UsageStatsWrapper:
            def __init__(self, usage):
                self.input_tokens = usage.prompt_tokens
                self.output_tokens = usage.completion_tokens
                self.estimated_cost = usage.total_cost_usd
        
        usage_stats = UsageStatsWrapper(llm.usage)
        report_path = generate_report(results, usage_stats, log_dir)
        logger.info(f"Run report generated: {report_path}")
    except Exception as e:
        logger.error(f"Failed to generate run report: {e}")


def _print_summary(results: list[dict], llm: LLMClient):
    """Print a run summary."""
    logger.info("\n" + "=" * 60)
    logger.info("RUN SUMMARY")
    logger.info("=" * 60)

    done = [r for r in results if r["status"] == "done"]
    failed = [r for r in results if r["status"] == "failed"]
    timeout = [r for r in results if r["status"] == "timeout"]
    budget = [r for r in results if r["status"] == "budget_exceeded"]

    logger.info(f"  Completed: {len(done)}")
    logger.info(f"  Failed:    {len(failed)}")
    logger.info(f"  Timeout:   {len(timeout)}")
    logger.info(f"  Budget:    {len(budget)}")
    logger.info(f"  {llm.usage.summary()}")

    if done:
        logger.info("\nCompleted tasks:")
        for r in done:
            logger.info(f"  ✓ Task {r['task_id']} → {r.get('branch', 'N/A')} ({r['elapsed_seconds']}s)")

    if failed:
        logger.info("\nFailed tasks:")
        for r in failed:
            logger.info(f"  ✗ Task {r['task_id']} — {r.get('error', 'unknown error')}")

    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Autonomous Agent Runner")
    parser.add_argument("--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--checklist", default="checklist.yaml", help="Path to checklist file")
    
    # Mutually exclusive group for --dry-run and --status
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Plan only, no changes")
    group.add_argument("--status", action="store_true", help="Show checklist status and exit")
    
    parser.add_argument("--task", type=int, help="Run a specific task ID only")
    parser.add_argument("--repo", type=str, help="Run tasks for a specific repo only")
    args = parser.parse_args()

    try:
        run(args)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
