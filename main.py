import ccxt
import requests
import time
import os
import logging
from datetime import datetime, timedelta
import threading
from flask import Flask

# Настройка логов, чтобы видеть работу в консоли Render/Heroku
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)

@app.route('/')
def home():
    return f"🚀 SNIPER v9.1 (STABLE) ACTIVE. Time: {datetime.now().strftime('%H:%M:%S')}"

# --- НАСТРОЙКИ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0 

# Инициализация MEXC
exchange = ccxt.mexc({
    'enableRateLimit': True, 
    'timeout': 20000, 
    'options': {'defaultType': 'swap'}
})

sent_signals = {}

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logging.error(f"TG Error: {e}")

def check_logic(symbol, tf):
    """Логика Open-High для моментального захвата импульса"""
    try:
        # Запрашиваем всего 2 свечи (минимальный вес данных)
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=2)
        if not ohlcv or len(ohlcv) < 2: return
        
        o = ohlcv[-1][1]  # Открытие текущей свечи
        h = ohlcv[-1][2]  # Максимум (High) в моменте
        c = ohlcv[-1][4]  # Текущая цена
        
        # Главная формула: считаем прострел вверх (памп)
        spike_up = ((h - o) / o) * 100
        # Считаем прострел вниз (дамп)
        spike_down = ((o - ohlcv[-1][3]) / o) * 100 
        
        # Проверка на Памп
        if spike_up >= THRESHOLD:
            send_alert(symbol, tf, spike_up, c, h, o, "ПАМП 🔥", ohlcv[-1][0])
            
        # Проверка на Дамп
        elif spike_down >= THRESHOLD:
            send_alert(symbol, tf, -spike_down, c, ohlcv[-1][3], o, "ДАМП ❄️", ohlcv[-1][0])

    except:
        pass

def send_alert(symbol, tf, percent, price, peak, open_p, label, ts):
    key = f"{symbol}_{ts}_{tf}"
    if key not in sent_signals:
        tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"
        msg = (f"<b>{label} {percent:+.2f}% ({tf})</b>\n"
               f"Монета: <b>{symbol}</b>\n"
               f"Цена сейчас: <code>{price}</code>\n"
               f"Пик (High/Low): <code>{peak}</code>\n"
               f"Открытие свечи: <code>{open_p}</code>\n"
               f"───────────────────\n"
               f"🔗 <a href='{tv}'>ОТКРЫТЬ ГРАФИК</a>")
        send_msg(msg)
        sent_signals[key] = time.time()
        logging.info(f"Сигнал отправлен: {symbol} {tf}")

def sniper_loop():
    logging.info("Снайпер v9.1 запущен...")
    while True:
        try:
            # 1. Обновляем список монет (на случай листингов)
            markets = exchange.load_markets()
            symbols = [s for s, m in markets.items() if m['active'] and m['type'] == 'swap' and m['quote'] == 'USDT']
            
            logging.info(f"Начинаю обход {len(symbols)} монет...")
            
            for symbol in symbols:
                check_logic(symbol, '1h')
                check_logic(symbol, '2h')
                
                # Безопасная пауза между монетами (чтобы не забанили)
                time.sleep(0.06) 
            
            # 2. Очистка памяти от старых сигналов (старше 12 часов)
            now = time.time()
            for k in list(sent_signals.keys()):
                if now - sent_signals[k] > 43200:
                    del sent_signals[k]
            
            # 3. Безопасная пауза между кругами
            logging.info("Круг завершен. Сплю 10 секунд...")
            time.sleep(10)
            
        except Exception as e:
            logging.error(f"Ошибка в цикле: {e}")
            time.sleep(30)

# Запуск в отдельном потоке
threading.Thread(target=sniper_loop, daemon=True).start()

if __name__ == "__main__":
    # Порт для Render или других хостингов
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
