from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import requests
import os
import sys
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

# 確保輸出編碼為 UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import threading

yfinance_lock = threading.Lock()

# 配置資訊（從環境變數讀取）
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全域快取
cache_results: List[Dict] = []
last_update_time: str = "尚未更新"

def send_telegram_message(message: str):
    # Telegram notifications are completely disabled per user request to avoid notification floods.
    print(f"[Telegram Disabled] Message not sent: {message}")
    return

def get_stock_name(symbol: str):
    STOCK_NAMES = {
        '6561.TWO': '是方', '7703.TWO': '銳澤', '4551.TW': '智伸科', '6640.TWO': '均華',
        '3231.TW': '緯創', '5347.TWO': '世界', '6669.TW': '緯穎', '2330.TW': '台積電',
        '2891.TW': '中信金', '2889.TW': '國票金',
        '3008.TW': '大立光', '2308.TW': '台達電', '2885.TW': '元大金', '2618.TW': '長榮航',
        '3211.TWO': '順達', '2395.TW': '研華', '3551.TWO': '世禾', '8067.TWO': '汎銓',
        '9907.TW': '統一實', '3362.TWO': '先進光', '9904.TW': '寶成', '1527.TW': '鑽全',
        '2002.TW': '中鋼'
    }
    return STOCK_NAMES.get(symbol, symbol.split('.')[0])

_chip_cache: Dict[str, Dict[str, tuple]] = {}
_chip_cache_lock = threading.Lock()
_chip_session = requests.Session()
_chip_session.headers.update({"User-Agent": "Mozilla/5.0"})

def _to_int(v) -> int:
    return int(str(v).replace(',', '').strip() or 0)

def _fetch_twse_day(t_date: str) -> Dict[str, tuple]:
    key = f"TW{t_date}"
    if key in _chip_cache: return _chip_cache[key]
    with _chip_cache_lock:
        if key in _chip_cache: return _chip_cache[key]
        result: Dict[str, tuple] = {}
        try:
            url = f"https://www.twse.com.tw/fund/T86?response=json&date={t_date}&selectType=ALL"
            resp = _chip_session.get(url, timeout=15).json()
            for row in resp.get('data', []):
                try:
                    code = str(row[0]).strip()
                    f_net = (_to_int(row[4]) + _to_int(row[7])) // 1000
                    t_net = _to_int(row[10]) // 1000
                    result[code] = (f_net, t_net)
                except Exception: continue
        except: pass
        _chip_cache[key] = result
        return result

def _fetch_tpex_day(t_date: str) -> Dict[str, tuple]:
    key = f"OTC{t_date}"
    if key in _chip_cache: return _chip_cache[key]
    with _chip_cache_lock:
        if key in _chip_cache: return _chip_cache[key]
        result: Dict[str, tuple] = {}
        try:
            y = int(t_date[:4]) - 1911
            d_fmt = f"{y}/{t_date[4:6]}/{t_date[6:]}"
            url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={d_fmt}"
            resp = _chip_session.get(url, timeout=15).json()
            rows = (resp.get('tables') or [{}])[0].get('data') or []
            for row in rows:
                try:
                    code = str(row[0]).strip()
                    f_net = _to_int(row[10]) // 1000
                    t_net = _to_int(row[13]) // 1000
                    result[code] = (f_net, t_net)
                except Exception: continue
        except: pass
        _chip_cache[key] = result
        return result

def _warm_chip_cache(days_back: int = 10):
    for d_offset in range(days_back):
        t_date = (datetime.now() - timedelta(days=d_offset)).strftime('%Y%m%d')
        _fetch_twse_day(t_date)
        _fetch_tpex_day(t_date)

_warning_stocks: set = set()
def _fetch_warning_stocks():
    global _warning_stocks
    found = set()
    try:
        url = "https://www.twse.com.tw/announcement/punish?response=json"
        resp = _chip_session.get(url, timeout=10).json()
        for row in resp.get('data', []):
            if len(row) > 2:
                code = str(row[2]).strip()
                if code: found.add(code)
    except: pass
    _warning_stocks = found

def get_chip_data(symbol: str, days: int = 5):
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_day if '.TWO' in symbol.upper() else _fetch_twse_day
    total_f, total_t = 0, 0
    found_days = 0
    for d_offset in range(10):
        if found_days >= days: break
        t_date = (datetime.now() - timedelta(days=d_offset)).strftime('%Y%m%d')
        day_map = fetcher(t_date)
        if code in day_map:
            f, t = day_map[code]
            total_f += f; total_t += t
            found_days += 1
    return total_f, total_t

def get_chip_latest_day(symbol: str):
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_day if '.TWO' in symbol.upper() else _fetch_twse_day
    for d_offset in range(10):
        t_date = (datetime.now() - timedelta(days=d_offset)).strftime('%Y%m%d')
        day_map = fetcher(t_date)
        if code in day_map:
            return day_map[code]
    return (0, 0)

