import subprocess
import sys
import os
import signal
import json
import shutil
import yaml
import datetime
import pathlib
import logging
from pathlib import Path

logger = logging.getLogger("agent.process_manager")


class RunManager:
    def __init__(self, runs_dir="runs"):
        """Initialize the run manager.
        
        Args:
            runs_dir (str): Directory where runs are stored.
        """
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.registry_file = self.runs_dir / "registry.json"
        self._load_registry()
    
    def _load_registry(self):
        """Load registry from runs/registry.json or empty dict if not found."""
        if self.registry_file.exists():
            try:
                with open(self.registry_file, 'r', encoding='utf-8') as f:
                    self.registry = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load registry: {e}. Starting with empty registry.")
                self.registry = {}
        else:
            self.registry = {}
    
    def _save_registry(self):
        """Write self.registry to runs/registry.json."""
        try:
            with open(self.registry_file, 'w', encoding='utf-8') as f:
                json.dump(self.registry, f, indent=2, default=str)
        except IOError as e:
            logger.error(f"Failed to save registry: {e}")
    
    def start_run(self, run_id, repo_name, checklist_path, config_path="config.yaml") -> dict:
        """Start a new run.
        
        Args:
            run_id (str): Unique identifier for the run.
            repo_name (str): Name of the repository.
            checklist_path (str): Path to the checklist file.
            config_path (str): Path to the config file.
        
        Returns:
            dict: The run entry in the registry.
        """
        # Create run directory
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy checklist file
        dest_checklist = run_dir / "checklist.yaml"
        try:
            shutil.copy2(checklist_path, dest_checklist)
        except (IOError, OSError) as e:
            logger.error(f"Failed to copy checklist: {e}")
            raise
        
        # Prepare log file
        log_file = run_dir / "output.log"
        
        # Spawn subprocess
        cmd = [
            sys.executable, "-m", "agent.runner",
            "--config", config_path,
            "--checklist", str(dest_checklist)
        ]
        try:
            with open(log_file, 'w') as f:
                proc = subprocess.Popen(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT
                )
        except (OSError, ValueError) as e:
            logger.error(f"Failed to start subprocess: {e}")
            raise
        
        # Create entry
        entry = {
            "pid": proc.pid,
            "repo": repo_name,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "running",
            "log_file": str(log_file),
            "checklist_file": str(dest_checklist),
            "config_path": config_path
        }
        self.registry[run_id] = entry
        self._save_registry()
        
        logger.info(f"Started run {run_id} with PID {proc.pid}")
        return entry
    
    def get_status(self, run_id) -> dict:
        """Get status of a run.
        
        Args:
            run_id (str): Run identifier.
        
        Returns:
            dict: Status information.
        """
        if run_id not in self.registry:
            raise KeyError(f"Run {run_id} not found")
        
        entry = self.registry[run_id].copy()
        pid = entry["pid"]
        
        # Check if process is alive
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            # Process exists but we don't have permission to signal it
            alive = True
        
        # Update status if process is dead and was running
        if not alive and entry["status"] == "running":
            entry["status"] = "finished"
            self.registry[run_id]["status"] = "finished"
            self._save_registry()
        
        # Load checklist to get task counts
        checklist_file = Path(entry["checklist_file"])
        tasks = {"total": 0, "done": 0, "failed": 0, "pending": 0, "in_progress": 0}
        if checklist_file.exists():
            try:
                with open(checklist_file, 'r', encoding='utf-8') as f:
                    checklist = yaml.safe_load(f)
                if checklist and "tasks" in checklist:
                    for task in checklist["tasks"]:
                        tasks["total"] += 1
                        status = task.get("status", "pending")
                        if status == "done":
                            tasks["done"] += 1
                        elif status == "failed":
                            tasks["failed"] += 1
                        elif status == "pending":
                            tasks["pending"] += 1
                        elif status == "in_progress":
                            tasks["in_progress"] += 1
            except (yaml.YAMLError, IOError) as e:
                logger.warning(f"Failed to load checklist for status: {e}")
        
        entry["tasks"] = tasks
        entry["run_id"] = run_id
        return entry
    
    def stop_run(self, run_id) -> bool:
        """Stop a running process.
        
        Args:
            run_id (str): Run identifier.
        
        Returns:
            bool: True on success.
        """
        if run_id not in self.registry:
            raise KeyError(f"Run {run_id} not found")
        
        entry = self.registry[run_id]
        pid = entry["pid"]
        
        try:
            os.kill(pid, signal.SIGTERM)
            entry["status"] = "stopped"
            self._save_registry()
            logger.info(f"Sent SIGTERM to run {run_id} (PID {pid})")
            return True
        except ProcessLookupError:
            logger.warning(f"Process {pid} for run {run_id} not found")
            entry["status"] = "finished"
            self._save_registry()
            return False
        except PermissionError:
            logger.error(f"Permission denied to signal process {pid}")
            return False
        except Exception as e:
            logger.error(f"Failed to stop run {run_id}: {e}")
            return False
    
    def list_runs(self) -> list[dict]:
        """List all runs sorted by started_at descending."""
        runs = []
        for run_id in self.registry:
            try:
                status = self.get_status(run_id)
                runs.append(status)
            except Exception as e:
                logger.warning(f"Failed to get status for run {run_id}: {e}")
        
        # Sort by started_at descending
        runs.sort(key=lambda x: x.get("started_at", ""), reverse=True)
        return runs
