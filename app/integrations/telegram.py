"""Telegram interface (aiogram 3, long polling).

Only TELEGRAM_OWNER_ID can talk to the bot. Approval cards are inline
keyboards; a tap resolves the approval and runs or discards the action.
"""

from __future__ import annotations

import asyncio
import logging
import secrets

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import approvals
from app.agent.loop import Agent
from app.config import get_settings
from app.integrations import google

log = logging.getLogger(__name__)

# One-time states for the Google OAuth link, so the callback can't be forged.
_oauth_states: set[str] = set()


class TelegramNotifier:
    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id

    async def send(self, text: str) -> None:
        for chunk in _chunks(text):
            await self.bot.send_message(self.chat_id, chunk)

    async def send_approval(self, approval_id: int, summary: str) -> None:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Yes, do it", callback_data=f"apr:{approval_id}:yes"),
                    InlineKeyboardButton(text="No", callback_data=f"apr:{approval_id}:no"),
                ]
            ]
        )
        await self.bot.send_message(self.chat_id, f"Approval #{approval_id}\n\n{summary[:3500]}", reply_markup=kb)


def _chunks(text: str, size: int = 4000) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def build(agent: Agent) -> tuple[Bot, Dispatcher, TelegramNotifier]:
    s = get_settings()
    bot = Bot(token=s.telegram_bot_token)
    dp = Dispatcher()
    notifier = TelegramNotifier(bot, s.telegram_owner_id)
    owner = F.from_user.id == s.telegram_owner_id

    @dp.message(~owner)
    async def _reject(message: Message) -> None:
        log.warning("ignored message from non-owner id=%s", message.from_user.id if message.from_user else None)
        await message.answer("This assistant is private.")

    @dp.message(Command("start"), owner)
    async def _start(message: Message) -> None:
        connected = await google.is_connected()
        await message.answer(
            "Online. Talk to me in plain language.\n"
            f"Google: {'connected' if connected else 'not connected, send /connect_google'}\n"
            "Commands: /brief /pending /connect_google /id"
        )

    @dp.message(Command("id"))
    async def _id(message: Message) -> None:
        await message.answer(f"Your Telegram id is {message.from_user.id if message.from_user else '?'}")

    @dp.message(Command("connect_google"), owner)
    async def _connect(message: Message) -> None:
        state = secrets.token_urlsafe(24)
        _oauth_states.add(state)
        try:
            await message.answer(f"Open this link and allow access:\n{google.auth_url(state)}")
        except RuntimeError as e:
            await message.answer(str(e))

    @dp.message(Command("pending"), owner)
    async def _pending(message: Message) -> None:
        rows = await approvals.pending()
        if not rows:
            await message.answer("Nothing waiting for approval.")
            return
        for a in rows:
            await notifier.send_approval(a.id, a.summary)

    @dp.message(Command("brief"), owner)
    async def _brief(message: Message) -> None:
        await bot.send_chat_action(message.chat.id, "typing")
        reply = await agent.run_turn("Give me the morning brief now.", notifier=notifier)
        await notifier.send(reply)

    @dp.callback_query(F.data.startswith("apr:"))
    async def _approval(cb: CallbackQuery) -> None:
        if not cb.from_user or cb.from_user.id != s.telegram_owner_id:
            await cb.answer("Not yours.", show_alert=True)
            return
        _, raw_id, verdict = cb.data.split(":")
        text = await approvals.resolve(int(raw_id), verdict == "yes", agent.registry, notifier)
        if isinstance(cb.message, Message):
            await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer()
        await notifier.send(text)

    @dp.message(owner, F.text)
    async def _chat(message: Message) -> None:
        assert message.text
        await bot.send_chat_action(message.chat.id, "typing")
        try:
            reply = await agent.run_turn(message.text, notifier=notifier)
        except Exception as e:  # noqa: BLE001
            log.exception("turn failed")
            reply = f"That failed: {type(e).__name__}: {e}"
        await notifier.send(reply)

    @dp.message(owner)
    async def _other(message: Message) -> None:
        await message.answer("Text only for now. Voice notes come in Phase 2.")

    return bot, dp, notifier


def consume_oauth_state(state: str) -> bool:
    if state in _oauth_states:
        _oauth_states.discard(state)
        return True
    return False


async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=False)
    try:
        await dp.start_polling(bot, handle_signals=False)
    except asyncio.CancelledError:
        pass
