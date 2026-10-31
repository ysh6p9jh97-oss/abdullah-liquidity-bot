import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
telegram_app = None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً بك في ABDULLAH TRADING ROOM 📊\n\n"
        "أوامر البوت:\n"
        "/start - بدء التشغيل\n"
        "/help - المساعدة\n"
        "/status - حالة البوت\n\n"
        "البوت جاهز لاستقبال طلباتك."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك في مؤشر عبدالله.\n"
        "استخدم /status للتحقق من حالة البوت.\n"
        "تنبيه: لا توجد بيانات سوق مباشرة متصلة حاليًا."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🟢 البوت يعمل بنجاح.\n"
        "📡 اتصال Telegram نشط.\n"
        "📊 تغذية بيانات السوق: غير متصلة."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "وصلت رسالتك بنجاح.\n"
        "استخدم /help لمعرفة الأوامر المتاحة."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app

    if BOT_TOKEN:
        telegram_app = (
            Application.builder()
            .token(BOT_TOKEN)
            .build()
        )

        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CommandHandler("help", help_command))
        telegram_app.add_handler(CommandHandler("status", status))
        telegram_app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )

        await telegram_app.initialize()
        await telegram_app.start()

        if telegram_app.updater:
            await telegram_app.updater.start_polling()

        logger.info("Telegram bot started")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN is not configured")

    yield

    if telegram_app:
        if telegram_app.updater:
            await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(
    title="ABDULLAH TRADING ROOM",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def home():
    return {
        "project": "ABDULLAH TRADING ROOM",
        "status": "running",
        "telegram": "connected" if BOT_TOKEN else "token_missing"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
