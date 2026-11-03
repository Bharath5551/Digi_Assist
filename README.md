# Digi Assist

A personal lifestyle assistant you talk to on Telegram. One agent, a set of skills it loads per task, persistent memory, and an approval gate in front of anything that cannot be undone. Runs on NVIDIA's free hosted Nemotron by default; any OpenAI-compatible endpoint or Claude works with one env var.

Phase 1 (this version): Telegram chat, memory, Gmail, Google Calendar, reminders, a 5 am morning brief.

## How it works

```
Telegram ──> app/integrations/telegram.py ──> app/agent/loop.py ──> app/llm/ (Nemotron / OpenRouter / Claude)
                                                   │
                     ┌─────────────────────────────┼──────────────────────────┐
                     ▼                             ▼                          ▼
             app/skills/<name>/            app/approvals.py             app/audit.py
             SKILL.md + skill.py        yes/no card on Telegram     every tool call logged
```

- `app/agent/router.py` picks which skills to load for a message. With five or fewer optional skills everything is loaded; past that a small model chooses from the skill descriptions.
- `app/agent/loop.py` runs the tool loop in one canonical message format; `app/llm/` converts it for the provider. Tool arguments are validated against the schema before any handler runs, because open models mistype them.
- `app/llm/openai_compat.py` covers NVIDIA NIM, OpenRouter and any OpenAI-style server. `app/llm/anthropic_provider.py` covers Claude (strict tools, prompt caching, server-side fallbacks).
- A tool marked `requires_approval=True` never runs directly. It is queued, you get a card with Yes/No, and only Yes executes it. Sends, deletes and invites are gated. Reads, drafts, reminders and your own events are not.
- `app/skills/memory` is always on. Facts, preferences, people and routines are keyed rows; corrections overwrite.
- `app/scheduler.py` fires the morning brief (`BRIEF_TIME`) and reminders.

## Adding a skill

Create `app/skills/<name>/` with `SKILL.md` (instructions the agent reads when the skill is loaded) and `skill.py` exporting `SKILL = Skill(...)` with its tools. Nothing else changes. Mark any tool that sends, deletes or spends with `requires_approval=True` and give it a `summarize` so the approval card is readable.

## Running it

### 1. Accounts you need

- A model API key. Default: free NVIDIA key from https://build.nvidia.com/settings/api-keys (no card; roughly 40 requests a minute shared across models). Alternatives: OpenRouter (`LLM_PROVIDER=openrouter`, `MODEL=nvidia/nemotron-3-super-120b-a12b:free`) or Claude (`LLM_PROVIDER=anthropic`, `MODEL=claude-opus-5-5`).
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

The loop, approval gate, argument validation, persistence, skill discovery and the OpenAI-format conversion are tested against a fake provider. Gmail and Calendar calls are thin wrappers over the Google client and are exercised manually.

## Known limits in Phase 1

- Free Nemotron is good enough for chat and single tool calls. Multi-step tool use is less reliable than Claude; expect occasional wrong arguments (rejected and retried) or a skipped step. The approval gate is enforced in code either way. The 40 requests/min cap is per key and NVIDIA may throttle or retire models without notice.
- Text only on Telegram. Voice notes are Phase 2.
- Memory search is keyword match, not semantic. Fine for a few hundred facts; pgvector arrives when that stops being true.
- Schema is created with `create_all` at startup. Alembic migrations arrive with Phase 2, when the schema starts changing under live data.
- One owner. The bot refuses every other Telegram user.
