import os
import sys
import pandas as pd
import yfinance as yf
import ta
import json
import time
from datetime import datetime

# 強制 UTF-8 輸出
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# --- 環境變數與路徑設定 (Cloud 支援) ---
TELEGRAM_TOKEN = os.getenv("TG_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID")

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watch_list.json")
if not os.path.exists(WATCHLIST_FILE):
    WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "..", "watch_list.json")

def load_config():
    global TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        return {"tg_token": TELEGRAM_TOKEN, "tg_chat_id": TELEGRAM_CHAT_ID}
    
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            TELEGRAM_TOKEN = config.get("tg_token") or config.get("token")
            TELEGRAM_CHAT_ID = config.get("tg_chat_id") or config.get("chat_id")
            return config
    return {}

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def send_telegram_msg(message):
    # Telegram notifications are completely disabled per user request to avoid notification floods.
    print(f"[Telegram Disabled] Message not sent: {message.replace(chr(10), ' ')}")
    return

def analyze_panic_bottom(df):
    """
    恐慌接刀核心邏輯
    """
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    close = df['Close'].squeeze()
    high = df['High'].squeeze()
    low = df['Low'].squeeze()
    open_p = df['Open'].squeeze()
    volume = df['Volume'].squeeze()

    # 1. 計算 RSI & 20MA Bias
    df['rsi'] = ta.momentum.rsi(close=close, window=14)
    df['ma20'] = close.rolling(window=20).mean()
    df['bias20'] = (close - df['ma20']) / df['ma20'] * 100
    
    # 2. Volume Spike
    df['v_ma20'] = volume.rolling(window=20).mean()
    df['is_volume_spike'] = volume > (df['v_ma20'] * 1.8)
    
    # 3. K 線特徵 (精準槌子線)
    body = abs(close - open_p)
    lower_shadow = (close.where(close < open_p, open_p)) - low
    df['is_hammer'] = (lower_shadow > (body * 2)) & (close > low)
    
    # 4. 終極訊號判斷
    df['panic_signal'] = (df['rsi'] < 30) & \
                         (df['bias20'] < -10) & \
                         (df['is_volume_spike'] | df['is_hammer']) & \
                         (close >= close.shift(1))
    
    return df

def run_panic_scan():
    watchlist = load_watchlist()
    if not watchlist:
        print(f"錯誤: 找不到觀察名單 {WATCHLIST_FILE}")
        return

    print(f"--- 🌋 雲端啟動【恐慌接刀】極限掃描 ---")
    print("-" * 60)

    results = []

    for item in watchlist:
        symbol = item['symbol']
        name = item['name']
        print(f"掃描中: {symbol} {name}...")
        
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="6mo")
            if df.empty or len(df) < 20: continue

            df = analyze_panic_bottom(df)
            last = df.iloc[-1]
            
            # 如果符合極限恐慌區域
            if last['rsi'] < 35 or last['bias20'] < -8:
                status = "🟡 進入觀察區"
                if last['panic_signal']:
                    status = "🔥 觸發終極接刀訊號！"
                
                results.append({
                    "symbol": symbol,
                    "name": name,
                    "price": float(last['Close']),
                    "rsi": float(last['rsi']),
                    "bias": float(last['bias20']),
                    "volume_spike": "是" if last['is_volume_spike'] else "否",
                    "status": status
                })
            time.sleep(0.4)
        except: continue

    if results:
        msg = f"🌋 【恐慌接刀 - 雲端策略掃描】\n"
        msg += f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        for r in results:
            msg += f"------------------\n"
            msg += f"📈 {r['symbol']} ({r['name']})\n"
            msg += f"💰 現價: {r['price']:.2f}\n"
            msg += f"📊 RSI: {r['rsi']:.1f}\n"
            msg += f"📉 20MA 乖離: {r['bias']:.1f}%\n"
            msg += f"📢 爆量承接: {r['volume_spike']}\n"
            msg += f"🎯 狀態: {r['status']}\n"
        
        print(msg)
        send_telegram_msg(msg)
    else:
        print("【⌛ 掃描結束】未發現極限恐慌標的。")

if __name__ == "__main__":
    run_panic_scan()
