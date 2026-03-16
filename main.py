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
    return "✅ Бот живой и работает!"

# ================= НАСТРОЙКИ =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = float(os.getenv("THRESHOLD", "7.0"))

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: добавь переменные в Render!")
    exit()

exchange = ccxt.mexc()

markets = exchange.load_markets()
symbols = [m['symbol'] for m in markets.values() 
           if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT']

print(f"✅ Запущен мониторинг {len(symbols)} фьючерсов MEXC (7%+)")

def bot_loop():
    last_candle_ts = {}
    while True:
        for symbol in symbols:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=3)
                if len(ohlcv) < 3: continue

                closed_ts = ohlcv[-2][0]
                prev_close = ohlcv[-3][4]
                close = ohlcv[-2][4]
                percent = (close - prev_close) / prev_close * 100

                if symbol not in last_candle_ts or last_candle_ts[symbol] != closed_ts:
                    if percent >= THRESHOLD:
                        base = symbol.split('/')[0]
                        link = f"https://www.tradingview.com/chart/?symbol=MEXC:{base}USDT.P"
                        
                        text = f"""🚨 ПАМП +{percent:.2f}% и более на часовой свече (MEXC)!

Монета: {symbol}
Цена: {close}
Время: {datetime.utcfromtimestamp(closed_ts/1000).strftime('%d.%m %H:%M UTC')}

🔗 График: {link}"""

                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
                        print(f"🚀 Алерт: {symbol} +{percent:.2f}%")

                    last_candle_ts[symbol] = closed_ts
            except:
                pass
        time.sleep(300)

# Запускаем бота в отдельном потоке
threading.Thread(target=bot_loop, daemon=True).start()

# Запускаем Flask (Render требует порт)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
