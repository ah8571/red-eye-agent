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

## 6. Security — Key Management & Least Privilege
- [ ] Write onboarding disclaimer: each key given to the agent must be the most restricted scope available for that service (Supabase service role, Stripe restricted key, DigitalOcean read/scoped token, etc.)
- [ ] Document per-service key scoping guide in setup instructions (Supabase, Stripe, SendGrid, DigitalOcean)
- [ ] Investigate secrets relay pattern: agent receives short-lived tokens from a broker rather than holding long-lived keys directly (e.g., Vault, AWS Secrets Manager, or a thin internal proxy)
- [ ] Build internal privilege enforcement layer: agent_runner.py declares which external APIs each task type is allowed to call; calls outside that allowlist are blocked at runtime (mirrors the GitHub branch-only enforcement already in place)
- [ ] Store provisioning keys separately from code keys in `.env` with explicit naming convention (`PROVISION_SUPABASE_KEY` vs `APP_SUPABASE_KEY`) so scope is visible at a glance

## 7. Audit Logging
- [ ] Add `audit_log.py` module that records every external action: API calls made, files changed, branches pushed, provisioning operations executed
- [ ] Log entries include: timestamp, run_id, task_id, action_type, target (repo/service/resource), outcome
- [ ] Store audit log separately from run logs — append-only, never overwritten
- [ ] Expose audit log viewer in web dashboard (filterable by run, date, action type)
- [ ] On provisioning actions, write audit entry before and after execution (intent + result)

## 8. Docker Sandbox for Code Execution
- [ ] Install Docker on the Droplet
- [ ] Create `Dockerfile.sandbox` with Python/Node/git, non-root user, no network
- [ ] Modify `git_manager.py` to run LLM-generated commands inside container with `--network=none`, `--memory=512m`, `--cpus=1`
- [ ] Keep git operations and LLM API calls outside the sandbox (host only — no env vars inside container)
- [ ] Add sandbox enable/disable flag to `config.yaml`
- [ ] Test that prompt injection via repo file content cannot exfiltrate env vars

## 9. Branch Preview System (Approve & Merge flow)
- [ ] After each agent run, commit changes to a branch (`redeye/<run-id>-<slug>`) instead of directly to main
- [ ] Auto-start a preview server on a dedicated port (8001) from that branch on the Droplet
- [ ] Add `staging.redeyeagent.com` subdomain: A-record → 161.35.119.24, Caddy block reverse-proxying to localhost:8001
- [ ] Add Caddy wildcard cert support via DNS challenge for future `<branch>.preview.redeyeagent.com` per-branch previews
- [ ] Expose "Preview" link, "Approve & Merge", and "Reject & Delete" buttons on each run card in Command Center
- [ ] `POST /api/runs/{run_id}/approve` — merges branch to main, pushes, kills preview server
- [ ] `POST /api/runs/{run_id}/reject` — deletes branch, kills preview server
- [ ] Store `branch_name` and `preview_url` in the run record (registry / DB)
- [ ] Add single-slot constraint: only one active preview at a time; new completed run claims the slot and previous preview is stopped

## Future / Phase 2
- [ ] Scheduled runs (cron-based)
- [ ] Multi-agent parallelism within a single run
- [ ] Usage metering (tokens per user per run)
- [ ] Self-hosted install script (one command to deploy on any VPS)
- [ ] Public API for programmatic checklist submission
- [ ] Infrastructure provisioner (`provisioner.py`): agent calls Supabase/Stripe/DO management APIs for infra tasks declared in checklist

---
*Last updated: April 27, 2026*
