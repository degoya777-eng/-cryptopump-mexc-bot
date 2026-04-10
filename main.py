import ccxt
import requests
import time
import os
import logging
from datetime import datetime
import threading
from flask import Flask

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)

# Глобальные переменные для мониторинга
stats = {
    "start_time": datetime.now(),
    "iterations": 0,
    "errors": 0,
    "signals_sent": 0,
    "last_iteration_time": None
}

@app.route('/')
def home():
    uptime = str(datetime.now() - stats["start_time"]).split('.')[0]
    return (f"✅ OK Uptime: {uptime} "
            f"Итераций: {stats['iterations']} "
            f"Ошибок: {stats['errors']} "
            f"Сигналов: {stats['signals_sent']} "
            f"Последняя: {stats['last_iteration_time']}")

@app.route('/health')
def health():
    return "OK", 200

# Настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0 

# Подключаем MEXC
exchange = ccxt.mexc({
    'enableRateLimit': True, 
    'timeout': 20000, 
    'options': {'defaultType': 'swap'}
})

active_symbols_global = []
sent_signals = {}
last_market_update = 0

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except: pass

def send_alert(symbol, tf, percent, price, o, h, l, vol_curr, vol_rel, label, ts):
    key = f"{symbol}_{ts}_{tf}"
    if key not in sent_signals:
        tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"
        
        # Расчет дисбаланса
        range_hl = h - l if (h - l) > 0 else 0.00000001
        bull_power = ((price - l) / range_hl) * 100
        bear_power = 100 - bull_power
        
        bias_text = f"🟩 Быки {bull_power:.0f}%" if bull_power > 70 else f"🟥 Медведи {bear_power:.0f}%" if bear_power > 70 else "⚖️ Нейтрально"
        peak = h if "ПАМП" in label else l

        msg = (f"<b>{label} {percent:+.2f}% ({tf})</b>\n"
               f"Монета: <b>{symbol}</b>\n"
               f"Цена: <code>{price}</code> | Пик: <code>{peak}</code>\n"
               f"───────────────────\n"
               f"📊 Объём: ${vol_curr:,.0f}\n"
               f"🎯 Дисбаланс: {bias_text}\n"
               f"───────────────────\n"
               f"🔗 <a href='{tv}'>TRADINGVIEW</a>")
        
        send_msg(msg)
        sent_signals[key] = time.time()
        stats["signals_sent"] += 1

def process_heavy_logic(symbol):
    try:
        # Берем 5 свечей, чтобы хватило на 4H (текущая + 3 прошлых) и сравнения объемов
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=6)
        if not ohlcv or len(ohlcv) < 5: return
        
        price_now = ohlcv[-1][4]
        
        # --- 1H LOGIC ---
        c1 = ohlcv[-1]
        o1, h1, l1, v1 = c1[1], c1[2], c1[3], c1[5]
        s_up_1h = ((h1 - o1) / o1) * 100
        s_down_1h = ((o1 - l1) / o1) * 100
        
        if s_up_1h >= THRESHOLD:
            send_alert(symbol, "1H", s_up_1h, price_now, o1, h1, l1, v1*price_now, 1.0, "ПАМП 🔥", c1[0])
        elif s_down_1h >= THRESHOLD:
            send_alert(symbol, "1H", -s_down_1h, price_now, o1, h1, l1, v1*price_now, 1.0, "ДАМП ❄️", c1[0])

        # --- 2H LOGIC (Current + Previous) ---
        c2_prev = ohlcv[-2]
        o2h = c2_prev[1]
        h2h = max(c2_prev[2], h1)
        l2h = min(c2_prev[3], l1)
        s_up_2h = ((h2h - o2h) / o2h) * 100
        s_down_2h = ((o2h - l2h) / o2h) * 100
        
        if s_up_2h >= THRESHOLD:
            send_alert(symbol, "2H", s_up_2h, price_now, o2h, h2h, l2h, (c2_prev[5]+v1)*price_now, 1.0, "ПАМП 🔥", c2_prev[0])
        elif s_down_2h >= THRESHOLD:
            send_alert(symbol, "2H", -s_down_2h, price_now, o2h, h2h, l2h, (c2_prev[5]+v1)*price_now, 1.0, "ДАМП ❄️", c2_prev[0])

        # --- 4H LOGIC (Current + 3 Previous) ---
        c4_start = ohlcv[-4]
        o4h = c4_start[1]
        h4h = max(ohlcv[-4][2], ohlcv[-3][2], ohlcv[-2][2], ohlcv[-1][2])
        l4h = min(ohlcv[-4][3], ohlcv[-3][3], ohlcv[-2][3], ohlcv[-1][3])
        v4h_total = sum(s[5] for s in ohlcv[-4:])
        
        s_up_4h = ((h4h - o4h) / o4h) * 100
        s_down_4h = ((o4h - l4h) / o4h) * 100
        
        if s_up_4h >= THRESHOLD:
            send_alert(symbol, "4H", s_up_4h, price_now, o4h, h4h, l4h, v4h_total*price_now, 1.0, "ПАМП 🔥", c4_start[0])
        elif s_down_4h >= THRESHOLD:
            send_alert(symbol, "4H", -s_down_4h, price_now, o4h, h4h, l4h, v4h_total*price_now, 1.0, "ДАМП ❄️", c4_start[0])
            
    except Exception as e:
        logging.debug(f"Error processing {symbol}: {e}")

def update_markets():
    global active_symbols_global, last_market_update
    try:
        exchange.load_markets()
        active_symbols_global = [s for s, m in exchange.markets.items() if m['active'] and m['type'] == 'swap' and m['quote'] == 'USDT']
        last_market_update = time.time()
    except Exception as e:
        stats["errors"] += 1
        logging.error(f"Market update error: {e}")

def sniper_loop():
    update_markets() 
    while True:
        try:
            if time.time() - last_market_update > 600:
                update_markets()

            for symbol in active_symbols_global:
                process_heavy_logic(symbol)
            
            stats["iterations"] += 1
            stats["last_iteration_time"] = datetime.now().strftime('%H:%M:%S')
            
            # Очистка старых сигналов (раз в 12 часов)
            now = time.time()
            for k in list(sent_signals.keys()):
                if now - sent_signals[k] > 43200: del sent_signals[k]
            
            time.sleep(10)
        except Exception as e:
            stats["errors"] += 1
            logging.error(f"Loop Error: {e}")
            time.sleep(30)

threading.Thread(target=sniper_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
