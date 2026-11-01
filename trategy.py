
import os
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone


API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
BASE_URL = "https://api.twelvedata.com/time_series"


def fetch_candles(symbol, interval, outputsize=200):
    if not API_KEY:
        raise ValueError("TWELVE_DATA_API_KEY is missing")

    params = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": API_KEY,
        "format": "JSON"
    })

    request = urllib.request.Request(
        f"{BASE_URL}?{params}",
        headers={"User-Agent": "AbdullahTradingBot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if "values" not in result:
        message = result.get("message", "No market data returned")
        raise RuntimeError(f"Market data error: {message}")

    candles = []
    for item in reversed(result["values"]):
        candles.append({
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "volume": float(item.get("volume") or 0)
        })

    # Exclude the newest candle because it may still be forming.
    if len(candles) > 1:
        candles = candles[:-1]

    if len(candles) < 60:
        raise ValueError("Not enough completed candles")

    return candles


def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough values for EMA")

    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = (value * multiplier) + (result * (1 - multiplier))

    return result


def calculate_rsi(closes, period=14):
    if len(closes) <= period:
        raise ValueError("Not enough candles for RSI")

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_atr(candles, period=14):
    if len(candles) <= period:
        raise ValueError("Not enough candles for ATR")

    ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous_close = candles[i - 1]["close"]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous_close),
            abs(current["low"] - previous_close)
        )
        ranges.append(true_range)

    return sum(ranges[-period:]) / period


def market_trend(candles):
    closes = [c["close"] for c in candles]
    fast = ema(closes, 20)
    slow = ema(closes, 50)

    if fast > slow:
        return "BUY"
    if fast < slow:
        return "SELL"
    return "NEUTRAL"


def analyze_candles(candles, higher_trends):
    if len(candles) < 60:
        raise ValueError("At least 60 candles are required")

    closes = [c["close"] for c in candles]
    last = candles[-1]
    previous = candles[-2]

    atr = calculate_atr(candles)
    rsi = calculate_rsi(closes)

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    # Liquidity levels from the candles before the signal candle.
    lookback = candles[-21:-1]
    liquidity_high = max(c["high"] for c in lookback)
    liquidity_low = min(c["low"] for c in lookback)

    # Sweep: price takes a prior high/low and closes back inside.
    bullish_sweep = (
        last["low"] < liquidity_low
        and last["close"] > liquidity_low
    )

    bearish_sweep = (
        last["high"] > liquidity_high
        and last["close"] < liquidity_high
    )

    # Short-term structure shift.
    structure = candles[-7:-1]
    previous_high = max(c["high"] for c in structure)
    previous_low = min(c["low"] for c in structure)

    bullish_shift = last["close"] > previous_high
    bearish_shift = last["close"] < previous_low

    # Volume confirmation, when the provider supplies volume.
    volumes = [c["volume"] for c in candles[-21:-1]]
    average_volume = sum(volumes) / len(volumes) if volumes else 0
    volume_confirmed = (
        average_volume > 0
        and last["volume"] >= average_volume * 1.2
    )

    bullish_trend = ema20 > ema50
    bearish_trend = ema20 < ema50

    bullish_htf = all(t == "BUY" for t in higher_trends)
    bearish_htf = all(t == "SELL" for t in higher_trends)

    buy_score = sum([
        bullish_sweep,
        bullish_shift,
        volume_confirmed,
        bullish_trend,
        bullish_htf,
        rsi > 50
    ])

    sell_score = sum([
        bearish_sweep,
        bearish_shift,
        volume_confirmed,
        bearish_trend,
        bearish_htf,
        rsi < 50
    ])

    direction = "WAIT"

    if buy_score >= 5 and buy_score > sell_score:
        direction = "BUY"
    elif sell_score >= 5 and sell_score > buy_score:
        direction = "SELL"

    result = {
        "signal": direction,
        "entry": None,
        "stop_loss": None,
        "take_profit_1": None,
        "take_profit_2": None,
        "take_profit_3": None,
        "rsi": round(rsi, 2),
        "atr": round(atr, 5),
        "buy_score": buy_score,
        "sell_score": sell_score,
        "volume_confirmed": volume_confirmed,
        "time_utc": datetime.now(timezone.utc).isoformat()
    }

    if direction == "BUY":
        entry = last["close"]
        stop = min(last["low"], previous["low"]) - (atr * 0.2)
        risk = entry - stop

        if risk <= 0:
            result["signal"] = "WAIT"
            return result

        result.update({
            "entry": round(entry, 5),
            "stop_loss": round(stop, 5),
            "take_profit_1": round(entry + risk, 5),
            "take_profit_2": round(entry + (risk * 2), 5),
            "take_profit_3": round(entry + (risk * 3), 5)
        })

    elif direction == "SELL":
        entry = last["close"]
        stop = max(last["high"], previous["high"]) + (atr * 0.2)
        risk = stop - entry

        if risk <= 0:
            result["signal"] = "WAIT"
            return result

        result.update({
            "entry": round(entry, 5),
            "stop_loss": round(stop, 5),
            "take_profit_1": round(entry - risk, 5),
            "take_profit_2": round(entry - (risk * 2), 5),
            "take_profit_3": round(entry - (risk * 3), 5)
        })

    return result


def analyze_symbol(symbol, interval="5min"):
    """
    Supported intervals: 5min, 15min, 1h, 4h.
    Uses 15min and 1h as higher-timeframe confirmation
    when analyzing the 5min timeframe.
    """
    candles = fetch_candles(symbol, interval)

    higher_trends = []
    if interval == "5min":
        higher_trends = [
            market_trend(fetch_candles(symbol, "15min")),
            market_trend(fetch_candles(symbol, "1h"))
        ]
    elif interval == "15min":
        higher_trends = [
            market_trend(fetch_candles(symbol, "1h")),
            market_trend(fetch_candles(symbol, "4h"))
        ]

    return analyze_candles(candles, higher_trends)


if __name__ == "__main__":
    try:
        result = analyze_symbol("XAU/USD", "5min")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({
            "signal": "WAIT",
            "error": str(error)
        }, ensure_ascii=False, indent=2))
