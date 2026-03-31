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
    # Эта страница нужна, чтобы Uprobot дергал бота и не давал Render уснуть
    return f"✅ Бот v5.2 АКТИВЕН. (30m Pump | 4H Signals | MA50 | Top-120 Vol). Время сервера: {datetime.now().strftime('%H:%M:%S')}"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0 # Порог для пампа/дампа на 30м

# Таймаут увеличен до 30 сек, чтобы бот не падал при долгом ответе MEXC
exchange = ccxt.mexc({
    'enableRateLimit': True, 
    'timeout': 30000, 
    'options': {'defaultType': 'swap'}
})

def get_funding_status(val):
    abs_val = abs(val)
    if abs_val < 0.0003: return "🟢"
    if abs_val < 0.001: return "⚠️"
    return "🚨"

def send_msg(text):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logging.error(f"Ошибка отправки в Telegram: {e}")

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
    sent_signals = {} 
    logging.info("Мульти-таймфрейм мониторинг (v5.2 ТОП-ОБЪЕМЫ) запущен.")
    
    while True: # ГЛОБАЛЬНЫЙ ЦИКЛ (Бот никогда не должен из него выходить)
        try:
            try:
                exchange.load_markets()
                # 1. Получаем тикеры ВСЕХ монет разом
                tickers = exchange.fetch_tickers()
            except Exception as e:
                logging.error(f"Ошибка загрузки рынков MEXC: {e}. Пропуск цикла.")
                time.sleep(10)
                continue # Возвращаемся в начало цикла, если биржа не отвечает

            # 2. Фильтруем только активные USDT фьючерсы и собираем их объемы
            active_swaps = []
            for symbol, ticker_data in tickers.items():
                market = exchange.markets.get(symbol)
                if market and market.get('active') and market.get('type') == 'swap' and market.get('quote') == 'USDT':
                    vol = ticker_data.get('quoteVolume', 0)
                    if vol is None: vol = 0
                    active_swaps.append({'symbol': symbol, 'vol': vol})
            
            # 3. Сортируем по объему торгов (от большего к меньшему) и берем Топ-120
            active_swaps.sort(key=lambda x: x['vol'], reverse=True)
            symbols = [x['symbol'] for x in active_swaps][:120] 

            for symbol in symbols:
                try: # Локальный try/except. Если одна монета глючит, другие работают.
                    # 1. ЖИВАЯ ЦЕНА В МОМЕНТЕ
                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker['last'] # LIVE цена
                    funding = float(ticker.get('info', {}).get('fundingRate', 0) or 0)
                    f_pct = funding * 100
                    f_status = get_funding_status(funding)
                    tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"

                    # 2. ПАМП/ДАМП (Таймфрейм 30м - ловим в моменте)
                    ohlcv_30m = exchange.fetch_ohlcv(symbol, '30m', limit=5)
                    if not ohlcv_30m or len(ohlcv_30m) < 2: continue
                    ts_30m = ohlcv_30m[-1][0]
                    prev_close_30m = ohlcv_30m[-2][4]
                    # Расчет на основе живой цены прямо сейчас
                    percent_30m = (price - prev_close_30m) / prev_close_30m * 100

                    # 3. MA50 (Таймфрейм 1ч)
                    ohlcv_1h = exchange.fetch_ohlcv(symbol, '1h', limit=50)
                    if ohlcv_1h and len(ohlcv_1h) == 50:
                        ma50 = sum([c[4] for c in ohlcv_1h]) / 50
                        ma_text = "🟢 Выше MA50" if price > ma50 else "🔴 Ниже MA50"
                    else:
                        ma_text = "⚪ Нет данных"

                    # 4. СИГНАЛЫ РАЗВОРОТА (Таймфрейм 4ч)
                    ohlcv_4h = exchange.fetch_ohlcv(symbol, '4h', limit=30)
                    if not ohlcv_4h or len(ohlcv_4h) < 20: continue
                    ts_4h = ohlcv_4h[-1][0]
                    rsi_4h = calculate_rsi_wilder([c[4] for c in ohlcv_4h])
                    vol_avg_4h = sum(c[5] for c in ohlcv_4h[-6:-1]) / 5

                    # Логика LONG (3/5 на 4H)
                    l_count = 0
                    if funding < -0.0005: l_count += 1
                    if rsi_4h < 45: l_count += 1
                    if calculate_cvd_logic(ohlcv_4h, 'long'): l_count += 1
                    if ohlcv_4h[-1][5] > vol_avg_4h * 1.3: l_count += 1
                    low_24h = min(c[3] for c in ohlcv_4h[-6:])
                    if (price - low_24h) / low_24h < 0.03: l_count += 1

                    l_key = f"{symbol}_{ts_4h}_long"
                    if l_count >= 3 and rsi_4h < 50 and l_key not in sent_signals:
                        msg = (f"🚨 <b>СИЛЬНЫЙ ЛОНГ 4H ({l_count}/5)</b>\n"
                               f"Монета: {symbol}\n"
                               f"RSI (4h): {rsi_4h:.1f}\n"
                               f"Тренд 1h: {ma_text}\n"
                               f"Фандинг: {f_status} <code>{f_pct:.4f}%</code>\n"
                               f"🔗 <a href='{tv}'>График</a>")
                        send_msg(msg)
                        sent_signals[l_key] = time.time()

                    # Логика SHORT (3/5 на 4H)
                    s_count = 0
                    if funding > 0.0005: s_count += 1
                    if rsi_4h > 65: s_count += 1
                    if calculate_cvd_logic(ohlcv_4h, 'short'): s_count += 1
                    if ohlcv_4h[-1][5] > vol_avg_4h * 1.3: s_count += 1
                    high_24h = max(c[2] for c in ohlcv_4h[-6:])
                    if (high_24h - price) / price < 0.03: s_count += 1

                    s_key = f"{symbol}_{ts_4h}_short"
                    if s_count >= 3 and rsi_4h > 50 and s_key not in sent_signals:
                        msg = (f"❄️ <b>СИЛЬНЫЙ ШОРТ 4H ({s_count}/5)</b>\n"
                               f"Монета: {symbol}\n"
                               f"RSI (4h): {rsi_4h:.1f}\n"
                               f"Тренд 1h: {ma_text}\n"
                               f"Фандинг: {f_status} <code>{f_pct:.4f}%</code>\n"
                               f"🔗 <a href='{tv}'>График</a>")
                        send_msg(msg)
                        sent_signals[s_key] = time.time()

                    # Логика ПАМП/ДАМП (В моменте живой цены)
                    p_key = f"{symbol}_{ts_30m}_pd"
                    if abs(percent_30m) >= THRESHOLD and p_key not in sent_signals:
                        dir_text = "ПАМП 🔥" if percent_30m > 0 else "ДАМП ❄️"
                        msg = (f"<b>{dir_text} {percent_30m:+.2f}% (В моменте)</b>\n"
                               f"Монета: {symbol}\n"
                               f"Тренд 1h: {ma_text}\n"
                               f"Фандинг: {f_status} <code>{f_pct:.4f}%</code>\n"
                               f"🔗 <a href='{tv}'>График</a>")
                        send_msg(msg)
                        sent_signals[p_key] = time.time()

                    time.sleep(0.3) # Защита от бана IP со стороны MEXC
                except Exception as e:
                    # Ошибка по одной монете не сломает весь скрипт
                    continue

            # Очистка памяти словаря (удаляем старье старше 24ч)
            now = time.time()
            sent_signals = {k: v for k, v in sent_signals.items() if v > (now - 86400)}
            
            time.sleep(60) # Спим 1 минуту перед новым кругом поиска
            
        except Exception as e:
            # Если сломалось что-то глобальное (например, интернет на сервере пропал)
            logging.error(f"Глобальная ошибка в цикле: {e}")
            time.sleep(30) # Спим 30 сек и пробуем заново

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
