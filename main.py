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
    return "✅ Бот живой! (4 независимых сигнала)"

# ================= НАСТРОЙКИ =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: добавь TELEGRAM_TOKEN и CHAT_ID")
    exit()
# ============================================

exchange = ccxt.mexc()
markets = exchange.load_markets()
symbols = [m['symbol'] for m in markets.values() 
           if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT']

print(f"✅ Бот запущен — 4 независимых типа сигналов ({len(symbols)} фьючерсов)")

sent_alerts = set()   # для ±7%
sent_condition_alerts = set()  # для слабых и сильных сигналов

def bot_loop():
    while True:
        for symbol in symbols:
            try:
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=7)
                if len(ohlcv) < 7: continue

                prev_close = ohlcv[-2][4]
                candle_ts = ohlcv[-1][0]
                percent = (current_price - prev_close) / prev_close * 100

                alert_key = (symbol, candle_ts)

                # ================= 1 & 2. ПРОСТОЙ ПАМП / ДАМП (±7%) =================
                if abs(percent) >= THRESHOLD and alert_key not in sent_alerts:
                    direction = "ПАМП" if percent > 0 else "ДАМП"
                    emoji = "🔥" if percent > 0 else "❄️"
                    text = f"""{emoji} ПРОСТОЙ {direction} +{abs(percent):.2f}% В МОМЕНТЕ

Монета: {symbol}
Цена: {current_price:.8f}
Изменение: {percent:+.2f}%
Время: {datetime.utcfromtimestamp(candle_ts/1000).strftime('%d.%m %H:%M UTC')}

🔗 График: https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"""

                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                  json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
                    sent_alerts.add(alert_key)

                # ================= 3 & 4. СЛАБЫЙ И СИЛЬНЫЙ СИГНАЛ (по условиям) =================
                condition_key = (symbol, candle_ts, "condition")

                if condition_key not in sent_condition_alerts:
                    # ----- Подсчёт условий -----
                    conditions_met = 0

                    # 1. Funding Rate < -0.05%
                    funding = exchange.fetch_funding_rate(symbol)
                    if funding.get('fundingRate', 0) * 100 < -0.05:
                        conditions_met += 1

                    # 2. RSI(30) < 50 и разворачивается вверх
                    closes = [c[4] for c in ohlcv]
                    rsi30 = 50  # заглушка (можно доработать позже)
                    if rsi30 < 50:  # пока упрощённо
                        conditions_met += 1

                    # 3. Open Interest растёт
                    oi_now = exchange.fetch_open_interest(symbol)['openInterest']
                    oi_prev = exchange.fetch_open_interest_history(symbol, '1h', limit=2)[0]['openInterest']
                    if (oi_now - oi_prev) / oi_prev * 100 > 3:
                        conditions_met += 1

                    # 4. Объём растёт на зелёной свече
                    volume_growth = ohlcv[-1][5] > ohlcv[-2][5] * 1.3
                    is_green = current_price > ohlcv[-1][1]
                    if volume_growth and is_green:
                        conditions_met += 1

                    # 5. Цена у уровня поддержки
                    low_6h = min(c[3] for c in ohlcv[-6:])
                    if abs(current_price - low_6h) / low_6h < 0.02:
                        conditions_met += 1

                    # Отправка сигнала
                    if conditions_met >= 3:
                        text = f"""🚨 СИЛЬНЫЙ СИГНАЛ ({conditions_met}/5 условий)

Монета: {symbol}
Цена: {current_price:.8f}
Условий: {conditions_met}
Время: {datetime.utcfromtimestamp(candle_ts/1000).strftime('%d.%m %H:%M UTC')}"""
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
                        sent_condition_alerts.add(condition_key)

                    elif 1 <= conditions_met <= 2:
                        text = f"""📡 СЛАБЫЙ СИГНАЛ ({conditions_met}/5 условий)

Монета: {symbol}
Цена: {current_price:.8f}
Условий: {conditions_met}
Время: {datetime.utcfromtimestamp(candle_ts/1000).strftime('%d.%m %H:%M UTC')}"""
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                      json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})
                        sent_condition_alerts.add(condition_key)

            except:
                pass

        time.sleep(300)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
