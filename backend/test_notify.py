import os
import requests
import json
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

watchlist = [
    '6561.TWO', '7703.TWO', '4551.TW', '6640.TWO', '3231.TW',
    '5347.TWO', '6669.TW', '2330.TW', '9907.TW', '2891.TW',
    '2889.TW', '3362.TWO', '3008.TW', '2308.TW', '2885.TW',
    '2618.TW', '9904.TW', '1527.TW', '2002.TW', '3211.TWO', '2395.TW'
]

def send_msg(msg):
    # Telegram notifications are completely disabled per user request to avoid notification floods.
    print(f"[Telegram Disabled] Message not sent: {msg}")
    return

def get_stock_name(symbol):
    names = {'6561.TWO': '是方', '7703.TWO': '銳澤', '4551.TW': '智伸科', '6640.TWO': '均華', '3231.TW': '緯創', '5347.TWO': '世界', '6669.TW': '緯穎', '2330.TW': '台積電', '9907.TW': '統一實', '2891.TW': '中信金', '2889.TW': '國票金', '3362.TWO': '先進光', '3008.TW': '大立光', '2308.TW': '台達電', '2885.TW': '元大金', '2618.TW': '長榮航', '9904.TW': '寶成', '1527.TW': '鑽全', '2002.TW': '中鋼', '3211.TWO': '順達', '2395.TW': '研華'}
    return names.get(symbol, symbol)

def get_chip(symbol):
    code = symbol.split('.')[0]
    is_otc = '.TWO' in symbol.upper()
    t_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d') # 使用昨日數據測試
    try:
        if not is_otc:
            url = f"https://www.twse.com.tw/fund/T86?response=json&date={t_date}&selectType=ALL"
            resp = requests.get(url, timeout=5).json()
            for row in resp.get('data', []):
                if row[0].strip() == code:
                    return (int(row[4].replace(',','')) + int(row[7].replace(',',''))) // 1000
        else:
            y = int(t_date[:4]) - 1911
            d_fmt = f"{y}/{t_date[4:6]}/{t_date[6:]}"
            url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={d_fmt}"
            resp = requests.get(url, timeout=5).json()
            for row in resp.get('aaData', []):
                if row[0].strip() == code:
                    return int(row[8].replace(',','')) // 1000
    except: pass
    return 0

def analyze(s):
    try:
        df = yf.download(s, period="60d", progress=False)
        if df.empty: return None
        price = df['Close'].iloc[-1]
        chip = get_chip(s)
        # 簡單判斷：若籌碼 > 0 則發送
        if chip > 0:
            msg = f"🚀 【手動掃描通知】 {get_stock_name(s)} ({s})\n💰 價格：{round(float(price), 2)}\n💎 主力買超：{chip} 張\n⏰ 時間：{datetime.now().strftime('%H:%M:%S')}"
            send_msg(msg)
        return s
    except: return None

print("Starting manual scan...")
send_msg("🔔 *手動掃描啟動*：正在檢查 21 檔標的...")
with ThreadPoolExecutor(max_workers=10) as executor:
    list(executor.map(analyze, watchlist))
send_msg("✅ *手動掃描完成*")
print("Done.")
