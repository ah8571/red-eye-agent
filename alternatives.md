# Alternatives — Reference Notes

## Open Agents (Vercel)
- **URL:** https://open-agents.dev/
- **Repo:** https://github.com/vercel-labs/open-agents (MIT, ~2.5k stars)
- **What it is:** Open-source reference app for building cloud coding agents on Vercel. Chat-driven — you give it a task via web UI, it works in an isolated Vercel sandbox VM.
- **Architecture:** Web app (Next.js) → Durable workflow (Vercel Workflow SDK) → Sandbox VM. The agent runs *outside* the sandbox and interacts via tools (file ops, shell, search).
- **Key features:**
  - Durable workflows that survive restarts and checkpoint mid-run
  - Isolated Vercel sandboxes (~$0.02/min while active, auto-hibernate)
  - GitHub App integration for clone/branch/push/PR
  - Multi-model support via AI Gateway
  - Explorer + executor subagents for parallel work
  - Snapshot and restore sandbox filesystem state
- **Requirements:** Vercel deployment, PostgreSQL, Vercel OAuth app, GitHub App (with private key, webhook secret), optional Redis/KV
- **Limitations for overnight batch use:**
  - No checklist/batch mode — chat-driven, one task at a time
  - No multi-repo orchestration in a single run
  - No WhatsApp/messaging integration; web UI only
  - Vercel ecosystem lock-in
  - Variable cost vs. flat Droplet pricing
- **Worth stealing:** Durable workflow pattern (checkpoint mid-task, resume on crash)

---

## OpenClaw
- **URL:** https://openclaw.ai/
- **Repo:** https://github.com/openclaw/openclaw (MIT, ~357k stars)
- **What it is:** Personal AI assistant that runs as a daemon on your own machine/server. Connects to WhatsApp, Telegram, Slack, Discord, Signal, iMessage, and 20+ other channels.
- **Architecture:** Gateway (control plane, WebSocket) → Pi agent (RPC) → CLI / apps / nodes. Runs as a systemd/launchd service.
- **Key features:**
  - Built-in WhatsApp (Baileys), Telegram, Slack, Discord, and many more channels
  - Skills/plugin system with a registry (ClawHub)
  - Bash/file/shell tools — can execute code on the host
  - Multi-agent routing across sessions
  - Voice wake + talk mode on macOS/iOS/Android
  - macOS/iOS/Android companion apps
  - Docker sandbox support for non-main sessions
- **Runs on:** Any machine — your laptop, a Droplet, a Raspberry Pi. `npm install -g openclaw@latest && openclaw onboard --install-daemon`
- **Limitations for overnight batch use:**
  - No structured task checklist system
  - No branch-per-task git workflow
  - No test-then-commit safety loop
  - No token budget caps or per-task timeouts
  - Large codebase (TypeScript, 1,648 contributors) — significant learning curve
- **Worth stealing:** WhatsApp integration via Baileys (no Twilio needed), skills architecture, session management

---

## Why We Went Custom
- Purpose-built for serial overnight task execution across multiple repos
- Flat-cost infrastructure ($12/mo Droplet vs. variable sandbox/platform pricing)
- Full control — no ecosystem lock-in
- WhatsApp integration planned for Phase 2 (Twilio or direct Baileys port)
- Simpler to understand, debug, and extend
