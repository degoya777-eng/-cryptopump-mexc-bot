import ccxt
import requests
import time
import os
import logging
from datetime import datetime
from flask import Flask
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)

@app.route('/')
def home():
    return f"✅ СНАЙПЕР v8.0 (1H+2H + Context 4H) АКТИВЕН. Время: {datetime.now().strftime('%H:%M:%S')}"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0 

exchange = ccxt.mexc({'enableRateLimit': True, 'timeout': 30000, 'options': {'defaultType': 'swap'}})

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logging.error(f"Ошибка TG: {e}")

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

def send_signal_to_tg(symbol, price, percent, tf, current_ohlcv, ohlcv_4h):
    # Считаем RSI сигнального таймфрейма
    rsi_signal = calculate_rsi_wilder([c[4] for c in current_ohlcv])
    # Считаем контекстный RSI (4H)
    rsi_4h = calculate_rsi_wilder([c[4] for c in ohlcv_4h])
    
    tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"
    emoji = "🔥 ПАМП" if percent > 0 else "❄️ ДАМП"
    
    # Визуальный индикатор потенциала (4H RSI)
    potential = "🚀 Есть запас" if rsi_4h < 65 else "⚠️ Перегрев"
    if percent < 0: potential = "🚑 Дно близко" if rsi_4h < 35 else "📉 Падаем дальше"

    msg = (f"<b>{emoji} {percent:+.2f}% ({tf})</b>\n"
           f"Монета: <b>{symbol}</b>\n"
           f"Цена: <code>{price}</code>\n"
           f"───────────────────\n"
           f"📊 RSI ({tf}): {rsi_signal:.1f}\n"
           f"🌍 <b>RSI (4H): {rsi_4h:.1f}</b> ({potential})\n"
           f"───────────────────\n"
           f"🔗 <a href='{tv}'>Открыть график</a>")
    send_msg(msg)

def sniper_loop():
    sent_signals = {} 
    logging.info("Снайпер v8.0 запущен (1H/2H + Контекст 4H).")
    
    while True:
        try:
            try:
                exchange.load_markets()
                tickers = exchange.fetch_tickers()
            except:
                time.sleep(30)
                continue

            active_swaps = []
            for symbol, ticker_data in tickers.items():
                market = exchange.markets.get(symbol)
                if market and market.get('active') and market.get('type') == 'swap' and market.get('quote') == 'USDT':
                    vol = ticker_data.get('quoteVolume', 0) or 0
                    active_swaps.append({'symbol': symbol, 'vol': vol})
            
            active_swaps.sort(key=lambda x: x['vol'], reverse=True)
            symbols = [x['symbol'] for x in active_swaps][:550]

            for symbol in symbols:
                try:
                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker['last']
                    
                    # Тянем 1H, 2H и 4H (для контекста)
                    ohlcv_1h = exchange.fetch_ohlcv(symbol, '1h', limit=20)
                    ohlcv_2h = exchange.fetch_ohlcv(symbol, '2h', limit=20)
                    ohlcv_4h = exchange.fetch_ohlcv(symbol, '4h', limit=20)
                    
                    if not ohlcv_1h or not ohlcv_2h or not ohlcv_4h or len(ohlcv_1h) < 15: continue
                    
                    # Расчеты 1H
                    prev_1h = ohlcv_1h[-2][4]
                    change_1h = (price - prev_1h) / prev_1h * 100
                    ts_1h = ohlcv_1h[-1][0]
                    
                    # Расчеты 2H
                    prev_2h = ohlcv_2h[-2][4]
                    change_2h = (price - prev_2h) / prev_2h * 100
                    ts_2h = ohlcv_2h[-1][0]
                    
                    # 1. Проверка 2H
                    if abs(change_2h) >= THRESHOLD:
                        p_key_2h = f"{symbol}_{ts_2h}_2h"
                        if p_key_2h not in sent_signals:
                            send_signal_to_tg(symbol, price, change_2h, "2H", ohlcv_2h, ohlcv_4h)
                            sent_signals[p_key_2h] = time.time()
                    
                    # 2. Проверка 1H
                    if abs(change_1h) >= THRESHOLD:
                        p_key_1h = f"{symbol}_{ts_1h}_1h"
                        if p_key_1h not in sent_signals:
                            send_signal_to_tg(symbol, price, change_1h, "1H", ohlcv_1h, ohlcv_4h)
                            sent_signals[p_key_1h] = time.time()

                    time.sleep(0.1)
                except:
                    continue

            now = time.time()
            sent_signals = {k: v for k, v in sent_signals.items() if v > (now - 86400)}
            logging.info("Цикл завершен. Пауза 90 секунд.")
            time.sleep(90)
            
        except Exception as e:
            logging.error(f"Ошибка: {e}")
            time.sleep(30)

threading.Thread(target=sniper_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
