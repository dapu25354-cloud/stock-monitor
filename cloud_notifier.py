import requests
import yfinance as yf
import pandas as pd
import os
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import Dict

# 從 GitHub Secrets 讀取 (安全性考量)
TELEGRAM_TOKEN = os.getenv("TG_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID")

# 主力大買訊號門檻：5 日累計籌碼集中度 > 8% 且 三大法人總和 > 0
CHIP_THRESHOLD = 8

watchlist = [
    '6561.TWO', '7703.TWO', '4551.TW', '6640.TWO', '3231.TW',
    '5347.TWO', '6669.TW', '2330.TW', '9907.TW', '2891.TW',
    '2889.TW', '3362.TWO', '3008.TW', '2308.TW', '2885.TW',
    '2618.TW', '9904.TW', '1527.TW', '2002.TW', '3211.TWO', '2395.TW'
]

STOCK_NAMES = {
    '6561.TWO': '是方', '7703.TWO': '銳澤', '4551.TW': '智伸科', '6640.TWO': '均華',
    '3231.TW': '緯創', '5347.TWO': '世界', '6669.TW': '緯穎', '2330.TW': '台積電',
    '9907.TW': '統一實', '2891.TW': '中信金', '2889.TW': '國票金', '3362.TWO': '先進光',
    '3008.TW': '大立光', '2308.TW': '台達電', '2885.TW': '元大金', '2618.TW': '長榮航',
    '9904.TW': '寶成', '1527.TW': '鑽全', '2002.TW': '中鋼', '3211.TWO': '順達',
    '2395.TW': '研華'
}

def get_stock_name(symbol):
    return STOCK_NAMES.get(symbol, symbol)

def send_telegram_message(message):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram send failed: {e}")

def _to_int(v):
    return int(str(v).replace(',', '').strip() or 0)

# 每日 chip 回應快取（在 prefetch 階段填滿，per-stock analyse 直接讀）
_chip_cache: Dict[str, Dict[str, tuple]] = {}

def _fetch_twse_day(t_date: str) -> Dict[str, tuple]:
    key = f"TW{t_date}"
    if key in _chip_cache: return _chip_cache[key]
    result: Dict[str, tuple] = {}
    try:
        url = f"https://www.twse.com.tw/fund/T86?response=json&date={t_date}&selectType=ALL"
        resp = requests.get(url, timeout=15).json()
        for row in resp.get('data', []):
            try:
                code = str(row[0]).strip()
                f_net = (_to_int(row[4]) + _to_int(row[7])) // 1000
                t_net = _to_int(row[10]) // 1000
                result[code] = (f_net, t_net)
            except Exception:
                continue
    except Exception as e:
        print(f"[chip] TWSE {t_date} fetch failed: {e}")
    _chip_cache[key] = result
    return result

def _fetch_tpex_day(t_date: str) -> Dict[str, tuple]:
    key = f"OTC{t_date}"
    if key in _chip_cache: return _chip_cache[key]
    result: Dict[str, tuple] = {}
    try:
        y = int(t_date[:4]) - 1911
        d_fmt = f"{y}/{t_date[4:6]}/{t_date[6:]}"
        url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={d_fmt}"
        resp = requests.get(url, timeout=15).json()
        rows = (resp.get('tables') or [{}])[0].get('data') or []
        for row in rows:
            try:
                code = str(row[0]).strip()
                f_net = _to_int(row[10]) // 1000
                t_net = _to_int(row[13]) // 1000
                result[code] = (f_net, t_net)
            except Exception:
                continue
    except Exception as e:
        print(f"[chip] TPEx {t_date} fetch failed: {e}")
    _chip_cache[key] = result
    return result

def warm_chip_cache(days_back=10):
    # GitHub Actions 跑時通常是清晨，今日資料還沒出，所以從 d_offset=1 開始
    for d_offset in range(1, days_back + 1):
        t_date = (datetime.now() - timedelta(days=d_offset)).strftime('%Y%m%d')
        _fetch_twse_day(t_date)
        _fetch_tpex_day(t_date)