def analyze_stock(symbol: str):
    try:
        with yfinance_lock:
            df = yf.download(symbol, period="60d", interval="1d", progress=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        latest = df.iloc[-1]
        price = float(latest['Close'])
        ma20 = float(df['Close'].rolling(window=20).mean().iloc[-1])
        bias = round(((price - ma20) / (ma20 + 0.001)) * 100, 2)
        
        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2
        
        # KD
        low_9 = df['Low'].rolling(window=9).min()
        high_9 = df['High'].rolling(window=9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9 + 0.001) * 100
        k = rsv.ewm(com=2, adjust=False).mean().iloc[-1]
        
        # TD
        df['diff4'] = df['Close'].diff(4)
        buy_c = 0; sell_c = 0
        for i in range(max(0, len(df) - 13), len(df)):
            if df['diff4'].iloc[i] < 0: buy_c += 1; sell_c = 0
            elif df['diff4'].iloc[i] > 0: sell_c += 1; buy_c = 0

        # RSI
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).ewm(com=13, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(com=13, adjust=False).mean()
        rsi = 100 - (100 / (1 + gain / (loss + 0.001))).iloc[-1]

        f_val, t_val = get_chip_data(symbol)
        inst_total = f_val + t_val
        total_vol_5d = df['Volume'].tail(5).sum() / 1000
        chip_concent = round((inst_total / (total_vol_5d + 0.001)) * 100, 2)

        f_today, t_today = get_chip_latest_day(symbol)
        today_total = f_today + t_today

        sig_list = []
        if chip_concent > 8 and inst_total > 0:
            sig_list.append("💎 主力大買")
            if today_total < 0:
                sig_list.append("⚠️ 主力轉賣")
        elif chip_concent < -8 and inst_total < 0:
            if today_total > 0:
                sig_list.append("💪 法人轉買")
            else:
                sig_list.append("⚠️ 主力出貨")
        
        if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0: sig_list.append("MACD金叉")
        if k < 25: sig_list.append("KD低檔")
        if buy_c >= 8: sig_list.append("TD低點轉折")

        s_type = "normal"
        if any(x in ["💎 主力大買", "💪 法人轉買", "MACD金叉"] for x in sig_list):
            s_type = "success"
        elif any(x in ["⚠️ 主力出貨", "⚠️ 主力轉賣"] for x in sig_list):
            s_type = "warning"

        return {
            "symbol": symbol, "name": get_stock_name(symbol), "price": round(price, 2),
            "ma20": round(ma20, 2), "rsi": round(rsi, 1), "bias": bias,
            "signal": " | ".join(sig_list) if sig_list else "穩定盤整",
            "signal_type": s_type,
            "td_signal": f"買計:{buy_c}" if buy_c > 0 else f"賣計:{sell_c}",
            "inst_signal": f"外資:{f_val} | 投信:{t_val}", "chip_concent": chip_concent,
            "today_signal": f"外資:{'+' if f_today > 0 else ''}{f_today} | 投信:{'+' if t_today > 0 else ''}{t_today}",
            "analysis": f"KD:{round(k,1)} | 乖離:{bias}%",
            "is_warning": symbol.split('.')[0] in _warning_stocks,
            "is_state_owned": symbol == '2330.TW'
        }
    except: return None

def update_all_stocks():
    global cache_results, last_update_time
    watchlist = []
    try:
        watchlist_path = os.path.join(os.path.dirname(__file__), "..", "..", "watch_list.json")
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
            '2395.TW'
        ]
    _warm_chip_cache()
    _fetch_warning_stocks()
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze_stock, watchlist))
    cache_results = [r for r in results if r]
    last_update_time = datetime.now().strftime("%H:%M:%S")

scheduler = BackgroundScheduler()
scheduler.add_job(update_all_stocks, 'cron', day_of_week='mon-fri', hour='9,10,12,14', minute='0,30')
scheduler.start()
threading.Thread(target=update_all_stocks, daemon=True).start()

# --- Todo List API & Persistence ---
class TodoItem(BaseModel):
    id: int
    task: str

TODO_FILE = os.path.join(os.path.dirname(__file__), "todos.json")

def load_todos() -> List[Dict]:
    if os.path.exists(TODO_FILE):
        try:
            with open(TODO_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"讀取 todos.json 失敗: {e}")
            return []
    return []

def save_todos(todos: List[Dict]):
    try:
        with open(TODO_FILE, 'w', encoding='utf-8') as f:
            json.dump(todos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"儲存 todos.json 失敗: {e}")

@app.get("/api/todos")
async def get_todos():
    return load_todos()

@app.post("/api/todos")
async def add_todo(item: TodoItem):
    todos = load_todos()
    todos.append({"id": item.id, "task": item.task})
    save_todos(todos)
    return {"status": "success"}

@app.delete("/api/todos/{todo_id}")
async def delete_todo(todo_id: int):
    todos = load_todos()
    new_todos = [t for t in todos if t.get("id") != todo_id]
    save_todos(new_todos)
    return {"status": "success"}

@app.get("/api/stocks")
async def get_stocks(): return cache_results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
