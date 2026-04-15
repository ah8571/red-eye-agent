# Red-Eye Agent

Red-Eye Agent — autonomous overnight coding agent powered by DeepSeek/OpenAI/Anthropic

## Features

- **Serial task execution**: Runs tasks one after another, ensuring orderly processing.
- **Multi-repo support**: Works across multiple repositories, each with its own workspace.
- **Budget tracking**: Monitors token usage and cost, with configurable limits per task and per run.
- **Auto-retry on test failure**: Automatically retries failed LLM calls (configurable up to `max_retries_per_task`).
- **Per-task logging**: Each task gets its own log file for detailed debugging.

## Quick Start

1. **Clone the repository**
   ```bash
   git clone https://github.com/ah8571/red-eye-agent.git
   cd red-eye-agent
   ```

2. **Set up environment**
   ```bash
   cp .env.example .env
   # Edit .env and add your API keys (OpenAI, Anthropic, or DeepSeek)
   ```

3. **Configure repositories**
   Edit `config.yaml` and add your repo URLs under the `repos` section.

4. **Define tasks**
   Edit `checklist.yaml` and list the tasks you want the agent to perform.

5. **Run the agent**
   ```bash
   python agent_runner.py
   ```

## Configuration

- **`config.yaml`**: Main configuration file. Defines LLM providers, budget limits, timeouts, repositories, and logging settings.
- **`checklist.yaml`**: Task checklist. Each task has an ID, repository, description, and status. The agent processes tasks with status "pending".

## CLI Flags

The agent runner supports several command-line flags:

- `--dry-run`: Plan only, no changes will be made.
- `--task <id>`: Run only the task with the specified ID.
- `--repo <name>`: Run tasks for a specific repository only.
- `--config <path>`: Path to config file (default: `config.yaml`).
- `--checklist <path>`: Path to checklist file (default: `checklist.yaml`).
- `--status`: Show checklist status and exit.

Example usage:
```bash
python agent_runner.py --dry-run
python agent_runner.py --task 3 --repo my-app
python agent_runner.py --status
```
