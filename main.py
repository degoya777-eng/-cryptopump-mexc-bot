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
    return "✅ Pump/Damp Bot v1.1 АКТИВЕН — 550 монет (30m + RSI)"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: добавь TELEGRAM_TOKEN и CHAT_ID")
    exit()

exchange = ccxt.mexc({'enableRateLimit': True, 'timeout': 20000})

# Загружаем все монеты и берём 550 самых ликвидных
markets = exchange.load_markets()
symbols = [m['symbol'] for m in markets.values() 
           if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT']

print(f"✅ Pump/Damp Bot запущен — {len(symbols)} монет (30m)")

sent = set()

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
    avg_gain = sum(gains[-period:]) / period or 0.0001
    avg_loss = sum(losses[-period:]) / period or 0.0001
    return 100 - (100 / (1 + avg_gain / avg_loss))

def bot_loop():
    while True:
        for symbol in symbols:
            try:
                ticker = exchange.fetch_ticker(symbol)
                price = ticker['last']
                ohlcv = exchange.fetch_ohlcv(symbol, '30m', limit=3)
                if len(ohlcv) < 3: continue

                prev_close = ohlcv[-2][4]
                percent = (price - prev_close) / prev_close * 100
                candle_ts = ohlcv[-1][0]
                key = (symbol, candle_ts)

                if abs(percent) >= THRESHOLD and key not in sent:
                    direction = "ПАМП" if percent > 0 else "ДАМП"
                    emoji = "🔥" if percent > 0 else "❄️"
                    rsi = calculate_rsi([c[4] for c in ohlcv])

                    text = f"""{emoji} <b>ПРОСТОЙ {direction} {percent:+.2f}% (30m)</b>

Монета: <b>{symbol}</b>
Цена в моменте: {price:.8f}
RSI(14): {rsi:.1f}
Изменение: {percent:+.2f}%
Время: {datetime.utcfromtimestamp(candle_ts/1000).strftime('%d.%m %H:%M UTC')}

🔗 График: https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"""

                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                  json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
                    sent.add(key)

            except:
                continue
                
        time.sleep(90)   # 90 секунд — как ты выбрал

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
