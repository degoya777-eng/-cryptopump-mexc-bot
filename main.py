import ccxt
import requests
import time
import os
import logging
from datetime import datetime, timezone
from flask import Flask
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Бот v4.2 работает! (5 условий + % Funding)"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0

exchange = ccxt.mexc({'enableRateLimit': True})

def get_funding_status(val):
    abs_val = abs(val)
    if abs_val < 0.0003: return "🟢" # Нейтральный
    if abs_val < 0.001: return "⚠️"  # Повышенный
    return "🚨" # Экстремальный

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except: pass

def calculate_rsi_wilder(closes, period=14):
    if len(closes) < period + 1: return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [max(0, d) for d in deltas]
    losses = [max(0, -d) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0: return 100
    return 100 - (100 / (1 + (avg_gain / avg_loss)))

def calculate_cvd_logic(ohlcv, mode='long'):
    if len(ohlcv) < 6: return False
    cvd = []
    cum = 0.0
    for c in ohlcv:
        delta = c[5] if c[4] >= c[1] else -c[5]
        cum += delta
        cvd.append(cum)
    if mode == 'long':
        return ohlcv[-1][4] > ohlcv[-1][1] and cvd[-1] > 0 and (cvd[-3] > cvd[-2] < cvd[-1])
    else:
        return ohlcv[-1][4] < ohlcv[-1][1] and cvd[-1] < 0 and (cvd[-3] < cvd[-2] > cvd[-1])

def bot_loop():
    sent_signals = set()
    while True:
        try:
            markets = exchange.load_markets()
            symbols = [m['symbol'] for m in markets.values() if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT'][:50]

            for symbol in symbols:
                try:
                    ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=30)
                    if len(ohlcv) < 20: continue
                    ticker = exchange.fetch_ticker(symbol)
                    
                    price = ticker['last']
                    funding = float(ticker.get('info', {}).get('fundingRate', 0) or 0)
                    f_pct = funding * 100
                    f_status = get_funding_status(funding)
                    
                    ts = ohlcv[-1][0]
                    prev_close = ohlcv[-2][4]
                    percent = (price - prev_close) / prev_close * 100
                    rsi = calculate_rsi_wilder([c[4] for c in ohlcv])
                    tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"

                    # --- ЛОГИКА LONG ---
                    l_count = 0
                    if funding < -0.0005: l_count += 1
                    if rsi < 45: l_count += 1
                    if calculate_cvd_logic(ohlcv, 'long'): l_count += 1
                    if ohlcv[-1][5] > (sum(c[5] for c in ohlcv[-6:-1])/5) * 1.3: l_count += 1
                    low_6h = min(c[3] for c in ohlcv[-6:])
                    if (price - low_6h) / low_6h < 0.02: l_count += 1 # 5-е условие: цена у дна 6ч

                    l_key = (symbol, ts, 'long')
                    if l_count >= 3 and l_key not in sent_signals:
                        send_msg(f"🚨 <b>СИЛЬНЫЙ ЛОНГ ({l_count}/5)</b>\nМонета: {symbol}\nRSI: {rsi:.1f}\nФандинг: {f_status} <code>{f_pct:.4f}%</code>\n🔗 <a href='{tv}'>График</a>")
                        sent_signals.add(l_key)

                    # --- ЛОГИКА SHORT ---
                    s_count = 0
                    if funding > 0.0005: s_count += 1
                    if rsi > 65: s_count += 1
                    if calculate_cvd_logic(ohlcv, 'short'): s_count += 1
                    if ohlcv[-1][5] > (sum(c[5] for c in ohlcv[-6:-1])/5) * 1.3: s_count += 1
                    high_6h = max(c[2] for c in ohlcv[-6:])
                    if (high_6h - price) / price < 0.02: s_count += 1 # 5-е условие: цена у пика 6ч

                    s_key = (symbol, ts, 'short')
                    if s_count >= 3 and s_key not in sent_signals:
                        send_msg(f"❄️ <b>СИЛЬНЫЙ ШОРТ ({s_count}/5)</b>\nМонета: {symbol}\nRSI: {rsi:.1f}\nФандинг: {f_status} <code>{f_pct:.4f}%</code>\n🔗 <a href='{tv}'>График</a>")
                        sent_signals.add(s_key)

                    # ПАМП/ДАМП
                    p_key = (symbol, ts, 'p')
                    if abs(percent) >= THRESHOLD and p_key not in sent_signals:
                        dir_text = "ПАМП 🔥" if percent > 0 else "ДАМП ❄️"
                        send_msg(f"<b>{dir_text} {percent:+.2f}%</b>\nМонета: {symbol}\nФандинг: {f_status} <code>{f_pct:.4f}%</code>\n🔗 <a href='{tv}'>График</a>")
                        sent_signals.add(p_key)

                    time.sleep(0.6)
                except: continue

            sent_signals = {k for k in sent_signals if k[1] > (time.time()*1000 - 86400000)}
            time.sleep(90)
        except: time.sleep(30)

threading.Thread(target=bot_loop, daemon=True).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
