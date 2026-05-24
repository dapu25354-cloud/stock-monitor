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

# 配置資訊（從環境變數讀取，避免將憑證寫入版本控制）
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

# 全域快取，確保網頁秒開
cache_results: List[Dict] = []
last_update_time: str = "尚未更新"

def send_telegram_message(message: str):
    if not TELEGRAM_TOKEN or "your_token" in TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def get_stock_name(symbol: str):
    STOCK_NAMES = {
        '6561.TWO': '是方', '7703.TWO': '銳澤', '4551.TW': '智伸科', '6640.TWO': '均華',
        '3231.TW': '緯創', '5347.TWO': '世界', '6669.TW': '緯穎', '2330.TW': '台積電',
        '9907.TW': '統一實', '2891.TW': '中信金', '2889.TW': '國票金', '3362.TWO': '先進光',
        '3008.TW': '大立光', '2308.TW': '台達電', '2885.TW': '元大金', '2618.TW': '長榮航',
        '9904.TW': '寶成', '1527.TW': '鑽全', '2002.TW': '中鋼', '3211.TWO': '順達',
        '2395.TW': '研華'
    }
    return STOCK_NAMES.get(symbol, symbol.split('.')[0])

_chip_cache: Dict[str, Dict[str, tuple]] = {}
_chip_cache_lock = threading.Lock()
_chip_session = requests.Session()
_chip_session.headers.update({"User-Agent": "Mozilla/5.0"})

def _to_int(v) -> int:
    # TWSE/TPEx mix strings ("1,234") with raw ints in the same response
    return int(str(v).replace(',', '').strip() or 0)

def _fetch_twse_day(t_date: str) -> Dict[str, tuple]:
    key = f"TW{t_date}"
    if key in _chip_cache:
        return _chip_cache[key]
    with _chip_cache_lock:
        if key in _chip_cache:
            return _chip_cache[key]
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
                except Exception:
                    continue
        except Exception as e:
            print(f"[chip] TWSE {t_date} fetch failed: {e}")
        _chip_cache[key] = result
        return result

def _fetch_tpex_day(t_date: str) -> Dict[str, tuple]:
    key = f"OTC{t_date}"
    if key in _chip_cache:
        return _chip_cache[key]
    with _chip_cache_lock:
        if key in _chip_cache:
            return _chip_cache[key]
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
                except Exception:
                    continue
        except Exception as e:
            print(f"[chip] TPEx {t_date} fetch failed: {e}")
        _chip_cache[key] = result
        return result

def _warm_chip_cache(days_back: int = 10):
    with _chip_cache_lock:
        _chip_cache.clear()
    for d_offset in range(days_back):
        t_date = (datetime.now() - timedelta(days=d_offset)).strftime('%Y%m%d')
        _fetch_twse_day(t_date)
        _fetch_tpex_day(t_date)

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
            total_f += f
            total_t += t
            found_days += 1
    return total_f, total_t

def analyze_stock(symbol: str):
    try:
        df = yf.download(symbol, period="60d", interval="1d", progress=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = float(latest['Close'])

        # 指標計算
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
        d = k; # 簡化計算
        
        # TD Signal
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

        # Chip
        f_val, t_val = get_chip_data(symbol)
        inst_total = f_val + t_val
        total_vol_5d = df['Volume'].tail(5).sum() / 1000
        chip_concent = round((inst_total / (total_vol_5d + 0.001)) * 100, 2)

        sig_list = []
        if chip_concent > 8 and inst_total > 0: sig_list.append("💎 主力大買")
        if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0: sig_list.append("MACD金叉")
        if k < 25: sig_list.append("KD低檔")
        if buy_c >= 8: sig_list.append("TD低點轉折")

        return {
            "symbol": symbol, "name": get_stock_name(symbol), "price": round(price, 2),
            "ma20": round(ma20, 2), "rsi": round(rsi, 1), "bias": bias,
            "signal": " | ".join(sig_list) if sig_list else "穩定盤整", 
            "signal_type": "success" if sig_list else "normal",
            "td_signal": f"買計:{buy_c}" if buy_c > 0 else f"賣計:{sell_c}",
            "inst_signal": f"外資:{f_val} | 投信:{t_val}", "chip_concent": chip_concent,
            "analysis": f"KD:{round(k,1)} | 乖離:{bias}%"
        }
    except: return None

def update_all_stocks():
    global cache_results, last_update_time
    print(f"[{datetime.now()}] 啟動並行分析中...")
    watchlist = [
        '6561.TWO', '7703.TWO', '4551.TW', '6640.TWO', '3231.TW',
        '5347.TWO', '6669.TW', '2330.TW', '9907.TW', '2891.TW',
        '2889.TW', '3362.TWO', '3008.TW', '2308.TW', '2885.TW',
        '2618.TW', '9904.TW', '1527.TW', '2002.TW', '3211.TWO', '2395.TW'
    ]
    
    _warm_chip_cache()
    new_results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze_stock, watchlist))
        new_results = [r for r in results if r]
    
    if new_results:
        cache_results = new_results
        last_update_time = datetime.now().strftime("%H:%M:%S")
        print(f"[{datetime.now()}] 分析完成，共 {len(cache_results)} 檔。")
        # 這裡可以加入 check_and_notify 的邏輯