def get_chip_data(symbol, days=5):
    """5 日累計三大法人買賣超（張）。與 backend/main.py 一致。"""
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_day if '.TWO' in symbol.upper() else _fetch_twse_day
    total_f, total_t = 0, 0
    found = 0
    for d_offset in range(1, 11):
        if found >= days: break
        t_date = (datetime.now() - timedelta(days=d_offset)).strftime('%Y%m%d')
        day = fetcher(t_date)
        if code in day:
            f, t = day[code]
            total_f += f
            total_t += t
            found += 1
    return total_f, total_t

def get_chip_latest_day(symbol):
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_day if '.TWO' in symbol.upper() else _fetch_twse_day
    for d_offset in range(1, 11):
        t_date = (datetime.now() - timedelta(days=d_offset)).strftime('%Y%m%d')
        day = fetcher(t_date)
        if code in day:
            return day[code]
    return (0, 0)

def analyze(symbol):
    """每檔分析一次，觸發訊號就立刻發 Telegram，並回傳 dict 給最後的 summary 用。"""
    try:
        df = yf.download(symbol, period="60d", progress=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        price = round(float(df['Close'].iloc[-1]), 2)
        f_val, t_val = get_chip_data(symbol)
        inst_total = f_val + t_val
        f_today, t_today = get_chip_latest_day(symbol)
        today_total = f_today + t_today
        total_vol_5d = float(df['Volume'].tail(5).sum()) / 1000
        chip_concent = round((inst_total / (total_vol_5d + 0.001)) * 100, 2)

        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2
        macd_cross = bool(float(hist.iloc[-1]) > 0 and float(hist.iloc[-2]) <= 0)

        sig_list = []
        if chip_concent > CHIP_THRESHOLD and inst_total > 0:
            sig_list.append("💎 主力大買")
            if today_total < 0:
                sig_list.append("⚠️ 主力轉賣")
        if macd_cross:
            sig_list.append("MACD金叉")

        if sig_list:
            msg = (
                f"🚀 *【GitHub 自動監控通知】*\n"
                f"------------------\n"
                f"💎 標的：{get_stock_name(symbol)} ({symbol})\n"
                f"💰 價格：{price}\n"
                f"📊 訊號：*{' | '.join(sig_list)}*\n"
                f"🔥 籌碼集中度(5日)：{chip_concent}%\n"
                f"🏢 5日 外資:{f_val} | 投信:{t_val}\n"
                f"📅 最近一日 外資:{f_today} | 投信:{t_today}\n"
                f"⏰ 時間：{datetime.now().strftime('%H:%M:%S')}"
            )
            send_telegram_message(msg)

        return {
            "symbol": symbol,
            "name": get_stock_name(symbol),
            "price": price,
            "chip_concent": chip_concent,
            "f_val": f_val,
            "t_val": t_val,
            "signals": sig_list,
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

def send_summary(results):
    """每次掃描結尾發一則摘要，讓使用者確認排程確實跑過。"""
    valid = [r for r in results if r]
    triggered = [r for r in valid if r['signals']]
    by_chip = sorted(valid, key=lambda r: abs(r['chip_concent']), reverse=True)[:5]

    top_lines = []
    for r in by_chip:
        sign = '+' if r['chip_concent'] >= 0 else ''
        tag = f"  *{', '.join(r['signals'])}*" if r['signals'] else ""
        top_lines.append(f"  {r['symbol']} {r['name']}: {sign}{r['chip_concent']}%{tag}")

    msg = (
        f"📡 *掃描完成* {datetime.now().strftime('%m/%d %H:%M')}\n"
        f"------------------\n"
        f"✅ 已掃描 {len(valid)}/{len(watchlist)} 檔\n"
        f"🚨 觸發訊號：{len(triggered)} 檔\n\n"
        f"📊 籌碼集中度 TOP 5 (5日)：\n"
        + "\n".join(top_lines)
    )
    send_telegram_message(msg)

if __name__ == "__main__":
    print(f"Starting cloud scan at {datetime.now()}")
    warm_chip_cache()
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze, watchlist))
    send_summary(results)
    print("Scan completed.")
