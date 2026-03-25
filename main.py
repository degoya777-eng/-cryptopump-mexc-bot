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
    return "✅ Бот живой! (твои условия + памп/дамп 7% в моменте)"

# ================= НАСТРОЙКИ =================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0                     # 7% для пампа и дампа

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: добавь TELEGRAM_TOKEN и CHAT_ID")
    exit()
# ============================================

exchange = ccxt.mexc()

markets = exchange.load_markets()
symbols = [m['symbol'] for m in markets.values() 
           if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT']

print(f"✅ Запущен бот по ТВОИМ условиям — {len(symbols)} фьючерсов MEXC")

sent_alerts = set()

def calculate_rsi(prices, period=30):
    """Простой расчёт RSI(30)"""
    gains = [max(0, prices[i] - prices[i-1]) for i in range(1, len(prices))]
    losses = [max(0, prices[i-1] - prices[i]) for i in range(1, len(prices))]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def bot_loop():
    while True:
        for symbol in symbols:
            try:
                # 1. Текущая цена
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']

                # 2. Последние 2 часовые свечи
                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=7)
                if len(ohlcv) < 7: continue

                prev_close = ohlcv[-2][4]
                candle_ts = ohlcv[-1][0]
                percent_change = (current_price - prev_close) / prev_close * 100

                # 3. Funding Rate
                funding = exchange.fetch_funding_rate(symbol)
                funding_rate = funding.get('fundingRate', 0) * 100

                # 4. Open Interest (рост)
                oi_now = exchange.fetch_open_interest(symbol)['openInterest']
                oi_prev = exchange.fetch_open_interest_history(symbol, '1h', limit=2)[0]['openInterest']
                oi_growth = (oi_now - oi_prev) / oi_prev * 100 if oi_prev > 0 else 0

                # 5. Объём и зелёная свеча
                volume_now = ohlcv[-1][5]
                volume_prev = ohlcv[-2][5]
                volume_growth = volume_now > volume_prev * 1.3

                is_green = current_price > ohlcv[-1][1]  # close > open

                # 6. RSI(30)
                closes = [c[4] for c in ohlcv]
                rsi30 = calculate_rsi(closes)
                rsi_rising = rsi30 > closes[-2]   # грубый разворот вверх

                # 7. Цена у поддержки (локальный минимум последних 6 часов)
                low_6h = min(c[3] for c in ohlcv[-6:])
                near_support = abs(current_price - low_6h) / low_6h < 0.015  # в пределах 1.5%

                # Считаем количество совпавших условий
                conditions_met = 0
                if funding_rate < -0.05: conditions_met += 1
                if rsi30 < 50 and rsi_rising: conditions_met += 1
                if oi_growth > 5: conditions_met += 1
                if volume_growth and is_green: conditions_met += 1
                if near_support: conditions_met += 1

                alert_key = (symbol, candle_ts)

                # Памп или дамп 7%
                if abs(percent_change) >= THRESHOLD and alert_key not in sent_alerts:
                    signal_type = "🚨 СИЛЬНЫЙ" if conditions_met >= 3 else "📡 ОБЫЧНЫЙ"

                    direction = "ПАМП" if percent_change > 0 else "ДАМП"
                    emoji = "🔥" if percent_change > 0 else "❄️"

                    text = f"""{emoji} {signal_type} СИГНАЛ {direction} +{abs(percent_change):.2f}% В МОМЕНТЕ

Монета: {symbol}
Цена: {current_price:.8f}
Рост/падение: {percent_change:+.2f}%
Условий совпало: {conditions_met}/5
Funding: {funding_rate:+.4f}%
RSI(30): {rsi30:.1f}
OI рост: {oi_growth:+.1f}%
Время: {datetime.utcfromtimestamp(candle_ts/1000).strftime('%d.%m %H:%M UTC')}

🔗 График: https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"""

                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                                  json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})

                    sent_alerts.add(alert_key)

            except:
                pass

        time.sleep(300)  # каждые 5 минут

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
