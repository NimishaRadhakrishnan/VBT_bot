"""Telegram adapter. It only converts Telegram updates <-> API calls; no agricultural logic here.

Run:  python -m agri.telegram_bot      (polling: works on a laptop, no public URL needed)
      TELEGRAM_MODE=webhook ...         (server with HTTPS)"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
                           BotCommand)

from .config import get_settings

log = logging.getLogger("telegram")
s = get_settings()
dp = Dispatcher()
_seen_groups: dict[str, float] = {}
CASE_RE = re.compile(r"Case #([0-9A-F]{6})")


def keyboard(buttons: list[dict]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    rows, row = [], []
    for b in buttons:
        row.append(InlineKeyboardButton(text=b["label"][:60], callback_data=b["payload"][:64]))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def call_api(chat_id: int, name: str | None, *, text=None, button=None, image: bytes | None = None,
                   voice: bytes | None = None, key: str | None = None) -> dict:
    data = {"user_ref": str(chat_id), "channel": "telegram"}
    for k, v in (("text", text), ("button", button), ("user_name", name), ("idempotency_key", key)):
        if v:
            data[k] = v
    files = []
    if image:
        files.append(("images", ("photo.jpg", image, "image/jpeg")))
    if voice:
        files.append(("voice", ("voice.ogg", voice, "audio/ogg")))
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{s.api_base_url}/v1/chat/messages", data=data, files=files or None,
                         headers={"X-API-Key": s.api_key})
        r.raise_for_status()
        return r.json()


async def _download(bot: Bot, file_id: str) -> bytes:
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)  # Bot API limit: 20 MB
    return buf.getvalue()


async def deliver(bot: Bot, chat_id: int, reply: dict) -> None:
    text = reply["text"]
    kb = keyboard(reply.get("buttons", []))
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
    for i, ch in enumerate(chunks):
        await bot.send_message(chat_id, ch, reply_markup=kb if i == len(chunks) - 1 else None)
    if reply.get("escalate") and s.agronomist_chat_id:
        await bot.send_message(int(s.agronomist_chat_id), reply["escalation_summary"])
        async with httpx.AsyncClient(timeout=60) as c:
            for p in reply.get("escalation_images", []):
                r = await c.get(f"{s.api_base_url}/v1/media/{Path(p).name}", headers={"X-API-Key": s.api_key})
                if r.status_code == 200:
                    await bot.send_photo(int(s.agronomist_chat_id), BufferedInputFile(r.content, "case.jpg"))


async def process(message: Message, bot: Bot, **kw) -> None:
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        reply = await call_api(message.chat.id, message.from_user.full_name if message.from_user else None,
                               key=f"tg:{message.chat.id}:{message.message_id}", **kw)
    except Exception as e:
        log.exception("API call failed: %s", e)
        await message.answer("Sorry, the service is busy. Please try again. / மன்னிக்கவும், மீண்டும் முயற்சிக்கவும்.")
        return
    await deliver(bot, message.chat.id, reply)


def _is_agronomist_chat(message: Message) -> bool:
    return bool(s.agronomist_chat_id) and str(message.chat.id) == str(s.agronomist_chat_id)


@dp.message(CommandStart())
async def start(message: Message, bot: Bot):
    await process(message, bot, button="/start")


@dp.message(Command("new"))
async def new(message: Message, bot: Bot):
    await process(message, bot, button="/new")


@dp.message(Command("language"))
async def language(message: Message, bot: Bot):
    await process(message, bot, button="/language")


@dp.message(Command("agronomist"))
async def agronomist(message: Message, bot: Bot):
    await process(message, bot, button="/agronomist")


@dp.message(Command("help"))
async def help_(message: Message, bot: Bot):
    await process(message, bot, button="/start")


@dp.message(F.reply_to_message, F.text, F.func(_is_agronomist_chat))
async def agronomist_answer(message: Message, bot: Bot):
    """An agronomist replies (Telegram 'reply') to a case summary in the agronomist group."""
    m = CASE_RE.search(message.reply_to_message.text or "")
    if not m:
        return
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{s.api_base_url}/v1/escalations/{m.group(1)}/reply", json={"text": message.text},
                         headers={"X-API-Key": s.api_key})
    if r.status_code != 200:
        await message.reply(f"Could not find case #{m.group(1)}")
        return
    out = r.json()
    await bot.send_message(int(out["user_ref"]), out["text"])
    await message.reply("✅ Sent to farmer.")


@dp.message(F.photo)
async def photo(message: Message, bot: Bot):
    if message.media_group_id:  # album: diagnose the first photo, ignore duplicates of the same plant
        if message.media_group_id in _seen_groups:
            return
        _seen_groups[message.media_group_id] = asyncio.get_event_loop().time()
    img = await _download(bot, message.photo[-1].file_id)  # largest size
    await process(message, bot, image=img, text=message.caption)


@dp.message(F.document.mime_type.startswith("image/"))
async def image_document(message: Message, bot: Bot):
    img = await _download(bot, message.document.file_id)  # uncompressed photo sent as file
    await process(message, bot, image=img, text=message.caption)


@dp.message(F.voice | F.audio)
async def voice(message: Message, bot: Bot):
    fid = message.voice.file_id if message.voice else message.audio.file_id
    await process(message, bot, voice=await _download(bot, fid))


@dp.message(F.text)
async def text(message: Message, bot: Bot):
    if _is_agronomist_chat(message):
        return
    await process(message, bot, text=message.text)


@dp.callback_query()
async def button(cb: CallbackQuery, bot: Bot):
    await cb.answer()
    if cb.message is None:
        return
    await bot.send_chat_action(cb.message.chat.id, ChatAction.TYPING)
    reply = await call_api(cb.message.chat.id, cb.from_user.full_name, button=cb.data, key=f"cb:{cb.id}")
    await deliver(bot, cb.message.chat.id, reply)


COMMANDS = [BotCommand(command="start", description="Start / தொடங்கு"),
            BotCommand(command="new", description="New problem / புதிய கேள்வி"),
            BotCommand(command="agronomist", description="Talk to agronomist / நிபுணரிடம் பேச"),
            BotCommand(command="language", description="Tamil / English")]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not s.telegram_bot_token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env (create a bot with @BotFather).")
    bot = Bot(s.telegram_bot_token)

    async def on_startup(bot: Bot):
        await bot.set_my_commands(COMMANDS)

    dp.startup.register(on_startup)
    if s.telegram_mode == "webhook":
        from aiohttp import web
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

        async def set_hook(bot: Bot):
            await bot.set_webhook(s.telegram_webhook_url, secret_token=s.telegram_webhook_secret or None)

        dp.startup.register(set_hook)
        app = web.Application()
        SimpleRequestHandler(dp, bot, secret_token=s.telegram_webhook_secret or None).register(app, path="/telegram/webhook")
        setup_application(app, dp, bot=bot)
        web.run_app(app, host="0.0.0.0", port=8081)
    else:
        asyncio.run(dp.start_polling(bot))


if __name__ == "__main__":
    main()
