"""
Logging setup — per-task log files + console output.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: str = "./logs", level: str = "INFO") -> Path:
    """
    Configure logging with:
    - Console output (INFO+)
    - Run-level log file (everything)

    Returns the log directory path.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Run-level log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_log_file = log_path / f"run_{timestamp}.log"

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
    ))
    root_logger.addHandler(console)

    # File handler (full detail)
    file_handler = logging.FileHandler(run_log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(file_handler)

    return log_path


def get_task_logger(log_dir: Path, task_id: int) -> logging.FileHandler:
    """
    Add a per-task file handler so each task's output goes to its own log.
    Returns the handler (caller should remove it when the task is done).
    """
    task_log_file = log_dir / f"task_{task_id}.log"
    handler = logging.FileHandler(task_log_file, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s │ %(name)-20s │ %(levelname)-7s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)
    return handler
