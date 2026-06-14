# -*- coding: utf-8 -*-
import os
import json
import sys
import time
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# 確保輸出支援 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

TW_TZ = timezone(timedelta(hours=8))
def now_tw():
    return datetime.now(TW_TZ)

# 導入 yfinance & pandas & ta
try:
    import yfinance as yf
    import pandas as pd
    import numpy as np
    import ta
except ImportError:
    print("請確認已安裝 yfinance, pandas, ta 庫")
    sys.exit(1)

# ==================== 觀察股清單與資料 ====================
STOCK_NAMES = {
    '6561.TWO': '是方', '7703.TWO': '銳澤', '4551.TW': '智伸科', '6640.TWO': '均華',
    '3231.TW': '緯創', '5347.TWO': '世界', '6669.TW': '緯穎', '2330.TW': '台積電',
    '2891.TW': '中信金', '2889.TW': '國票金', '3008.TW': '大立光', '2308.TW': '台達電',
    '2885.TW': '元大金', '2618.TW': '長榮航', '3211.TWO': '順達', '2395.TW': '研華',
    '9907.TW': '統一實', '3362.TWO': '先進光', '9904.TW': '寶成', '1527.TW': '鑽全',
    '2002.TW': '中鋼'
}

# 國營/官股護盤股
STATE_OWNED_STOCKS = {'2330.TW'}

# 三大法人籌碼取得邏輯 (快取)
_chip_cache = {}

def _to_int(v):
    return int(str(v).replace(',', '').strip() or 0)

def _fetch_twse_day(t_date):
    key = f"TW{t_date}"
    if key in _chip_cache: return _chip_cache[key]
    result = {}
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

def _fetch_tpex_day(t_date):
    key = f"OTC{t_date}"
    if key in _chip_cache: return _chip_cache[key]
    result = {}
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
    for d_offset in range(1, days_back + 1):
        t_date = (now_tw() - timedelta(days=d_offset)).strftime('%Y%m%d')
        _fetch_twse_day(t_date)
        _fetch_tpex_day(t_date)

def get_chip_data(symbol, days=5):
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_day if '.TWO' in symbol.upper() else _fetch_twse_day
    total_f, total_t = 0, 0
    found = 0
    for d_offset in range(1, 15):
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
    for d_offset in range(1, 15):
        t_date = (now_tw() - timedelta(days=d_offset)).strftime('%Y%m%d')
        day = fetcher(t_date)
        if code in day:
            return day[code]
    return (0, 0)

# 處置股/注意股取得
_warning_stocks = set()
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
        print(f"[warning] TWSE fetch failed: {e}")
    _warning_stocks = found

def is_warning_stock(symbol):
    code = symbol.split('.')[0]
    return code in _warning_stocks

