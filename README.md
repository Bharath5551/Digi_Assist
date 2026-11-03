# Digi Assist

A personal lifestyle assistant you talk to on Telegram. One Claude agent, a set of skills it loads per task, persistent memory, and an approval gate in front of anything that cannot be undone.

Phase 1 (this version): Telegram chat, memory, Gmail, Google Calendar, reminders, a 5 am morning brief.

## How it works

```
Telegram ──> app/integrations/telegram.py ──> app/agent/loop.py ──> Claude (Messages API, tool use)
                                                   │
                     ┌─────────────────────────────┼──────────────────────────┐
                     ▼                             ▼                          ▼
             app/skills/<name>/            app/approvals.py             app/audit.py
             SKILL.md + skill.py        yes/no card on Telegram     every tool call logged
```

- `app/agent/router.py` picks which skills to load for a message. With five or fewer optional skills everything is loaded; past that a small model chooses from the skill descriptions.
- `app/agent/loop.py` runs the Messages API tool loop. Thinking blocks and tool calls are stored as raw content blocks in Postgres so the conversation round-trips exactly.
- A tool marked `requires_approval=True` never runs directly. It is queued, you get a card with Yes/No, and only Yes executes it. Sends, deletes and invites are gated. Reads, drafts, reminders and your own events are not.
- `app/skills/memory` is always on. Facts, preferences, people and routines are keyed rows; corrections overwrite.
- `app/scheduler.py` fires the morning brief (`BRIEF_TIME`) and reminders.

## Adding a skill

Create `app/skills/<name>/` with `SKILL.md` (instructions the agent reads when the skill is loaded) and `skill.py` exporting `SKILL = Skill(...)` with its tools. Nothing else changes. Mark any tool that sends, deletes or spends with `requires_approval=True` and give it a `summarize` so the approval card is readable.

## Running it

### 1. Accounts you need

- An Anthropic API key.
- A Telegram bot: message `@BotFather`, `/newbot`, copy the token. Then message your bot `/id` once it is running to learn your numeric id (or temporarily run it with `TELEGRAM_OWNER_ID=0`, send `/id`, and set it).
- Google Cloud project with Gmail API, Calendar API and Tasks API enabled, and an OAuth client of type **Web application** whose redirect URI is `<PUBLIC_BASE_URL>/oauth/google/callback`. While the app is in "Testing" status add your Gmail address as a test user.

### 2. Local

```bash
cp .env.example .env   # fill it in; sqlite is fine locally
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

For the Google OAuth redirect to reach a local machine use something like `cloudflared tunnel --url http://localhost:8000` and put that URL in `PUBLIC_BASE_URL` and in the Google console.

### 3. Server (Docker Compose, one small VPS)

```bash
cp .env.example .env            # fill in; leave DATABASE_URL to compose
sed -i 's/assistant.example.com/your.domain/' Caddyfile
docker compose up -d --build
docker compose logs -f app
```

Caddy gets the HTTPS certificate on its own. Only `/health` and `/oauth/*` are reachable from outside; Telegram uses long polling so nothing inbound is needed for chat.

Then in Telegram: `/start`, `/connect_google`, open the link, allow, and talk.

## Tests

```bash
pytest
```

The loop, approval gate, persistence and skill discovery are tested against a fake Claude client. Gmail and Calendar calls are thin wrappers over the Google client and are exercised manually.

## Known limits in Phase 1

- Text only on Telegram. Voice notes are Phase 2.
- Memory search is keyword match, not semantic. Fine for a few hundred facts; pgvector arrives when that stops being true.
- Schema is created with `create_all` at startup. Alembic migrations arrive with Phase 2, when the schema starts changing under live data.
- One owner. The bot refuses every other Telegram user.