from apscheduler.triggers.cron import CronTrigger

def check_and_notify(data: dict):
    if data.get("signal_type") != "success":
        return
    msg = (
        f"🚀 *【本地監控通知】*\n"
        f"------------------\n"
        f"💎 標的：{data['name']} ({data['symbol']})\n"
        f"💰 價格：{data['price']}\n"
        f"📊 訊號：*{data['signal']}*\n"
        f"🔥 籌碼集中度：{data['chip_concent']}%\n"
        f"🏢 {data['inst_signal']} (張)\n"
        f"📈 {data['analysis']}\n"
        f"⏰ 時間：{datetime.now().strftime('%H:%M:%S')}"
    )
    send_telegram_message(msg)

def scheduled_scan():
    """定時掃描並通知 (支援手動觸發)"""
    update_all_stocks() # 先更新數據
    print(f"[{datetime.now()}] 正在檢查訊號並發送 Telegram 通知...")
    if not cache_results: return
    
    for data in cache_results:
        check_and_notify(data)

# 排程設定：開盤一小時後(10:00)、中午(12:00)、盤後(14:30)
scheduler = BackgroundScheduler()
# 10:00 AM
scheduler.add_job(scheduled_scan, CronTrigger(day_of_week='mon-fri', hour=10, minute=0))
# 12:00 PM
scheduler.add_job(scheduled_scan, CronTrigger(day_of_week='mon-fri', hour=12, minute=0))
# 14:30 PM
scheduler.add_job(scheduled_scan, CronTrigger(day_of_week='mon-fri', hour=14, minute=30))
scheduler.start()

# 伺服器啟動時立刻執行一次數據更新
threading.Thread(target=update_all_stocks, daemon=True).start()

@app.get("/api/scan")
async def manual_scan():
    """手動觸發全標的掃描與通知"""
    print(f"[{datetime.now()}] 手動觸發全標的掃描...")
    update_all_stocks()
    if not cache_results:
        return {"status": "error", "message": "尚未完成初始分析，請稍後"}
    
    # 執行通知判斷
    for data in cache_results:
        check_and_notify(data)
    
    return {"status": "success", "message": f"掃描完成，已檢查 {len(cache_results)} 檔標的"}

@app.get("/api/stocks")
async def get_stocks():
    if not cache_results:
        # 如果還沒快取好，執行一次快速分析（或返回空）
        return []
    return cache_results

TODOS_FILE = "todos.json"

def _load_todos() -> List[Dict]:
    if os.path.exists(TODOS_FILE):
        try:
            with open(TODOS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def _save_todos(todos: List[Dict]):
    with open(TODOS_FILE, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

_todos: List[Dict] = _load_todos()
_todos_lock = threading.Lock()

class Todo(BaseModel):
    id: int
    task: str

@app.get("/api/todos")
async def get_todos():
    return _todos

@app.post("/api/todos")
async def add_todo(todo: Todo):
    with _todos_lock:
        _todos.append(todo.dict())
        _save_todos(_todos)
    return {"status": "ok"}

@app.delete("/api/todos/{todo_id}")
async def delete_todo(todo_id: int):
    global _todos
    with _todos_lock:
        _todos = [t for t in _todos if t["id"] != todo_id]
        _save_todos(_todos)
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
