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
    return "✅ Бот живой! v3.4"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0
TOP_SYMBOLS = 50

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: добавь TELEGRAM_TOKEN и CHAT_ID")
    exit()

exchange = ccxt.mexc()
markets = exchange.load_markets()

# Топ-50 самых ликвидных
sorted_markets = sorted(
    [m for m in markets.values() if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT'],
    key=lambda x: float(x.get('info', {}).get('volume24', 0) or 0),
    reverse=True
)
symbols = [m['symbol'] for m in sorted_markets[:TOP_SYMBOLS]]

print(f"✅ Бот запущен (топ-{TOP_SYMBOLS} самых ликвидных фьючерсов)")

sent_pump_dump = set()
sent_condition = set()
prev_oi = {}

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
    avg_gain = sum(gains[-period:]) / period or 0.0001
    avg_loss = sum(losses[-period:]) / period or 0.0001
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calculate_cvd(ohlcv, sensitivity=1.5):   # ← подкрутили до 1.5 (меньше ложных)
    if len(ohlcv) < 6:
        return False
    cvd = []
    cumulative = 0.0
    for c in ohlcv:
        delta = c[5] if c[4] >= c[1] else -c[5]
        cumulative += delta
        cvd.append(cumulative)
    # Разворот: падал → развернулся вверх
    return (cvd[-3] > cvd[-2] < cvd[-1]) and cvd[-1] > 0

def send_msg(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except: pass

def bot_loop():
    send_msg("🤖 <b>MEXC Signal Bot v3.4 запущен!</b>\nТоп-50 ликвидных фьючерсов\nCVD sensitivity = 1.5")

    while True:
        for symbol in symbols:
            try:
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                funding_rate = float(ticker.get('info', {}).get('fundingRate', 0) or 0)

                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=20)
                if len(ohlcv) < 8: continue

                closes = [c[4] for c in ohlcv]
                prev_close = ohlcv[-2][4]
                candle_ts = ohlcv[-1][0]
                percent = (current_price - prev_close) / prev_close * 100
                time_str = datetime.utcfromtimestamp(candle_ts / 1000).strftime('%d.%m %H:%M UTC')
                tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"

                # Простой памп / дамп
                pump_key = (symbol, candle_ts)
                if abs(percent) >= THRESHOLD and pump_key not in sent_pump_dump:
                    direction = "ПАМП" if percent > 0 else "ДАМП"
                    emoji = "🔥" if percent > 0 else "❄️"
                    send_msg(f"{emoji} <b>ПРОСТОЙ {direction} {percent:+.2f}%</b>\nМонета: <b>{symbol}</b>\nЦена: {current_price:.8f}\nВремя: {time_str}\n🔗 <a href='{tv}'>График</a>")
                    sent_pump_dump.add(pump_key)

                # Условия
                cond_key = (symbol, candle_ts, "cond")
                if cond_key in sent_condition: continue

                conditions = []

                if funding_rate < -0.0005:
                    conditions.append(f"💰 Funding: {funding_rate*100:.4f}%")

                rsi = calculate_rsi(closes)
                if rsi < 50:                                      # ← как ты хотел
                    conditions.append(f"📉 RSI(14): {rsi:.1f}")

                if calculate_cvd(ohlcv, sensitivity=1.5):        # ← подкрутили чувствительность
                    conditions.append("🔄 CVD разворот вверх")

                if ohlcv[-1][5] > ohlcv[-2][5] * 1.4 and current_price > ohlcv[-1][1]:
                    conditions.append("📈 Объём +40% и бычья свеча")

                low_6h = min(c[3] for c in ohlcv[-6:])
                if abs(current_price - low_6h) / low_6h < 0.025:
                    conditions.append("🛡️ Цена у поддержки")

                count = len(conditions)

                if count >= 3:
                    send_msg(f"🚨 <b>СИЛЬНЫЙ СИГНАЛ ({count}/5)</b>\nМонета: <b>{symbol}</b>\nЦена: {current_price:.8f}\nВремя: {time_str}\n🔗 <a href='{tv}'>График</a>")
                elif count >= 1:
                    send_msg(f"📡 <b>Слабый сигнал ({count}/5)</b>\nМонета: <b>{symbol}</b>\nЦена: {current_price:.8f}\nВремя: {time_str}\n🔗 <a href='{tv}'>График</a>")

                sent_condition.add(cond_key)

            except:
                continue

        time.sleep(300)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
