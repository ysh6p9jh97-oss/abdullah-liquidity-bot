import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from strategy import analyze_symbol

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("abdullah_trading_room")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()

ALLOWED_SYMBOLS = {"XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"}
ALLOWED_INTERVALS = {"5min", "15min"}
telegram_app: Optional[Application] = None


def format_price(value):
    if value is None:
        return "—"
    return f"{value:.5f}"


async def reply(update: Update, text: str):
    if update.effective_message:
        await update.effective_message.reply_text(text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(
        update,
        "مرحباً بك في ABDULLAH TRADING ROOM 📊\n\n"
        "الأوامر:\n"
        "/analyze XAU/USD 5min\n"
        "/analyze EUR/USD 15min\n"
        "/status\n"
        "/help\n\n"
        "التحليل إرشادي فقط ولا ينفذ صفقات.",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(
        update,
        "طريقة التحليل:\n"
        "/analyze XAU/USD 5min\n"
        "/analyze EUR/USD 15min\n\n"
        "الأصول المدعومة حالياً: XAU/USD وEUR/USD وGBP/USD وUSD/JPY.\n"
        "الفواصل المدعومة: 5min و15min.",
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token_state = "موجود" if BOT_TOKEN else "غير مضبوط"
    data_state = "موجود" if DATA_API_KEY else "غير مضبوط"
    await reply(
        update,
        "حالة الإعداد:\n"
        f"TELEGRAM_BOT_TOKEN: {token_state}\n"
        f"TWELVE_DATA_API_KEY: {data_state}\n"
        "نجاح الاتصال ببيانات السوق يتأكد عند تنفيذ /analyze.",
    )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return

    if len(context.args) != 2:
        await reply(update, "استخدمي الصيغة:\n/analyze XAU/USD 5min")
        return

    symbol = context.args[0].upper().replace(" ", "")
    interval = context.args[1].lower()

    if symbol not in ALLOWED_SYMBOLS:
        await reply(
            update,
            "الرمز غير مدعوم حالياً.\n"
            "المتاح: XAU/USD, EUR/USD, GBP/USD, USD/JPY",
        )
        return

    if interval not in ALLOWED_INTERVALS:
        await reply(update, "الفاصل المتاح حالياً: 5min أو 15min.")
        return

    if not DATA_API_KEY:
        await reply(
            update,
            "مفتاح TWELVE_DATA_API_KEY غير موجود في إعدادات Render."
        )
        return

    await reply(update, f"⏳ جارٍ تحليل {symbol} على {interval}...")

    try:
        result = await asyncio.to_thread(analyze_symbol, symbol, interval)
    except Exception as exc:
        logger.exception("Analysis failed for %s %s", symbol, interval)
        message = str(exc)
        if "TWELVE_DATA_API_KEY" in message:
            message = "مفتاح بيانات السوق غير مضبوط."
        elif "API" in message or "api" in message or "limit" in message.lower():
            message = "تعذر جلب بيانات السوق. تحققي من مفتاح Twelve Data وحدود خطته."
        else:
            message = "تعذر إكمال التحليل. راجعي سجلات Render لمعرفة السبب."
        await reply(update, f"⚠️ {message}")
        return

    signal = result.get("signal", "WAIT")
    labels = {"BUY": "شراء 🟢", "SELL": "بيع 🔴", "WAIT": "انتظار 🟡"}
    text = (
        f"ABDULLAH TRADING ROOM\n"
        f"الأصل: {symbol}\n"
        f"الفاصل: {interval}\n"
        f"الإشارة: {labels.get(signal, 'انتظار 🟡')}\n"
        f"Entry: {format_price(result.get('entry'))}\n"
        f"SL: {format_price(result.get('stop_loss'))}\n"
        f"TP1: {format_price(result.get('take_profit_1'))}\n"
        f"TP2: {format_price(result.get('take_profit_2'))}\n"
        f"TP3: {format_price(result.get('take_profit_3'))}\n"
        f"RSI: {result.get('rsi', '—')}\n"
        f"ATR: {result.get('atr', '—')}\n"
        f"تأكيد الحجم: {'نعم' if result.get('volume_confirmed') else 'لا'}\n\n"
        "تنبيه: تحليل آلي للمعلومات فقط، وليس توصية استثمارية أو ضماناً للربح."
    )
    await reply(update, text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, "لتحليل السوق استخدمي:\n/analyze XAU/USD 5min")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app

    if not BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN is not configured; Telegram bot disabled.")
        yield
        return

    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("help", help_command))
    telegram_app.add_handler(CommandHandler("status", status))
    telegram_app.add_handler(CommandHandler("analyze", analyze))
    telegram_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    try:
        await telegram_app.initialize()
        await telegram_app.start()
        if telegram_app.updater is None:
            raise RuntimeError("Telegram updater is unavailable")
        await telegram_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot polling started.")
        yield
    finally:
        if telegram_app:
            try:
                if telegram_app.updater and telegram_app.updater.running:
                    await telegram_app.updater.stop()
                if telegram_app.running:
                    await telegram_app.stop()
                await telegram_app.shutdown()
            except Exception:
                logger.exception("Error while shutting down Telegram bot.")
            telegram_app = None


app = FastAPI(
    title="ABDULLAH TRADING ROOM",
    version="1.1.0",
    lifespan=lifespan,
)


@app.get("/")
async def home():
    return {
        "project": "ABDULLAH TRADING ROOM",
        "status": "running",
        "telegram_token_configured": bool(BOT_TOKEN),
        "market_data_key_configured": bool(DATA_API_KEY),
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
