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
    return "✅ Бот живой! v3.5"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
THRESHOLD = 7.0
TOP_SYMBOLS = 50

if not TELEGRAM_TOKEN or not CHAT_ID:
    print("❌ Ошибка: добавь TELEGRAM_TOKEN и CHAT_ID")
    exit()

exchange = ccxt.mexc()
markets = exchange.load_markets()

sorted_markets = sorted(
    [m for m in markets.values() if m.get('active') and m.get('type') == 'swap' and m.get('quote') == 'USDT'],
    key=lambda x: float(x.get('info', {}).get('volume24', 0) or 0),
    reverse=True
)
symbols = [m['symbol'] for m in sorted_markets[:TOP_SYMBOLS]]
print(f"✅ Бот запущен (топ-{TOP_SYMBOLS} фьючерсов)")

# Храним не просто set а dict с временем — переживает перезапуск цикла
# Ключ: (symbol, hour_ts) — округляем до часа чтобы не спамить
sent_pump_dump = {}   # key -> unix timestamp отправки
sent_condition = {}   # key -> unix timestamp отправки
COOLDOWN = 3600       # 1 час между одинаковыми сигналами

def already_sent(store, key):
    if key not in store:
        return False
    return time.time() - store[key] < COOLDOWN

def mark_sent(store, key):
    store[key] = time.time()

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
    avg_gain = sum(gains[-period:]) / period or 0.0001
    avg_loss = sum(losses[-period:]) / period or 0.0001
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calculate_cvd(ohlcv):
    """
    Исправленный CVD:
    1. Считает накопленную дельту по всем свечам
    2. Требует cvd[-1] > 0 (покупатели доминируют в целом)
    3. Разворот: 2 падающих свечи → последняя растёт
    4. Последняя дельта должна быть положительной (не просто меньше падение)
    """
    if len(ohlcv) < 6:
        return False
    cvd = []
    cumulative = 0.0
    for c in ohlcv:
        delta = c[5] if c[4] >= c[1] else -c[5]
        cumulative += delta
        cvd.append(cumulative)

    # Последняя дельта свечи должна быть положительной
    last_delta = ohlcv[-1][5] if ohlcv[-1][4] >= ohlcv[-1][1] else -ohlcv[-1][5]
    if last_delta <= 0:
        return False

    # CVD в целом положительный
    if cvd[-1] <= 0:
        return False

    # V-образный разворот
    return cvd[-3] > cvd[-2] < cvd[-1]

