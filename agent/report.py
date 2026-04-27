import datetime
import subprocess
from pathlib import Path

def generate_report(results, usage_stats, log_dir):
    """
    Generate a Markdown run report.
    
    Args:
        results: List of dicts with keys: task_id, repo, status, elapsed, error
        usage_stats: Object with input_tokens, output_tokens, estimated_cost attributes
        log_dir: Path object for log directory
    """
    # Create timestamp for filename
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = log_dir / f"run_report_{timestamp}.md"
    
    with open(report_path, "w", encoding="utf-8") as f:
        # Header
        f.write(f"# Run Report — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # Task Summary Table
        f.write("## Task Summary\n\n")
        f.write("| ID | Repository | Status | Elapsed Time (s) |\n")
        f.write("|----|------------|--------|------------------|\n")
        
        for task in results:
            task_id = task.get('task_id', 'N/A')
            repo = task.get('repo', 'N/A')
            status = task.get('status', 'unknown')
            elapsed = task.get('elapsed', 0)
            if isinstance(elapsed, (int, float)):
                elapsed_str = f"{elapsed:.2f}"
            else:
                elapsed_str = str(elapsed)
            
            f.write(f"| {task_id} | {repo} | {status} | {elapsed_str} |\n")
        
        f.write("\n")
        
        # Token Usage and Cost
        f.write("## Token Usage & Cost\n\n")
        f.write(f"- **Input tokens:** {usage_stats.input_tokens:,}" + "\n")
        f.write(f"- **Output tokens:** {usage_stats.output_tokens:,}" + "\n")
        f.write(f"- **Total tokens:** {usage_stats.input_tokens + usage_stats.output_tokens:,}" + "\n")
        f.write(f"- **Estimated cost:** ${usage_stats.estimated_cost:.4f}" + "\n")
        f.write("\n")
        
        # Failed Tasks with Error Messages
        failed_tasks = [t for t in results if t.get('status') == 'failed']
        if failed_tasks:
            f.write("## Failed Tasks\n\n")
            for task in failed_tasks:
                task_id = task.get('task_id', 'N/A')
                repo = task.get('repo', 'N/A')
                error = task.get('error', 'No error message')
                
                f.write(f"### Task {task_id} — {repo}\n")
                f.write(f"**Error:** {error}\n\n")
        else:
            f.write("## Failed Tasks\n\n")
            f.write("No failed tasks.\n\n")
        
        # Summary Statistics
        f.write("## Summary Statistics\n\n")
        
        status_counts = {}
        for task in results:
            status = task.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        
        for status, count in sorted(status_counts.items()):
            f.write(f"- **{status}:** {count}\n")
        
        f.write(f"\n**Total tasks:** {len(results)}\n")
    
    return report_path


def generate_diff_summary(git_manager, branch_name, log_dir):
    """
    Generate a diff summary between main and the given branch.
    
    Args:
        git_manager: GitManager instance for the repository
        branch_name: Name of the branch to compare against main
        log_dir: Path object for log directory
    """
    # Create timestamp for filename
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d")
    diff_path = log_dir / f"diff_summary_{timestamp}.md"
    
    # Run git diff --stat
    cmd = ["git", "diff", f"main..{branch_name}", "--stat"]
    result = subprocess.run(
        cmd,
        cwd=git_manager.workspace_dir,
        capture_output=True,
        text=True,
        timeout=30
    )
    
    with open(diff_path, "w", encoding="utf-8") as f:
        f.write(f"# Diff Summary — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Repository:** {git_manager.name}\n")
        f.write(f"**Branch:** {branch_name}\n\n")
        f.write("## Changed Files\n\n")
        f.write("```\n")
        if result.returncode == 0:
            f.write(result.stdout.strip())
        else:
            f.write(f"Error running git diff: {result.stderr.strip()}")
        f.write("\n```\n")
    
    return diff_path