"""Entry point: FastAPI (health + OAuth callback) with the Telegram bot and
scheduler running inside the app's lifespan."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from app.agent.loop import Agent
from app.agent.skills import discover
from app.config import get_settings
from app.db import base as db
from app.integrations import google, telegram
from app import scheduler as sched_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    await db.init_db()
    registry = discover()
    agent = Agent(registry)
    app.state.agent = agent
    log.info("skills loaded: %s", ", ".join(registry.names()))

    tasks: list[asyncio.Task] = []
    sched = None
    if s.telegram_bot_token and s.telegram_owner_id:
        bot, dp, notifier = telegram.build(agent)
        tasks.append(asyncio.create_task(telegram.run_polling(bot, dp)))
        sched = sched_mod.build(agent, notifier)
        sched.start()
        log.info("telegram polling and scheduler started")
    else:
        log.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_OWNER_ID not set: running HTTP only")

    try:
        yield
    finally:
        if sched:
            sched.shutdown(wait=False)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await db.dispose()


app = FastAPI(title="Digi Assist", lifespan=lifespan)


@app.get("/health", response_class=PlainTextResponse)
async def health() -> str:
    return "ok"


@app.get("/oauth/google/callback", response_class=PlainTextResponse)
async def google_callback(code: str = "", state: str = "", error: str = "") -> str:
    if error:
        raise HTTPException(400, f"Google returned: {error}")
    if not telegram.consume_oauth_state(state):
        raise HTTPException(400, "Unknown or reused state. Send /connect_google again.")
    await google.finish_auth(code)
    return "Google connected. You can close this tab and go back to Telegram."
