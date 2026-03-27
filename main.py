import ccxt
import requests
import time
import os
import logging
from datetime import datetime, timezone
from flask import Flask
import threading

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Бот v4.1 LIVE! (90s interval + Funding)"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0

if not TELEGRAM_TOKEN or not CHAT_ID:
    logging.error("❌ Ошибка: проверь TELEGRAM_TOKEN и CHAT_ID")
    exit()

# Инициализация MEXC
exchange = ccxt.mexc({'enableRateLimit': True})

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Ошибка TG: {e}")

def calculate_rsi_wilder(closes, period=14):
    if len(closes) < period + 1: return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
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
    logging.info("Мониторинг запущен (интервал 90с)...")

    while True:
        try:
            markets = exchange.load_markets()
            # Берем только активные фьючерсы USDT
            all_symbols = [m['symbol'] for m in markets.values() if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT']
            symbols = all_symbols[:50] 

            for symbol in symbols:
                try:
                    ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=30)
                    if len(ohlcv) < 20: continue

                    ticker = exchange.fetch_ticker(symbol)
                    current_price = ticker['last']
                    funding = float(ticker.get('info', {}).get('fundingRate', 0) or 0)
                    
                    last_candle = ohlcv[-1]
                    prev_close = ohlcv[-2][4]
                    candle_ts = last_candle[0]
                    percent = (current_price - prev_close) / prev_close * 100
                    
                    tv_link = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"
                    rsi_val = calculate_rsi_wilder([c[4] for c in ohlcv])

                    # Уникальные ключи для блокировки повторов в течение часа
                    p_key = (symbol, candle_ts, 'p')
                    l_key = (symbol, candle_ts, 'l')
                    s_key = (symbol, candle_ts, 's')

                    # --- 1. ПАМП / ДАМП ---
                    if abs(percent) >= THRESHOLD and p_key not in sent_signals:
                        emoji = "🔥 ПАМП" if percent > 0 else "❄️ ДАМП"
                        send_msg(f"<b>{emoji} {percent:+.2f}%</b>\nМонета: {symbol}\nЦена: {current_price}\nФандинг: <code>{funding:.4f}</code>\n🔗 <a href='{tv_link}'>График</a>")
                        sent_signals.add(p_key)

                    # --- 2. СИЛЬНЫЙ ЛОНГ ---
                    l_score = 0
                    if funding < -0.0005: l_score += 1
                    if rsi_val < 45: l_score += 1
                    if calculate_cvd_logic(ohlcv, 'long'): l_score += 1
                    if last_candle[5] > (sum(c[5] for c in ohlcv[-6:-1])/5) * 1.3: l_score += 1
                    
                    if l_score >= 3 and l_key not in sent_signals:
                        send_msg(f"🚨 <b>СИЛЬНЫЙ ЛОНГ ({l_score}/4)</b>\nМонета: {symbol}\nRSI: {rsi_val:.1f}\nФандинг: <code>{funding:.4f}</code>\n🔗 <a href='{tv_link}'>График</a>")
                        sent_signals.add(l_key)

                    # --- 3. СИЛЬНЫЙ ШОРТ ---
                    s_score = 0
                    if funding > 0.0005: s_score += 1
                    if rsi_val > 65: s_score += 1
                    if calculate_cvd_logic(ohlcv, 'short'): s_score += 1
                    if last_candle[5] > (sum(c[5] for c in ohlcv[-6:-1])/5) * 1.3: s_score += 1

                    if s_score >= 3 and s_key not in sent_signals:
                        send_msg(f"❄️ <b>СИЛЬНЫЙ ШОРТ ({s_score}/4)</b>\nМонета: {symbol}\nRSI: {rsi_val:.1f}\nФандинг: <code>{funding:.4f}</code>\n🔗 <a href='{tv_link}'>График</a>")
                        sent_signals.add(s_key)

                    time.sleep(0.6) # Защита от Rate Limit

                except Exception: continue

            # Чистка старых сигналов (старше 24ч)
            now_ms = time.time() * 1000
            sent_signals = {k for k in sent_signals if k[1] > now_ms - 86400000}
            
            time.sleep(90) # Интервал проверки
        except Exception as e:
            logging.error(f"Ошибка цикла: {e}")
            time.sleep(30)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
