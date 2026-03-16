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
    return "✅ Бот живой и работает! (реал-тайм +7% в моменте)"

# ================= НАСТРОЙКИ =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = float(os.getenv("THRESHOLD", "7.0"))

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: добавь переменные в Render!")
    exit()
# ============================================

exchange = ccxt.mexc()

markets = exchange.load_markets()
symbols = [m['symbol'] for m in markets.values() 
           if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT']

print(f"✅ Запущен реал-тайм мониторинг {len(symbols)} фьючерсов MEXC (+7% в моменте свечи)")

last_alert_ts = {}  # чтобы алерт был только 1 раз за свечу

def bot_loop():
    while True:
        for symbol in symbols:
            try:
                # Текущая цена в реальном времени
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']

                # Последняя ЗАКРЫТАЯ часовая свеча
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=2)
                if len(ohlcv) < 2:
                    continue
                prev_close = ohlcv[-2][4]  # закрытие предыдущей свечи
                current_candle_ts = ohlcv[-1][0]  # время текущей свечи

                percent = (current_price - prev_close) / prev_close * 100

                # Проверяем, что это новая свеча и процент уже >= 7%
                if (symbol not in last_alert_ts or last_alert_ts[symbol] != current_candle_ts) and percent >= THRESHOLD:
                    base = symbol.split('/')[0]
                    link = f"https://www.tradingview.com/chart/?symbol=MEXC:{base}USDT.P"
                    
                    text = f"""🚨 ПАМП +{percent:.2f}% В МОМЕНТЕ (часовая свеча формируется)!

Монета: {symbol}
Текущая цена: {current_price}
Рост от предыдущего закрытия: +{percent:.2f}%
Время: {datetime.utcfromtimestamp(current_candle_ts/1000).strftime('%d.%m %H:%M UTC')}

🔗 График: {link}"""

                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                  json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
                    print(f"🚀 РЕАЛ-ТАЙМ алерт: {symbol} +{percent:.2f}%")

                    last_alert_ts[symbol] = current_candle_ts

            except:
                pass

        time.sleep(300)  # проверяем каждые 5 минут

# Запуск
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
