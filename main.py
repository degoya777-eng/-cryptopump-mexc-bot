import ccxt
import requests
import time
import os
from datetime import datetime
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Бот живой! v3.7 (один сигнал на свечу + улучшенный CVD)"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: добавь TELEGRAM_TOKEN и CHAT_ID")
    exit()

exchange = ccxt.mexc()
markets = exchange.load_markets()

sorted_markets = sorted(
    [m for m in markets.values() if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT'],
    key=lambda x: float(x.get('info', {}).get('volume24', 0) or 0),
    reverse=True
)
symbols = [m['symbol'] for m in sorted_markets[:50]]

print(f"✅ Бот v3.7 запущен (топ-50)")

sent_pump_dump = set()
sent_condition = set()

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
    avg_gain = sum(gains[-period:]) / period or 0.0001
    avg_loss = sum(losses[-period:]) / period or 0.0001
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calculate_cvd(ohlcv):
    if len(ohlcv) < 6: return False
    cvd = []
    cum = 0.0
    for c in ohlcv:
        delta = c[5] if c[4] >= c[1] else -c[5]
        cum += delta
        cvd.append(cum)
    # Улучшенное условие по твоему запросу
    last_delta_positive = (ohlcv[-1][4] - ohlcv[-1][1]) > 0
    cvd_above_zero = cvd[-1] > 0
    return last_delta_positive and cvd_above_zero and (cvd[-3] > cvd[-2] < cvd[-1])

def calculate_cvd_short(ohlcv):
    if len(ohlcv) < 6: return False
    cvd = []
    cum = 0.0
    for c in ohlcv:
        delta = c[5] if c[4] >= c[1] else -c[5]
        cum += delta
        cvd.append(cum)
    last_delta_negative = (ohlcv[-1][4] - ohlcv[-1][1]) < 0
    cvd_below_zero = cvd[-1] < 0
    return last_delta_negative and cvd_below_zero and (cvd[-3] < cvd[-2] > cvd[-1])

def send_msg(text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except: pass

def bot_loop():
    send_msg("🤖 <b>Бот v3.7 запущен</b>\n4 независимых сигнала + улучшенный CVD")

    while True:
        for symbol in symbols:
            try:
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                funding_rate = float(ticker.get('info', {}).get('fundingRate', 0) or 0)

                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=20)
                if len(ohlcv) < 8: continue

                prev_close = ohlcv[-2][4]
                candle_ts = ohlcv[-1][0]
                percent = (current_price - prev_close) / prev_close * 100
                time_str = datetime.utcfromtimestamp(candle_ts / 1000).strftime('%d.%m %H:%M UTC')
                tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"

                key = (symbol, candle_ts)

                # 1 & 2. ПРОСТОЙ ПАМП / ДАМП
                if abs(percent) >= THRESHOLD and key not in sent_pump_dump:
                    direction = "ПАМП" if percent > 0 else "ДАМП"
                    emoji = "🔥" if percent > 0 else "❄️"
                    send_msg(f"{emoji} <b>ПРОСТОЙ {direction} {percent:+.2f}%</b>\nМонета: <b>{symbol}</b>\nЦена: {current_price:.8f}\nВремя: {time_str}\n🔗 <a href='{tv}'>График</a>")
                    sent_pump_dump.add(key)

                # 3. СИЛЬНЫЙ ЛОНГ (3+)
                long_count = 0
                if funding_rate < -0.0005: long_count += 1
                if calculate_rsi([c[4] for c in ohlcv]) < 50: long_count += 1
                if calculate_cvd(ohlcv): long_count += 1
                if ohlcv[-1][5] > ohlcv[-2][5] * 1.4 and current_price > ohlcv[-1][1]: long_count += 1
                low_6h = min(c[3] for c in ohlcv[-6:])
                if abs(current_price - low_6h) / low_6h < 0.025: long_count += 1

                if long_count >= 3:
                    send_msg(f"🚨 <b>СИЛЬНЫЙ ЛОНГ ({long_count}/5)</b>\nМонета: <b>{symbol}</b>\nЦена: {current_price:.8f}\nВремя: {time_str}\n🔗 <a href='{tv}'>График</a>")

                # 4. СИЛЬНЫЙ ШОРТ (4+)
                short_count = 0
                if funding_rate > 0.0005: short_count += 1
                if calculate_rsi([c[4] for c in ohlcv]) > 70: short_count += 1
                if calculate_cvd_short(ohlcv): short_count += 1
                if ohlcv[-1][5] > ohlcv[-2][5] * 1.4 and current_price < ohlcv[-1][1]: short_count += 1
                high_6h = max(c[2] for c in ohlcv[-6:])
                if abs(current_price - high_6h) / high_6h < 0.025: short_count += 1

                if short_count >= 4:
                    send_msg(f"❄️ <b>СИЛЬНЫЙ ШОРТ ({short_count}/5)</b>\nМонета: <b>{symbol}</b>\nЦена: {current_price:.8f}\nВремя: {time_str}\n🔗 <a href='{tv}'>График</a>")

            except:
                continue

        time.sleep(300)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