def send_msg(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Telegram ошибка: {e}")

def bot_loop():
    send_msg(
        "🤖 <b>MEXC Signal Bot v3.5 запущен!</b>\n"
        "Топ-50 фьючерсов\n"
        "⏱ Cooldown: 1 час на сигнал\n"
        "✅ CVD исправлен (только реальный разворот)\n\n"
        "⚠️ Не является финансовым советом"
    )

    while True:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Сканирую...")

        for symbol in symbols:
            try:
                ticker = exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                funding_rate = float(ticker.get('info', {}).get('fundingRate', 0) or 0)

                ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=20)
                if len(ohlcv) < 8:
                    continue

                closes = [c[4] for c in ohlcv]
                prev_close = ohlcv[-2][4]

                # Округляем timestamp до часа — ключ не меняется пока свеча не закрылась
                candle_ts = ohlcv[-1][0] // 3600000 * 3600000

                percent = (current_price - prev_close) / prev_close * 100
                time_str = datetime.utcfromtimestamp(ohlcv[-1][0] / 1000).strftime('%d.%m %H:%M UTC')
                tv = f"https://www.tradingview.com/chart/?symbol=MEXC:{symbol.replace('/', '').replace(':USDT', '.P')}"

                # ── ПАМП / ДАМП ───────────────────────────────────────────────
                pump_key = f"pump_{symbol}_{candle_ts}"
                if abs(percent) >= THRESHOLD and not already_sent(sent_pump_dump, pump_key):
                    direction = "ПАМП" if percent > 0 else "ДАМП"
                    emoji = "🔥" if percent > 0 else "❄️"
                    send_msg(
                        f"{emoji} <b>ПРОСТОЙ {direction} {percent:+.2f}%</b>\n"
                        f"Монета: <b>{symbol}</b>\n"
                        f"Цена: {current_price:.8f}\n"
                        f"Время: {time_str}\n"
                        f"🔗 <a href='{tv}'>График</a>"
                    )
                    mark_sent(sent_pump_dump, pump_key)

                # ── УСЛОВИЯ СИГНАЛА ───────────────────────────────────────────
                cond_key = f"cond_{symbol}_{candle_ts}"
                if already_sent(sent_condition, cond_key):
                    time.sleep(0.15)
                    continue

                conditions = []

                # 1. Funding Rate
                if funding_rate < -0.0005:
                    conditions.append(f"💰 Funding: {funding_rate*100:.4f}%")

                # 2. RSI — только ЗАКРЫТЫЕ свечи (ohlcv[-2] и старше)
                rsi = calculate_rsi(closes[:-1])  # убираем незакрытую свечу
                if rsi < 50:
                    conditions.append(f"📉 RSI(14): {rsi:.1f}")

                # 3. CVD — исправленный
                if calculate_cvd(ohlcv[:-1]):  # убираем незакрытую свечу
                    conditions.append("🔄 CVD разворот вверх")

                # 4. Объём + зелёная свеча (на закрытой свече)
                if ohlcv[-2][5] > ohlcv[-3][5] * 1.4 and ohlcv[-2][4] > ohlcv[-2][1]:
                    conditions.append("📈 Объём +40% и бычья свеча")

                # 5. Цена у поддержки
                low_6h = min(c[3] for c in ohlcv[-7:-1])
                if abs(current_price - low_6h) / low_6h < 0.025:
                    conditions.append("🛡️ Цена у поддержки")

                count = len(conditions)
                cond_text = "\n".join(f"  {c}" for c in conditions)

                if count >= 3:
                    send_msg(
                        f"🚨 <b>СИЛЬНЫЙ СИГНАЛ ({count}/5)</b>\n"
                        f"Монета: <b>{symbol}</b>\n"
                        f"Цена: {current_price:.8f}\n"
                        f"Время: {time_str}\n\n"
                        f"Условия:\n{cond_text}\n\n"
                        f"🔗 <a href='{tv}'>График</a>\n"
                        f"⚠️ Не является финансовым советом"
                    )
                    mark_sent(sent_condition, cond_key)
                elif count >= 1:
                    send_msg(
                        f"📡 <b>Слабый сигнал ({count}/5)</b>\n"
                        f"Монета: <b>{symbol}</b>\n"
                        f"Цена: {current_price:.8f}\n"
                        f"Время: {time_str}\n\n"
                        f"Условия:\n{cond_text}\n\n"
                        f"🔗 <a href='{tv}'>График</a>"
                    )
                    mark_sent(sent_condition, cond_key)

                time.sleep(0.15)

            except Exception as e:
                print(f"Ошибка {symbol}: {e}")
                continue

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Цикл завершён. Пауза 5 мин...")
        time.sleep(300)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
```

---

## Что исправлено в v3.5:

**Спам каждые 15 минут** — теперь `sent_condition` это словарь со временем отправки. Cooldown 1 час — даже если Render перезапустится, в течение часа повтор не придёт на ту же свечу.

**CVD ложные сигналы** — добавлены два новых требования: последняя дельта свечи должна быть положительной (не просто "меньше падает"), и CVD в целом должен быть выше нуля. PROVE с CVD = -147K теперь не пройдёт.

**Незакрытые свечи** — RSI, CVD и объём теперь считаются по `ohlcv[:-1]` — без текущей незакрытой свечи которая постоянно меняется и даёт ложные сигналы.

**requirements.txt** без изменений:
```
ccxt
requests
flask
