# Developer Roadmap v1

## 1. GitHub App Integration (manual + code)
- [ ] Register a GitHub App at github.com/settings/apps
- [ ] Set callback URL to `http://your-domain/auth/github/callback`
- [ ] Store App ID and private key in `.env`
- [ ] Build OAuth install flow in `web/app.py` (redirect → GitHub → callback → store token)
- [ ] Update `git_manager.py` to use per-repo installation tokens instead of global PAT
- [ ] Write onboarding docs: tell new users to add branch protection rules to their repo

## 2. Agent Context Memory / Internal Wiki
- [ ] Add auto-discovery: if `.agent-wiki.md` exists in repo root, prepend to context automatically
- [ ] After each successful task, append a one-line log entry to `.agent-wiki.md`
- [ ] After each run, generate a wiki summary section via LLM and append to the file
- [ ] Commit wiki updates as part of the agent branch (goes through PR review)
- [ ] Add wiki viewer/editor tab to the web dashboard

## 3. Database Migration (SQLite → Supabase)
- [ ] Add `sqlalchemy` + `alembic` to requirements.txt
- [ ] Create DB models: users, repos, runs, tasks, wiki_entries
- [ ] Replace `web/users.json` reads/writes with DB calls in `web/app.py`
- [ ] Replace `runs/registry.json` reads/writes with DB calls in `process_manager.py`
- [ ] Add DB connection string to `.env`
- [ ] (Manual) Create Supabase project and get connection string

## 4. Notifications
- [ ] (Manual) Set up SMTP credentials — Gmail app password or SendGrid free tier
- [ ] Add `notifier.py` with `send_run_complete()` and `send_run_failed()`
- [ ] Call notifier from `agent_runner.py` at run end
- [ ] Add notification preferences (email, Slack webhook URL) to user profile in dashboard
- [ ] Add Slack/Discord webhook as optional alternative to email

## 5. Async Clarification System
- [ ] Add `needs_clarification` as a valid task status in checklist schema
- [ ] Update LLM prompt in `task_executor.py` to allow flagging uncertainty with `NEEDS_CLARIFICATION:`
- [ ] Parse `NEEDS_CLARIFICATION:` response before attempting file edits
- [ ] Add clarification queue to registry → DB
- [ ] Add "Clarifications Needed" panel to dashboard and command center
- [ ] Add `/api/runs/{run_id}/tasks/{task_id}/clarify` POST endpoint
- [ ] Add resume-from-task logic (partially exists via `--task N` flag)

## Future / Phase 2
- [ ] Scheduled runs (cron-based)
- [ ] Multi-agent parallelism within a single run
- [ ] Usage metering (tokens per user per run)
- [ ] Self-hosted install script (one command to deploy on any VPS)
- [ ] Public API for programmatic checklist submission

---
*Last updated: April 26, 2026*
