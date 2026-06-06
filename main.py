import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_USERNAME = "@TGgreedking"
CHANNEL_URL = "https://t.me/TGgreedking"
WEBHOOK_PATH = "/webhook"
PORT = int(os.environ.get("PORT", 8080))

# On Railway set WEBHOOK_URL=https://<your-service>.up.railway.app/webhook
# On Replit dev the REPLIT_DEV_DOMAIN fallback is used automatically
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
if not WEBHOOK_URL:
    _dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    if _dev_domain:
        WEBHOOK_URL = f"https://{_dev_domain}{WEBHOOK_PATH}"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bot / Dispatcher
# ---------------------------------------------------------------------------

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

users_db: dict = {}
SECRET_PHRASE = "5FN7E"
ITEMS_PER_PAGE = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_URL)]
    ])


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status not in ("left", "kicked", "banned")
    except TelegramBadRequest:
        return False


def get_display_name(user: dict) -> str:
    if user.get("username"):
        return f"@{user['username']}"
    return user["name"]


def get_leaderboard_page(page: int = 1):
    sorted_users = sorted(
        users_db.values(),
        key=lambda x: (-x["score"], x.get("code_entered_at", float("inf"))),
    )
    total_pages = max(1, (len(sorted_users) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * ITEMS_PER_PAGE
    page_users = sorted_users[start_idx: start_idx + ITEMS_PER_PAGE]

    text = f"🏆 **Список лидеров (Страница {page}/{total_pages}):**\n\n"
    for rank, user in enumerate(page_users, start=start_idx + 1):
        text += f"{rank}. {get_display_name(user)} — {user['score']} очков\n"
    if not page_users:
        text += "Список пока пуст. Будьте первым!"

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"leaderboard_page:{page - 1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"leaderboard_page:{page + 1}"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None
    return text, keyboard


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message):
    user_id = str(message.from_user.id)
    if user_id not in users_db:
        users_db[user_id] = {
            "name": message.from_user.first_name,
            "username": message.from_user.username,
            "score": 0,
            "joined_at": time.time(),
        }
    else:
        users_db[user_id]["username"] = message.from_user.username
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n"
        "Для просмотра таблицы лидеров с листанием используй команду /leaderboard"
    )


@router.message(F.text.upper() == SECRET_PHRASE)
async def secret_combination_handler(message: Message, bot: Bot):
    if not await is_subscribed(bot, message.from_user.id):
        await message.answer(
            "❌ Для участия необходимо подписаться на наш канал!",
            reply_markup=get_subscribe_keyboard(),
        )
        return
    user_id = str(message.from_user.id)
    if user_id not in users_db:
        users_db[user_id] = {
            "name": message.from_user.first_name,
            "username": message.from_user.username,
            "score": 0,
            "joined_at": time.time(),
        }
    else:
        users_db[user_id]["username"] = message.from_user.username
    users_db[user_id]["score"] += 10
    users_db[user_id]["code_entered_at"] = time.time()
    await message.answer(
        f"🎉 **Верно!** Вы правильно набрали комбинацию!\n"
        f"➕ Вам начислено 10 очков. Ваш счет: {users_db[user_id]['score']}"
    )


@router.message(Command("leaderboard"))
async def leaderboard_handler(message: Message):
    text, keyboard = get_leaderboard_page(page=1)
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("profile"))
async def profile_handler(message: Message, bot: Bot):
    if not await is_subscribed(bot, message.from_user.id):
        await message.answer(
            "❌ Для просмотра профиля необходимо подписаться на наш канал!",
            reply_markup=get_subscribe_keyboard(),
        )
        return
    user_id = str(message.from_user.id)
    user = users_db.get(user_id)
    if not user or not user.get("code_entered_at"):
        await message.answer(
            "😕 У вас пока нет рейтинга. Введите правильный код, чтобы заработать очки!",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    sorted_users = sorted(
        users_db.values(),
        key=lambda x: (-x["score"], x.get("code_entered_at", float("inf"))),
    )
    rank = next((i + 1 for i, u in enumerate(sorted_users) if u is user), None)
    entered_at = datetime.fromtimestamp(user["code_entered_at"], tz=timezone.utc).strftime(
        "%d.%m.%Y %H:%M:%S UTC"
    )
    text = (
        f"👤 **Ваш профиль:**\n\n"
        f"🏅 Место в рейтинге: **#{rank}**\n"
        f"⭐ Очков: **{user['score']}**\n"
        f"🕐 Последний ввод кода: **{entered_at}**"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)


@router.callback_query(F.data.startswith("leaderboard_page:"))
async def leaderboard_callback_handler(callback: CallbackQuery):
    page = int(callback.data.split(":")[1])
    text, keyboard = get_leaderboard_page(page=page)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        pass
    await callback.answer()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook registered: {WEBHOOK_URL}")
    else:
        logger.warning("No WEBHOOK_URL — webhook not registered (set WEBHOOK_URL env var on Railway)")
    yield
    await bot.delete_webhook()
    await bot.session.close()
    logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> PlainTextResponse:
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return PlainTextResponse("ok")


@app.get("/healthz")
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
