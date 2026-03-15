import ccxt
import requests
import time
import os
from datetime import datetime

# ================= НАСТРОЙКИ ИЗ Render =================
TELEGRAM_TOKEN = os.getenv("8778736181:AAELWDkj4znoYexdTb0UqlxQfICrDY2c2q8")
CHAT_ID = os.getenv("829545680")
THRESHOLD = float(os.getenv("THRESHOLD", "7.0"))  # 7% и более

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: не указаны TELEGRAM_TOKEN или CHAT_ID в Environment Variables")
    exit()

# =====================================================

exchange = ccxt.mexc()

# Загружаем ВСЕ USDT-перпетюалы MEXC (более 400)
markets = exchange.load_markets()
symbols = [m['symbol'] for m in markets.values() 
           if m.get('active') 
           and m.get('type') == 'swap' 
           and m.get('quote') == 'USDT']

print(f"✅ Запущен мониторинг {len(symbols)} фьючерсов MEXC (7%+)")

last_candle_ts = {}

while True:
    for symbol in symbols:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=3)
            if len(ohlcv) < 3:
                continue

            closed_ts = ohlcv[-2][0]
            prev_close = ohlcv[-3][4]
            close = ohlcv[-2][4]
            percent = (close - prev_close) / prev_close * 100

            if symbol not in last_candle_ts or last_candle_ts[symbol] != closed_ts:
                if percent >= THRESHOLD:
                    base = symbol.split('/')[0]
                    link = f"https://www.tradingview.com/chart/?symbol=MEXC:{base}USDT.P"
                    
                    text = f"""🚨 ПАМП +{percent:.2f}% и более на часовой свече (MEXC)!

Монета: {symbol}
Цена закрытия: {close}
Время: {datetime.utcfromtimestamp(closed_ts/1000).strftime('%d.%m %H:%M UTC')}

🔗 График: {link}"""

                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
                    )
                    print(f"🚀 Алерт: {symbol} +{percent:.2f}%")

                last_candle_ts[symbol] = closed_ts

        except:
            pass

    time.sleep(300)