def analyze_stock(symbol):
    print(f"正在分析 {symbol}...")
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="6mo")
        if df.empty or len(df) < 30:
            return None
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        close_series = df['Close'].squeeze()
        high_series = df['High'].squeeze()
        low_series = df['Low'].squeeze()
        volume_series = df['Volume'].squeeze()
        
        price = round(float(close_series.iloc[-1]), 2)
        price_prev = round(float(close_series.iloc[-2]), 2)
        change = round(price - price_prev, 2)
        change_pct = round((change / price_prev) * 100, 2)
        
        # 1. 計算 RSI
        rsi_series = ta.momentum.rsi(close=close_series, window=14)
        rsi = round(float(rsi_series.iloc[-1]), 1)
        
        # 2. 計算 20MA
        ma20_series = close_series.rolling(window=20).mean()
        ma20 = round(float(ma20_series.iloc[-1]), 2)
        bias20 = round(((price - ma20) / ma20) * 100, 2)
        
        # 3. 計算布林下軌
        indicator_bb = ta.volatility.BollingerBands(close=close_series, window=20, window_dev=2)
        bb_lband = round(float(indicator_bb.bollinger_lband().iloc[-1]), 2)
        
        # 4. 籌碼資料
        f_val, t_val = get_chip_data(symbol)
        inst_total = f_val + t_val
        f_today, t_today = get_chip_latest_day(symbol)
        today_total = f_today + t_today
        
        total_vol_5d = float(volume_series.tail(5).sum()) / 1000
        chip_concent = round((inst_total / (total_vol_5d + 0.001)) * 100, 2)
        
        # 5. MACD 金叉
        exp1 = close_series.ewm(span=12, adjust=False).mean()
        exp2 = close_series.ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2
        macd_cross = bool(float(hist.iloc[-1]) > 0 and float(hist.iloc[-2]) <= 0)
        
        # 判斷訊號
        stop_lower_low = price >= price_prev
        touch_bb_lower = float(low_series.iloc[-1]) <= bb_lband
        
        is_cold_blooded = stop_lower_low and (rsi < 35 or touch_bb_lower)
        is_panic_bottom = rsi < 20 and bias20 <= -15.0 and stop_lower_low
        
        # 趨勢與建議
        signals = []
        if is_panic_bottom:
            signals.append("🌋 恐慌接刀")
        elif is_cold_blooded:
            signals.append("⚔️ 冷血獵殺")
        if macd_cross:
            signals.append("🧬 MACD金叉")
        if chip_concent > 8.0 and inst_total > 0:
            signals.append("💎 主力大買")
            
        # 趨勢分類
        if price >= ma20:
            if rsi > 70:
                trend_status = "🟡 高檔震盪"
                trend_class = "trend-warn"
                advice = "股價處於高檔過熱區，不建議追高，可分批入袋為安。"
            else:
                trend_status = "🟢 偏多趨勢"
                trend_class = "trend-bull"
                advice = "股價守穩 20MA 月線之上，趨勢偏多，持股續抱或逢回加碼。"
        else:
            trend_status = "🔴 偏空弱勢"
            trend_class = "trend-bear"
            advice = "股價已跌破 20MA 月線，多頭轉弱，建議適度減碼防禦。"
            
        if is_cold_blooded or is_panic_bottom:
            advice = "💡 偵測到極限超跌/反彈訊號！技術面有落底跡象，可考慮小量分批布局。"
            
        return {
            "symbol": symbol,
            "name": STOCK_NAMES.get(symbol, symbol),
            "price": price,
            "change": change,
            "change_pct": change_pct,
            "rsi": rsi,
            "ma20": ma20,
            "bias20": bias20,
            "bb_l": bb_lband,
            "chip_concent": chip_concent,
            "f_val": f_val,
            "t_val": t_val,
            "f_today": f_today,
            "t_today": t_today,
            "signals": signals,
            "trend_status": trend_status,
            "trend_class": trend_class,
            "advice": advice,
            "is_warning": is_warning_stock(symbol),
            "is_state_owned": symbol in STATE_OWNED_STOCKS
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

def build_dashboard():
    # 載入名單
    watchlist_path = os.path.join(os.path.dirname(__file__), "watch_list.json")
    if os.path.exists(watchlist_path):
        with open(watchlist_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            watchlist = [item["symbol"] for item in data]
    else:
        watchlist = list(STOCK_NAMES.keys())
        
    print("開始快取與下載數據...")
    warm_chip_cache()
    fetch_warning_stocks()
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(analyze_stock, watchlist))
        
    valid_results = [r for r in results if r]
    
    # 產生 HTML 內容
    now_str = now_tw().strftime('%Y-%m-%d %H:%M:%S')
    
    # 建立卡片 HTML
    cards_html = ""
    for r in valid_results:
        # 判斷漲跌顏色
        price_change_class = "up-color" if r['change'] > 0 else ("down-color" if r['change'] < 0 else "neutral-color")
        change_symbol = "+" if r['change'] > 0 else ""
        
        # 標記
        badges = ""
        if r['is_warning']:
            badges += '<span class="badge badge-warn">⚠️ 警示股</span>'
        if r['is_state_owned']:
            badges += '<span class="badge badge-state">🏛️ 官股</span>'
        for s in r['signals']:
            badges += f'<span class="badge badge-signal">{s}</span>'
            
        # RSI 顏色
        rsi_class = "rsi-low" if r['rsi'] < 35 else ("rsi-high" if r['rsi'] > 70 else "")
        
        # 籌碼集中度顏色
        chip_class = "chip-high" if r['chip_concent'] > 8.0 else ("chip-low" if r['chip_concent'] < -8.0 else "")
        
        cards_html += f"""
        <div class="card" data-symbol="{r['symbol']}" data-name="{r['name']}" data-signals="{','.join(r['signals'])}" data-trend="{r['trend_class']}">
            <div class="card-header">
                <div>
                    <span class="stock-name">{r['name']}</span>
                    <span class="stock-symbol">{r['symbol']}</span>
                </div>
                <div class="trend-badge {r['trend_class']}">{r['trend_status']}</div>
            </div>
            
            <div class="card-body">
                <div class="price-row">
                    <span class="price-val">{r['price']:.2f}</span>
                    <span class="price-change {price_change_class}">{change_symbol}{r['change']:.2f} ({change_symbol}{r['change_pct']:.2f}%)</span>
                </div>
                
                <div class="badges-row">
                    {badges}
                </div>
                
                <div class="metrics-grid">
                    <div class="metric-item">
                        <span class="metric-label">RSI(14)</span>
                        <span class="metric-val {rsi_class}">{r['rsi']}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">月線 (20MA)</span>
                        <span class="metric-val">{r['ma20']:.2f}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">月線乖離</span>
                        <span class="metric-val {price_change_class}">{change_symbol}{r['bias20']:.1f}%</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">布林下軌</span>
                        <span class="metric-val">{r['bb_l']:.2f}</span>
                    </div>
                </div>
                
                <div class="chip-section">
                    <div class="chip-summary">
                        <span>5日籌碼集中度</span>
                        <span class="chip-val {chip_class}">{r['chip_concent']}%</span>
                    </div>
                    <div class="chip-details">
                        5日法人買賣超: 外資 {r['f_val']:+d}張 | 投信 {r['t_val']:+d}張<br/>
                        最新一日: 外資 {r['f_today']:+d}張 | 投信 {r['t_today']:+d}張
                    </div>
                </div>
                
                <div class="advice-box">
                    <strong>操作戰略：</strong>{r['advice']}
                </div>
            </div>
        </div>
        """

    # HTML 模版
    html_template = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>StockMaster 雲端戰略儀表板</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Noto+Sans+TC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-main: #c9d1d9;
            --text-dim: #8b949e;
            --link-color: #58a6ff;
            --up-color: #3fb950;
            --down-color: #f85149;
            --warn-color: #d29922;
            --state-color: #1f6feb;
            --signal-bg: rgba(88, 166, 255, 0.15);
            --signal-color: #58a6ff;
        }}
        
        * {{
            box-sizing: border-box;
            font-family: 'Outfit', 'Noto Sans TC', sans-serif;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}

        .container {{
            width: 100%;
            max-width: 1200px;
        }}

        header {{
            display: flex;
            flex-direction: column;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
            margin-bottom: 25px;
        }}
        
        @media(min-width: 768px) {{
            header {{
                flex-direction: row;
                justify-content: space-between;
                align-items: flex-end;
            }}
        }}

        .title-section h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(45deg, #58a6ff, #bc85ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}

        .title-section p {{
            margin: 5px 0 0 0;
            color: var(--text-dim);
            font-size: 14px;
        }}

        .update-tag {{
            background-color: #21262d;
            border: 1px solid var(--border-color);
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
            color: var(--text-dim);
            margin-top: 15px;
            align-self: flex-start;
            font-family: monospace;
        }}
        
        @media(min-width: 768px) {{
            .update-tag {{
                margin-top: 0;
                align-self: auto;
            }}
        }}

        /* 控制列 */
        .controls {{
            display: flex;
            flex-direction: column;
            gap: 15px;
            margin-bottom: 25px;
        }}

        @media(min-width: 768px) {{
            .controls {{
                flex-direction: row;
                justify-content: space-between;
                align-items: center;
            }}
        }}

        .search-box {{
            flex: 1;
            max-width: 400px;
            position: relative;
        }}

        .search-box input {{
            width: 100%;
            background-color: #161b22;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px 15px;
            color: var(--text-main);
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }}

        .search-box input:focus {{
            border-color: var(--link-color);
        }}

        .filter-buttons {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}

        .filter-btn {{
            background-color: #21262d;
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            font-weight: 500;
        }}

        .filter-btn:hover {{
            background-color: #30363d;
        }}

        .filter-btn.active {{
            background-color: var(--link-color);
            color: #0d1117;
            border-color: var(--link-color);
            font-weight: 700;
        }}

        /* 卡片網格 */
        .grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }}

        @media(min-width: 600px) {{
            .grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
        }}

        @media(min-width: 992px) {{
            .grid {{
                grid-template-columns: repeat(3, 1fr);
            }}
        }}

        .card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
            display: flex;
            flex-direction: column;
        }}

        .card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 8px 20px rgba(0,0,0,0.4);
            border-color: #444c56;
        }}

        .card-header {{
            padding: 16px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: rgba(255,255,255,0.02);
        }}

        .stock-name {{
            font-size: 18px;
            font-weight: 700;
            color: #f0f6fc;
            display: block;
        }}

        .stock-symbol {{
            font-size: 12px;
            color: var(--text-dim);
            font-family: monospace;
        }}

        .trend-badge {{
            font-size: 12px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 20px;
        }}

        .trend-bull {{
            background-color: rgba(63, 185, 80, 0.15);
            color: var(--up-color);
            border: 1px solid rgba(63, 185, 80, 0.3);
        }}

        .trend-bear {{
            background-color: rgba(248, 81, 73, 0.15);
            color: var(--down-color);
            border: 1px solid rgba(248, 81, 73, 0.3);
        }}

        .trend-warn {{
            background-color: rgba(210, 153, 34, 0.15);
            color: var(--warn-color);
            border: 1px solid rgba(210, 153, 34, 0.3);
        }}

        .card-body {{
            padding: 16px;
            display: flex;
            flex-direction: column;
            flex: 1;
        }}

        .price-row {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            margin-bottom: 12px;
        }}

        .price-val {{
            font-size: 26px;
            font-weight: 700;
            font-family: monospace;
        }}

        .price-change {{
            font-size: 14px;
            font-weight: 600;
        }}

        .up-color {{ color: var(--up-color); }}
        .down-color {{ color: var(--down-color); }}
        .neutral-color {{ color: var(--text-dim); }}

        .badges-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 15px;
            min-height: 22px;
        }}

        .badge {{
            font-size: 11px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 4px;
        }}

        .badge-warn {{
            background-color: rgba(210, 153, 34, 0.15);
            color: var(--warn-color);
            border: 1px solid rgba(210, 153, 34, 0.3);
        }}

        .badge-state {{
            background-color: rgba(31, 110, 235, 0.15);
            color: #58a6ff;
            border: 1px solid rgba(31, 110, 235, 0.3);
        }}

        .badge-signal {{
            background-color: var(--signal-bg);
            color: var(--signal-color);
            border: 1px solid rgba(88, 166, 255, 0.3);
        }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            background-color: rgba(255,255,255,0.01);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 15px;
        }}

        .metric-item {{
            display: flex;
            flex-direction: column;
        }}

        .metric-label {{
            font-size: 11px;
            color: var(--text-dim);
            margin-bottom: 2px;
        }}

        .metric-val {{
            font-size: 14px;
            font-weight: 600;
            color: #f0f6fc;
            font-family: monospace;
        }}

        .rsi-low {{
            color: var(--up-color);
            background-color: rgba(63, 185, 80, 0.1);
            padding: 0 4px;
            border-radius: 3px;
        }}

        .rsi-high {{
            color: var(--down-color);
            background-color: rgba(248, 81, 73, 0.1);
            padding: 0 4px;
            border-radius: 3px;
        }}

        .chip-section {{
            border-top: 1px solid var(--border-color);
            padding-top: 12px;
            margin-bottom: 15px;
        }}

        .chip-summary {{
            display: flex;
            justify-content: space-between;
            font-size: 13px;
            font-weight: 500;
            margin-bottom: 4px;
        }}

        .chip-val {{
            font-weight: 700;
        }}

        .chip-high {{ color: var(--up-color); }}
        .chip-low {{ color: var(--down-color); }}

        .chip-details {{
            font-size: 11px;
            color: var(--text-dim);
            line-height: 1.4;
        }}

        .advice-box {{
            background-color: #1c2128;
            border-left: 3px solid var(--link-color);
            padding: 10px;
            border-radius: 0 6px 6px 0;
            font-size: 12px;
            color: #b1bac4;
            line-height: 1.4;
            margin-top: auto;
        }}

        .advice-box strong {{
            color: #f0f6fc;
        }}

        footer {{
            margin-top: 50px;
            padding: 20px 0;
            border-top: 1px solid var(--border-color);
            text-align: center;
            font-size: 12px;
            color: var(--text-dim);
            width: 100%;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="title-section">
                <h1>StockMaster 雲端戰略儀表板</h1>
                <p>21 檔核心觀察股 • 雲端自動健檢與獵殺監控中心</p>
            </div>
            <div class="update-tag">
                最後更新: {now_str} (台灣時間)
            </div>
        </header>

        <div class="controls">
            <div class="search-box">
                <input type="text" id="search-input" placeholder="搜尋股票代號或名稱..." onkeyup="filterCards()">
            </div>
            
            <div class="filter-buttons">
                <button class="filter-btn active" onclick="setFilter('all', this)">全部</button>
                <button class="filter-btn" onclick="setFilter('signal', this)">⚠️ 觸發訊號</button>
                <button class="filter-btn" onclick="setFilter('bull', this)">🟢 偏多</button>
                <button class="filter-btn" onclick="setFilter('bear', this)">🔴 偏空</button>
            </div>
        </div>

        <div class="grid" id="cards-container">
            {cards_html}
        </div>

        <footer>
            <p>© 2026 StockMaster. 由 GitHub Actions 雲端自動執行更新。</p>
        </footer>
    </div>

    <script>
        let currentFilter = 'all';

        function setFilter(filter, btnElement) {{
            // 變更 active 按鈕
            document.querySelectorAll('.filter-btn').forEach(btn => btn.classList.remove('active'));
            btnElement.classList.add('active');
            
            currentFilter = filter;
            filterCards();
        }}

        function filterCards() {{
            const query = document.getElementById('search-input').value.toLowerCase();
            const cards = document.querySelectorAll('.card');
            
            cards.forEach(card => {{
                const name = card.getAttribute('data-name').toLowerCase();
                const symbol = card.getAttribute('data-symbol').toLowerCase();
                const signals = card.getAttribute('data-signals');
                const trendClass = card.getAttribute('data-trend');
                
                // 搜尋文字篩選
                const matchesSearch = name.includes(query) || symbol.includes(query);
                
                // 按鈕分類篩選
                let matchesFilter = false;
                if (currentFilter === 'all') {{
                    matchesFilter = true;
                }} else if (currentFilter === 'signal') {{
                    matchesFilter = signals && signals.length > 0;
                }} else if (currentFilter === 'bull') {{
                    matchesFilter = trendClass === 'trend-bull';
                }} else if (currentFilter === 'bear') {{
                    matchesFilter = trendClass === 'trend-bear';
                }}
                
                if (matchesSearch && matchesFilter) {{
                    card.style.display = 'flex';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}
    </script>
</body>
</html>
"""
    
    # 寫入 index.html 到 root (因為 TODOLIST 是 git repo，寫入這目錄就是 repo 的 root)
    output_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_template)
    print(f"成功產生靜態網頁: {output_path}")

if __name__ == "__main__":
    build_dashboard()
