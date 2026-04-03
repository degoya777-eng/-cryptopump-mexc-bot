import ccxt
import requests
import time
import os
import logging
from datetime import datetime
import threading
from flask import Flask

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)

@app.route('/')
def home():
    return f"🚀 SNIPER v9.3 (VOLUME) ACTIVE. Time: {datetime.now().strftime('%H:%M:%S')}"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0 

exchange = ccxt.mexc({'enableRateLimit': True, 'timeout': 20000, 'options': {'defaultType': 'swap'}})
sent_signals = {}

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except: pass

def send_alert(symbol, tf, percent, price, peak, open_p, vol_curr, vol_rel, label, ts):
    key = f"{symbol}_{ts}_{tf}"
    if key not in sent_signals:
        tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"
        
        # Индикатор силы объема
        vol_emoji = "💎 СИЛЬНЫЙ" if vol_rel >= 3 else "⚠️ СЛАБЫЙ"
        
        msg = (f"<b>{label} {percent:+.2f}% ({tf})</b>\n"
               f"Монета: <b>{symbol}</b>\n"
               f"Цена: <code>{price}</code> | Пик: <code>{peak}</code>\n"
               f"───────────────────\n"
               f"📊 <b>Объем:</b> ${vol_curr:,.0f}\n"
               f"📈 <b>Рост объема:</b> x{vol_rel:.1f} {vol_emoji}\n"
               f"───────────────────\n"
               f"🔗 <a href='{tv}'>ОТКРЫТЬ ГРАФИК</a>")
        
        send_msg(msg)
        sent_signals[key] = time.time()
        logging.info(f"СИГНАЛ: {symbol} {tf} Vol x{vol_rel:.1f}")

def check_logic(symbol):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=3) # Берем 3 свечи для замера среднего объема
        if not ohlcv or len(ohlcv) < 3: return
        
        curr, prev, pprev = ohlcv[-1], ohlcv[-2], ohlcv[-3]
        price_now = curr[4]
        
        # --- 1H ДАННЫЕ ---
        ts_1h = curr[0]
        o_1h, h_1h, l_1h, v_1h = curr[1], curr[2], curr[3], curr[5]
        v_1h_prev = prev[5]
        # Считаем объем в долларах (приблизительно)
        v_usdt_1h = v_1h * price_now
        v_rel_1h = v_1h / v_1h_prev if v_1h_prev > 0 else 1
        
        s_up_1h = ((h_1h - o_1h) / o_1h) * 100
        s_down_1h = ((o_1h - l_1h) / o_1h) * 100
        
        if s_up_1h >= THRESHOLD:
            send_alert(symbol, "1H", s_up_1h, price_now, h_1h, o_1h, v_usdt_1h, v_rel_1h, "ПАМП 🔥", ts_1h)
        elif s_down_1h >= THRESHOLD:
            send_alert(symbol, "1H", -s_down_1h, price_now, l_1h, o_1h, v_usdt_1h, v_rel_1h, "ДАМП ❄️", ts_1h)

        # --- 2H ДАННЫЕ ---
        ts_2h_start = (ts_1h // 7200000) * 7200000
        if ts_1h == ts_2h_start:
            o_2h, h_2h, l_2h, v_2h = o_1h, h_1h, l_1h, v_1h
            v_2h_prev = pprev[5] + prev[5] # Складываем два часа до этого
        else:
            o_2h = prev[1]
            h_2h = max(prev[2], h_1h)
            l_2h = min(prev[3], l_1h)
            v_2h = prev[5] + v_1h
            v_2h_prev = ohlcv[-3][5] # Для простоты берем пред-предыдущий блок
            
        v_usdt_2h = v_2h * price_now
        v_rel_2h = v_2h / v_2h_prev if v_2h_prev > 0 else 1
        
        s_up_2h = ((h_2h - o_2h) / o_2h) * 100
        s_down_2h = ((o_2h - l_2h) / o_2h) * 100
        
        if s_up_2h >= THRESHOLD:
            send_alert(symbol, "2H", s_up_2h, price_now, h_2h, o_2h, v_usdt_2h, v_rel_2h, "ПАМП 🔥", ts_2h_start)
        elif s_down_2h >= THRESHOLD:
            send_alert(symbol, "2H", -s_down_2h, price_now, l_2h, o_2h, v_usdt_2h, v_rel_2h, "ДАМП ❄️", ts_2h_start)

    except: pass

def sniper_loop():
    while True:
        try:
            exchange.load_markets()
            symbols = [s for s, m in exchange.markets.items() if m['active'] and m['type'] == 'swap' and m['quote'] == 'USDT']
            for symbol in symbols:
                check_logic(symbol)
                time.sleep(0.05)
            now = time.time()
            for k in list(sent_signals.keys()):
                if now - sent_signals[k] > 43200: del sent_signals[k]
            time.sleep(10)
        except Exception as e:
            logging.error(f"Loop Error: {e}")
            time.sleep(30)

threading.Thread(target=sniper_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
