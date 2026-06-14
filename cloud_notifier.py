import requests
import yfinance as yf
import pandas as pd
import os
import sys
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import Dict

# Windows 終端機（cp950）印 emoji 會報錯；雲端 ubuntu 為 utf-8 不受影響
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

TW_TZ = timezone(timedelta(hours=8))

def now_tw():
    return datetime.now(TW_TZ)

# 從 GitHub Secrets 讀取 (安全性考量) 或從本機 config.json 讀取
TELEGRAM_TOKEN = os.getenv("TG_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID")

if not TELEGRAM_TOKEN:
    # 嘗試讀取本機 config.json
    try:
        import json
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                TELEGRAM_TOKEN = config.get("tg_token") or config.get("token")
                TELEGRAM_CHAT_ID = config.get("tg_chat_id") or config.get("chat_id")
    except Exception:
        pass

# 主力大買訊號門檻：5 日累計籌碼集中度 > 8% 且 三大法人總和 > 0
CHIP_THRESHOLD = 8

watchlist = []
try:
    watchlist_path = os.path.join(os.path.dirname(__file__), "..", "watch_list.json")
    if os.path.exists(watchlist_path):
        with open(watchlist_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            watchlist = [item["symbol"] for item in data]
except Exception as e:
    print(f"載入 watch_list.json 失敗: {e}")

if not watchlist:
    watchlist = [
        '6561.TWO', '7703.TWO', '4551.TW', '6640.TWO', '3231.TW',
        '5347.TWO', '6669.TW', '2330.TW', '9907.TW', '2891.TW',
        '2889.TW', '3362.TWO', '3008.TW', '2308.TW', '2885.TW',
        '2618.TW', '9904.TW', '1527.TW', '2002.TW', '3211.TWO',
        '2395.TW', '3551.TWO', '6830.TWO'
    ]

STOCK_NAMES = {
    '6561.TWO': '是方', '7703.TWO': '銳澤', '4551.TW': '智伸科', '6640.TWO': '均華',
    '3231.TW': '緯創', '5347.TWO': '世界', '6669.TW': '緯穎', '2330.TW': '台積電',
    '2891.TW': '中信金', '2889.TW': '國票金',
    '3008.TW': '大立光', '2308.TW': '台達電', '2885.TW': '元大金', '2618.TW': '長榮航',
    '3211.TWO': '順達', '2395.TW': '研華', '3551.TWO': '世禾', '6830.TWO': '汎銓',
    '9907.TW': '統一實', '3362.TWO': '先進光', '9904.TW': '寶成', '1527.TW': '鑽全',
    '2002.TW': '中鋼'
}

def get_stock_name(symbol):
    return STOCK_NAMES.get(symbol, symbol)

def send_telegram_message(message):
    # Telegram notifications are completely disabled per user request to avoid notification floods.
    print(f"[Telegram Disabled] Message not sent: {message.replace(chr(10), ' ')}")
    return

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
        t_date = (now_tw() - timedelta(days=d_offset)).strftime('%Y%m%d')
        _fetch_twse_day(t_date)
        _fetch_tpex_day(t_date)

# 警示股（注意/處置股）— 法人交易被機械限制，籌碼集中度會被低估
_warning_stocks: set = set()
EXTRA_WARNING_STOCKS: set = set()  # 手動補充用

# 國營/官股護盤股 — 官股買盤不在外資/投信籌碼裡，會低估真實買盤
STATE_OWNED_STOCKS: set = {
    '2330.TW', # 示例
}

def is_state_owned(symbol):
    return symbol in STATE_OWNED_STOCKS

def fetch_warning_stocks():
    global _warning_stocks
    found = set()
    try:
        url = "https://www.twse.com.tw/announcement/punish?response=json"
        resp = requests.get(url, timeout=10).json()
        for row in resp.get('data', []):
            if len(row) > 2:
                code = str(row[2]).strip()
                if code: found.add(code)
    except Exception as e:
        print(f"[warning] TWSE 處置股 fetch failed: {e}")
    _warning_stocks = found

def is_warning_stock(symbol):
    code = symbol.split('.')[0]
    return code in _warning_stocks or symbol in EXTRA_WARNING_STOCKS

def get_chip_data(symbol, days=5):
    """5 日累計三大法人買賣超（張）。與 backend/main.py 一致。"""
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_day if '.TWO' in symbol.upper() else _fetch_twse_day
    total_f, total_t = 0, 0
    found = 0
    for d_offset in range(1, 11):
        if found >= days: break
        t_date = (now_tw() - timedelta(days=d_offset)).strftime('%Y%m%d')
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
        t_date = (now_tw() - timedelta(days=d_offset)).strftime('%Y%m%d')
        day = fetcher(t_date)
        if code in day:
            return day[code]
    return (0, 0)

def analyze(symbol):
    """每檔 analysis 一次，觸發訊號就立刻發 Telegram，並回傳 dict 給最後的 summary 用。"""
    print(f"正在分析 {symbol}...", end="\r")
    try:
        df = yf.download(symbol, period="60d", progress=False)
        if df.empty: return None
        
        # 處理 yfinance 可能返回的 MultiIndex (Ticker, Metric)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 確保 Close 是 Series 而不是單列 DataFrame，避免 iloc[-1] 返回 Series 而不是 scalar
        close_series = df['Close'].squeeze()
        if isinstance(close_series, pd.DataFrame):
            close_series = close_series.iloc[:, 0]

        price = round(float(close_series.iloc[-1]), 2)
        f_val, t_val = get_chip_data(symbol)
        inst_total = f_val + t_val
        f_today, t_today = get_chip_latest_day(symbol)
        today_total = f_today + t_today
        
        volume_series = df['Volume'].squeeze()
        if isinstance(volume_series, pd.DataFrame):
            volume_series = volume_series.iloc[:, 0]
            
        total_vol_5d = float(volume_series.tail(5).sum()) / 1000
        chip_concent = round((inst_total / (total_vol_5d + 0.001)) * 100, 2)

        # MACD
        exp1 = close_series.ewm(span=12, adjust=False).mean()
        exp2 = close_series.ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2
        macd_cross = bool(float(hist.iloc[-1]) > 0 and float(hist.iloc[-2]) <= 0)

        sig_list = []
        if chip_concent > CHIP_THRESHOLD and inst_total > 0:
            sig_list.append("💎 主力大買")
            if today_total < 0:
                sig_list.append("⚠️ 主力轉賣")
        elif chip_concent < -CHIP_THRESHOLD and inst_total < 0 and today_total > 0:
            sig_list.append("💪 法人轉買")
        if today_total >= 5000:
            sig_list.append("📈 法人單日大買")
        elif today_total <= -5000:
            sig_list.append("📉 法人單日大賣")
        if macd_cross:
            sig_list.append("MACD金叉")

        warning = is_warning_stock(symbol)
        state = is_state_owned(symbol)
        warning_tag = "⚠️ 警示股（籌碼信號可能失真）\n" if warning else ""
        state_tag = "🏛️ 官股護盤股（外資/投信籌碼會低估真實買盤）\n" if state else ""

        if sig_list:
            msg = (
                f"🚀 *【GitHub 自動監控通知】*\n"
                f"------------------\n"
                f"{warning_tag}"
                f"{state_tag}"
                f"💎 標的：{get_stock_name(symbol)} ({symbol})\n"
                f"💰 價格：{price}\n"
                f"📊 訊號：*{' | '.join(sig_list)}*\n"
                f"🔥 籌碼集中度(5日)：{chip_concent}%\n"
                f"🏢 5日 外資:{f_val} | 投信:{t_val}\n"
                f"📅 最近一日 外資:{f_today} | 投信:{t_today}\n"
                f"⏰ 時間：{now_tw().strftime('%H:%M:%S')} (TW)"
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
            "is_warning": warning,
            "is_state_owned": state,
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
        f"📡 *掃描完成* {now_tw().strftime('%m/%d %H:%M')} (TW)\n"
        f"------------------\n"
        f"✅ 已掃描 {len(valid)}/{len(watchlist)} 檔\n"
        f"🚨 觸發訊號：{len(triggered)} 檔\n\n"
        f"📊 籌碼集中度 TOP 5 (5日)：\n"
        + "\n".join(top_lines)
    )
    send_telegram_message(msg)

# ============================================================
#  晚間收盤重點報告（過熱 / 弱勢 / 核心 + 支撐壓力 + 乖離）
# ============================================================
CORE_STOCKS = ['2330.TW', '6669.TW', '2308.TW']  # 三大核心


def _calc_rsi(close, window=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    ag = gain.ewm(alpha=1/window, min_periods=window, adjust=False).mean()
    al = loss.ewm(alpha=1/window, min_periods=window, adjust=False).mean()
    return 100 - (100 / (1 + ag / al))


def _ma(close, n):
    if len(close) < n:
        return None
    return float(close.rolling(n).mean().iloc[-1])


def _nearest_levels(price, candidates):
    merged = {}
    for label, val in candidates:
        if val is None:
            continue
        merged.setdefault(round(val, 1), []).append(label)
    above = sorted(k for k in merged if k > price)
    below = sorted((k for k in merged if k < price), reverse=True)
    res = [(v, '/'.join(merged[v])) for v in above[:2]]
    sup = [(v, '/'.join(merged[v])) for v in below[:2]]
    return res, sup


def analyze_levels(symbol):
    try:
        df = yf.Ticker(symbol).history(period="1y")
        if df.empty or len(df) < 40:
            return None
        close, high, low = df['Close'], df['High'], df['Low']
        price = round(float(close.iloc[-1]), 2)
        rsi = round(float(_calc_rsi(close).iloc[-1]), 1)
        ma5, ma20, ma60, ma120 = _ma(close, 5), _ma(close, 20), _ma(close, 60), _ma(close, 120)
        hi_1m, lo_1m = float(high.iloc[-20:].max()), float(low.iloc[-20:].min())
        hi_3m, lo_3m = float(high.iloc[-60:].max()), float(low.iloc[-60:].min())
        hi_52w = float(high.max())
        cands = [
            ('5日', ma5), ('月', ma20), ('季', ma60), ('半年', ma120),
            ('近月高', hi_1m), ('近月低', lo_1m), ('近季高', hi_3m), ('近季低', lo_3m),
            ('52週高', hi_52w),
        ]
        res, sup = _nearest_levels(price, cands)
        bias60 = round((price - ma60) / ma60 * 100, 1) if ma60 else None
        return {
            'symbol': symbol, 'name': get_stock_name(symbol), 'price': price,
            'rsi': rsi, 'bias60': bias60, 'ma60': ma60, 'res': res, 'sup': sup,
        }
    except Exception as e:
        print(f"Error analyzing levels {symbol}: {e}")
        return None


def _bias_txt(r):
    return f"{r['bias60']:+}%" if r['bias60'] is not None else "N/A"


def _fmt_levels(lst):
    return "  ".join(f"{v:.1f}({l})" for v, l in lst) if lst else "—"


def send_evening_report():
    print(f"Evening report start {now_tw()}")
    data = [r for r in (analyze_levels(s) for s in watchlist) if r]

    def is_hot(r):
        return r['rsi'] > 70 or (r['bias60'] is not None and r['bias60'] > 30)

    def is_weak(r):
        return r['rsi'] < 40 or (r['ma60'] is not None and r['price'] < r['ma60'])

    hot = sorted([r for r in data if is_hot(r)], key=lambda r: (r['bias60'] or 0), reverse=True)
    weak = sorted([r for r in data if is_weak(r)], key=lambda r: r['rsi'])
    core = sorted([r for r in data if r['symbol'] in CORE_STOCKS],
                  key=lambda r: CORE_STOCKS.index(r['symbol']))

    lines = [
        f"🌙 *台股收盤重點* {now_tw().strftime('%m/%d')} (TW)",
        "------------------",
        f"✅ 掃描 {len(data)}/{len(watchlist)} 檔",
        "",
        "🔴 *過熱（追高小心）*",
    ]
    lines += [f"・{r['name']} {r['price']}｜RSI {r['rsi']}｜季線乖離 {_bias_txt(r)}" for r in hot] or ["・無"]

    lines += ["", "🟢 *弱勢 / 已修正*"]
    lines += [f"・{r['name']} {r['price']}｜RSI {r['rsi']}｜季線乖離 {_bias_txt(r)}" for r in weak] or ["・無"]

    lines += ["", "🟡 *三大核心*"]
    for r in core:
        lines.append(f"・{r['name']} {r['price']}｜RSI {r['rsi']}｜乖離 {_bias_txt(r)}")
        lines.append(f"   壓力 {_fmt_levels(r['res'])}")
        lines.append(f"   支撐 {_fmt_levels(r['sup'])}")

    msg = "\n".join(lines)
    print(msg)
    send_telegram_message(msg)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else os.getenv("RUN_MODE", "intraday")
    if mode == "evening":
        send_evening_report()
    else:
        print(f"Starting cloud scan at {datetime.now()}")
        warm_chip_cache()
        fetch_warning_stocks()
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(analyze, watchlist))
        send_summary(results)
        print("Scan completed.")
