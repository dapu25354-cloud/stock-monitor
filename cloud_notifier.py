import requests
import yfinance as yf
import pandas as pd
import os
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# 從 GitHub Secrets 讀取 (安全性考量)
TELEGRAM_TOKEN = os.getenv("TG_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID")

watchlist = [
    '6561.TWO', '7703.TWO', '4551.TW', '6640.TWO', '3231.TW',
    '5347.TWO', '6669.TW', '2330.TW', '9907.TW', '2891.TW',
    '2889.TW', '3362.TWO', '3008.TW', '2308.TW', '2885.TW',
    '2618.TW', '9904.TW', '1527.TW', '2002.TW', '3211.TWO', '2395.TW'
]

def get_stock_name(symbol):
    names = {
        '6561.TWO': '是方', '7703.TWO': '銳澤', '4551.TW': '智伸科', '6640.TWO': '均華',
        '3231.TW': '緯創', '5347.TWO': '世界', '6669.TW': '緯穎', '2330.TW': '台積電',
        '9907.TW': '統一實', '2891.TW': '中信金', '2889.TW': '國票金', '3362.TWO': '先進光',
        '3008.TW': '大立光', '2308.TW': '台達電', '2885.TW': '元大金', '2618.TW': '長榮航',
        '9904.TW': '寶成', '1527.TW': '鑽全', '2002.TW': '中鋼', '3211.TWO': '順達',
        '2395.TW': '研華'
    }
    return names.get(symbol, symbol)

def send_telegram_message(message):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)

def get_chip_data(symbol):
    code = symbol.split('.')[0]
    is_otc = '.TWO' in symbol.upper()
    # GitHub Actions 執行時通常是台灣時間凌晨或清晨，所以使用最近一個交易日數據
    for d_offset in range(1, 10):
        t_date = (datetime.now() - timedelta(days=d_offset)).strftime('%Y%m%d')
        try:
            if not is_otc:
                url = f"https://www.twse.com.tw/fund/T86?response=json&date={t_date}&selectType=ALL"
                resp = requests.get(url, timeout=5).json()
                if resp.get('data'):
                    for row in resp['data']:
                        if row[0].strip() == code:
                            f = int(row[4].replace(',','')) + int(row[7].replace(',',''))
                            t = int(row[10].replace(',',''))
                            return f // 1000, t // 1000
            else:
                y = int(t_date[:4]) - 1911
                d_fmt = f"{y}/{t_date[4:6]}/{t_date[6:]}"
                url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={d_fmt}"
                resp = requests.get(url, timeout=5).json()
                if resp.get('aaData'):
                    for row in resp['aaData']:
                        if row[0].strip() == code:
                            f = int(row[8].replace(',',''))
                            t = int(row[11].replace(',',''))
                            return f // 1000, t // 1000
        except: continue
    return 0, 0

def analyze(symbol):
    try:
        df = yf.download(symbol, period="60d", progress=False)
        if df.empty: return
        
        price = round(float(df['Close'].iloc[-1]), 2)
        f_val, t_val = get_chip_data(symbol)
        inst_total = f_val + t_val
        total_vol_5d = df['Volume'].tail(5).sum() / 1000
        chip_concent = round((inst_total / (total_vol_5d + 0.001)) * 100, 2)
        
        # MACD
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2
        
        # 訊號判斷
        sig_list = []
        if chip_concent > 8 and inst_total > 0: sig_list.append("💎 主力大買")
        if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0: sig_list.append("MACD金叉")
        
        if sig_list:
            msg = (
                f"🚀 *【GitHub 自動監控通知】*\n"
                f"------------------\n"
                f"💎 標的：{get_stock_name(symbol)} ({symbol})\n"
                f"💰 價格：{price}\n"
                f"📊 訊號：*{' | '.join(sig_list)}*\n"
                f"🔥 籌碼集中度：{chip_concent}%\n"
                f"🏢 外資:{f_val} | 投信:{t_val} (張)\n"
                f"⏰ 時間：{datetime.now().strftime('%H:%M:%S')}"
            )
            send_telegram_message(msg)
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")

if __name__ == "__main__":
    print(f"Starting cloud scan at {datetime.now()}")
    with ThreadPoolExecutor(max_workers=10) as executor:
        executor.map(analyze, watchlist)
    print("Scan completed.")
