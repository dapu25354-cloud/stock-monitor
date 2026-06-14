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

# 優先讀取專案內的 watch_list.json (從 python/ 移入)
WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watch_list.json")
# 如果不存在，嘗試讀取上層目錄 (本機路徑)
if not os.path.exists(WATCHLIST_FILE):
    WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "..", "watch_list.json")

def load_config():
    """本機開發時讀取 config.json；Cloud 環境優先使用環境變數"""
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

def generate_signals(df):
    """
    冷血獵殺核心邏輯
    """
    # 處理 yfinance 可能返回的 MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    close = df['Close'].squeeze()
    high = df['High'].squeeze()
    low = df['Low'].squeeze()

    # 1. 計算 RSI
    df['rsi'] = ta.momentum.rsi(close=close, window=14)
    
    # 2. 計算布林通道
    indicator_bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    df['bb_lband'] = indicator_bb.bollinger_lband()
    
    # 3. 建立訊號欄位
    df['rsi_oversold'] = df['rsi'] < 35  # Cloud 版稍微調高靈敏度 (原為 30)
    df['touch_bb_lower'] = low <= df['bb_lband']
    df['stop_lower_low'] = close >= close.shift(1)
    
    # 買進訊號 (停止破低 AND (RSI超賣 OR 觸碰下軌))
    df['buy_signal'] = (df['stop_lower_low']) & (df['rsi_oversold'] | df['touch_bb_lower'])
    
    return df

def run_full_scan():
    watchlist = load_watchlist()
    if not watchlist:
        print(f"錯誤: 找不到觀察名單 {WATCHLIST_FILE}")
        return

    print(f"--- ⚔️ 雲端啟動【冷血獵殺】全方位掃描 ---")
    print(f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    triggered_stocks = []

    for item in watchlist:
        symbol = item['symbol']
        name = item['name']
        print(f"分析中: {symbol} ({name})...")
        
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="6mo")
            if df.empty or len(df) < 20:
                continue

            df = generate_signals(df)
            last_row = df.iloc[-1]
            
            if last_row['buy_signal']:
                res = {
                    "symbol": symbol,
                    "name": name,
                    "price": float(last_row['Close']),
                    "rsi": float(last_row['rsi']),
                    "bb_l": float(last_row['bb_lband'])
                }
                triggered_stocks.append(res)
                print(f"✅ {symbol} {name} 訊號觸發！")
            
            time.sleep(0.5)
        except Exception as e:
            print(f"❌ {symbol} 出錯: {e}")

    if triggered_stocks:
        summary_msg = "🎯 【冷血獵殺 - 雲端掃描報告】\n"
        summary_msg += f"⏰ 時間: {datetime.now().strftime('%H:%M:%S')}\n"
        for s in triggered_stocks:
            summary_msg += f"------------------\n"
            summary_msg += f"📈 {s['symbol']} ({s['name']})\n"
            summary_msg += f"💰 現價: {s['price']:.2f}\n"
            summary_msg += f"📊 RSI: {s['rsi']:.1f}\n"
            summary_msg += f"📉 布林下軌: {s['bb_l']:.1f}\n"
        
        print(summary_msg)
        send_telegram_msg(summary_msg)
    else:
        print("【⌛ 掃描完成】未發現冷血獵殺訊號。")

if __name__ == "__main__":
    run_full_scan()
