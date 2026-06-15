# -*- coding: utf-8 -*-
import os
import json
import sys
import time
import requests
import numpy as np
import pandas as pd
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

# 導入 yfinance & pandas
try:
    import yfinance as yf
except ImportError:
    print("請確認已安裝 yfinance 庫")
    sys.exit(1)

# ==================== 觀察股清單對照表 ====================
STOCK_NAMES = {
    '6561.TWO': '是方', '7703.TWO': '銳澤', '4551.TW': '智伸科', '6640.TWO': '均華',
    '3231.TW': '緯創', '5347.TWO': '世界', '6669.TW': '緯穎', '2330.TW': '台積電',
    '2891.TW': '中信金', '2889.TW': '國票金', '3008.TW': '大立光', '2308.TW': '台達電',
    '2885.TW': '元大金', '2618.TW': '長榮航', '3211.TWO': '順達', '2395.TW': '研華',
    '9907.TW': '統一實', '3362.TWO': '先進光', '9904.TW': '寶成', '1527.TW': '鑽全',
    '2002.TW': '中鋼', '3551.TWO': '世禾', '6830.TW': '汎銓'
}

# ==================== 觀察股專屬戰略配置檔 ====================
STOCK_PROFILES = {
    "6561.TWO": {"name": "是方", "target_pct": 0.20, "stop_loss_pct": 0.05},
    "7703.TWO": {"name": "銳澤", "target_pct": 0.18, "stop_loss_pct": 0.05},
    "4551.TW": {"name": "智伸科", "target_pct": 0.12, "stop_loss_pct": 0.04},
    "6640.TWO": {"name": "均華", "target_pct": 0.25, "stop_loss_pct": 0.06},
    "3231.TW": {"name": "緯創", "target_pct": 0.15, "stop_loss_pct": 0.05},
    "5347.TWO": {"name": "世界", "target_pct": 0.12, "stop_loss_pct": 0.04},
    "6669.TW": {"name": "緯穎", "target_pct": 0.20, "stop_loss_pct": 0.06},
    "2330.TW": {"name": "台積電", "target_pct": 0.15, "stop_loss_pct": 0.04},
    "9907.TW": {"name": "統一實", "target_pct": 0.08, "stop_loss_pct": 0.03},
    "2891.TW": {"name": "中信金", "target_pct": 0.08, "stop_loss_pct": 0.03},
    "2889.TW": {"name": "國票金", "target_pct": 0.08, "stop_loss_pct": 0.03},
    "3362.TWO": {"name": "先進光", "target_pct": 0.18, "stop_loss_pct": 0.05},
    "3008.TW": {"name": "大立光", "target_pct": 0.15, "stop_loss_pct": 0.04},
    "2308.TW": {"name": "台達電", "target_pct": 0.15, "stop_loss_pct": 0.04},
    "2885.TW": {"name": "元大金", "target_pct": 0.08, "stop_loss_pct": 0.03},
    "2618.TW": {"name": "長榮航", "target_pct": 0.10, "stop_loss_pct": 0.04},
    "9904.TW": {"name": "寶成", "target_pct": 0.10, "stop_loss_pct": 0.03},
    "1527.TW": {"name": "鑽全", "target_pct": 0.10, "stop_loss_pct": 0.04},
    "2002.TW": {"name": "中鋼", "target_pct": 0.08, "stop_loss_pct": 0.03},
    "3211.TWO": {"name": "順達", "target_pct": 0.20, "stop_loss_pct": 0.05},
    "2395.TW": {"name": "研華", "target_pct": 0.12, "stop_loss_pct": 0.04},
    "3551.TWO": {"name": "世禾", "target_pct": 0.15, "stop_loss_pct": 0.05},
    "6830.TW": {"name": "汎銓", "target_pct": 0.15, "stop_loss_pct": 0.05}
}

# 國營/官股護盤股
STATE_OWNED_STOCKS = {'2330.TW'}

# 三大法人籌碼與融資快取
_chip_cache = {}
_margin_cache = {}

def _to_int(v):
    return int(str(v).replace(',', '').strip() or 0)

# 代號自動清洗 (支援 .TW / .TWO 自動修復)
def clean_symbol(symbol):
    symbol = symbol.strip().upper()
    if not symbol:
        return ""
    if '.' in symbol:
        return symbol
    if symbol.isdigit():
        otc_prefixes = ('6561', '7703', '6640', '5347', '3211', '3551', '6830', '3362')
        if symbol.startswith(otc_prefixes):
            return f"{symbol}.TWO"
        return f"{symbol}.TW"
    return symbol

# ----------------- 籌碼與信用交易資料抓取 -----------------
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
    except Exception:
        pass
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
    except Exception:
        pass
    _chip_cache[key] = result
    return result

def warm_chip_cache(days_back=10):
    now = now_tw()
    for d_offset in range(1, days_back + 1):
        t_date = (now - timedelta(days=d_offset)).strftime('%Y%m%d')
        _fetch_twse_day(t_date)
        _fetch_tpex_day(t_date)

def get_chip_data_5d(symbol):
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_day if '.TWO' in symbol.upper() else _fetch_twse_day
    total_f, total_t = 0, 0
    found = 0
    now = now_tw()
    for d_offset in range(1, 15):
        if found >= 5: break
        t_date = (now - timedelta(days=d_offset)).strftime('%Y%m%d')
        day = fetcher(t_date)
        if day and code in day:
            f, t = day[code]
            total_f += f
            total_t += t
            found += 1
    return total_f, total_t

def get_chip_latest_day(symbol):
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_day if '.TWO' in symbol.upper() else _fetch_twse_day
    now = now_tw()
    for d_offset in range(1, 15):
        t_date = (now - timedelta(days=d_offset)).strftime('%Y%m%d')
        day = fetcher(t_date)
        if day and code in day:
            return day[code]
    return (0, 0)

def _fetch_twse_margin(t_date):
    key = f"TW_M_{t_date}"
    if key in _margin_cache: return _margin_cache[key]
    result = {}
    try:
        url = f"https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&date={t_date}&selectType=ALL"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10).json()
        tables = resp.get("tables", [])
        if len(tables) > 1:
            data = tables[1].get("data", [])
            for row in data:
                try:
                    code = str(row[0]).strip()
                    margin_bal = _to_int(row[6])
                    short_bal = _to_int(row[12])
                    result[code] = (margin_bal, short_bal)
                except Exception:
                    continue
    except Exception:
        pass
    _margin_cache[key] = result
    return result

def _fetch_tpex_margin(t_date):
    key = f"OTC_M_{t_date}"
    if key in _margin_cache: return _margin_cache[key]
    result = {}
    try:
        url = f"https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance?date={t_date}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10).json()
        if isinstance(resp, list):
            for item in resp:
                try:
                    code = str(item.get("SecuritiesCompanyCode", "")).strip()
                    margin_bal = _to_int(item.get("MarginPurchaseBalance", 0))
                    short_bal = _to_int(item.get("ShortSaleBalance", 0))
                    result[code] = (margin_bal, short_bal)
                except Exception:
                    continue
    except Exception:
        pass
    _margin_cache[key] = result
    return result

def get_margin_data_5d(symbol, yfin_dates):
    code = symbol.split('.')[0]
    fetcher = _fetch_tpex_margin if '.TWO' in symbol.upper() else _fetch_twse_margin
    margin_history = []
    for d_str in yfin_dates[-5:]:
        day = fetcher(d_str)
        m_bal, s_bal = day.get(code, (0, 0))
        margin_history.append((d_str, m_bal, s_bal))
    return margin_history

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
    except Exception:
        pass
    _warning_stocks = found

def is_warning_stock(symbol):
    code = symbol.split('.')[0]
    return code in _warning_stocks

# ----------------- 核心分析邏輯 -----------------
def analyze_stock(symbol):
    print(f"正在分析 {symbol}...")
    try:
        cleaned = clean_symbol(symbol)
        df = yf.download(cleaned, period="1y", progress=False)
        if df.empty and cleaned.endswith(".TW"):
            alt_symbol = cleaned.replace(".TW", ".TWO")
            df = yf.download(alt_symbol, period="1y", progress=False)
            if not df.empty:
                cleaned = alt_symbol
                
        if df.empty or len(df) < 60:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # 確保提取出來的是 1D Series 避免 yfinance 重複列或 MultiIndex 的 Series 錯誤
        close = df['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.squeeze()

        high = df['High']
        if isinstance(high, pd.DataFrame):
            high = high.iloc[:, 0]
        high = high.squeeze()

        low = df['Low']
        if isinstance(low, pd.DataFrame):
            low = low.iloc[:, 0]
        low = low.squeeze()

        volume = df['Volume']
        if isinstance(volume, pd.DataFrame):
            volume = volume.iloc[:, 0]
        volume = volume.squeeze()
        
        p_last = round(float(close.iloc[-1]), 2)
        p_prev = round(float(close.iloc[-2]), 2)
        change = round(p_last - p_prev, 2)
        change_pct = round((change / p_prev) * 100, 2)

        # === 計算過去一年成交量密集區 (POC) ===
        p_min_1y = float(close.min())
        p_max_1y = float(close.max())
        bins = np.linspace(p_min_1y, p_max_1y, 16)
        categories = pd.cut(close, bins=bins, include_lowest=True)
        volume_by_bin = volume.groupby(categories, observed=False).sum()
        max_vol_bin = volume_by_bin.idxmax()
        bin_left = float(max_vol_bin.left)
        bin_right = float(max_vol_bin.right)
        p_poc = round((bin_left + bin_right) / 2, 2)
        
        if p_last < bin_left:
            vp_type = "套牢壓力區"
            vp_class = "vp-bear"
        elif p_last > bin_right:
            vp_type = "密集支撐區"
            vp_class = "vp-bull"
        else:
            vp_type = "籌碼整理區"
            vp_class = "vp-neutral"

        # === 計算前波底部轉折點 ===
        swing_lows = []
        tail_low = low.tail(60)
        for idx in range(2, len(tail_low) - 2):
            val = float(tail_low.iloc[idx])
            if (val <= float(tail_low.iloc[idx-1]) and 
                val <= float(tail_low.iloc[idx-2]) and 
                val <= float(tail_low.iloc[idx+1]) and 
                val <= float(tail_low.iloc[idx+2])):
                swing_lows.append(val)
        
        if swing_lows:
            p_bottom = round(min(swing_lows), 2)
        else:
            p_bottom = round(float(tail_low.min()), 2)
            
        # 獲取本益比及殖利率
        pe_ratio = "N/A"
        div_yield = "N/A"
        try:
            ticker = yf.Ticker(cleaned)
            info = ticker.info
            pe = info.get("trailingPE")
            if pe: pe_ratio = f"{pe:.2f}倍"
            dy = info.get("dividendYield")
            if dy:
                if dy > 0.5:
                    div_yield = f"{dy:.2f}%"
                else:
                    div_yield = f"{dy * 100:.2f}%"
        except Exception:
            pass
            
        # 技術指標計算
        ma5 = float(close.rolling(window=5).mean().iloc[-1])
        ma10 = float(close.rolling(window=10).mean().iloc[-1])
        ma20 = float(close.rolling(window=20).mean().iloc[-1])
        ma60 = float(close.rolling(window=60).mean().iloc[-1])
        
        # RSI 14
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        rsi_val = float(100 - (100 / (1 + rs)).iloc[-1])
        
        # 布林通道
        std20 = close.rolling(window=20).std()
        bb_up_val = float((ma20 + 2 * std20).iloc[-1])
        bb_low_val = float((ma20 - 2 * std20).iloc[-1])
        bb_position = ((p_last - bb_low_val) / (bb_up_val - bb_low_val + 1e-9)) * 100
        
        # MACD
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        dif_series = exp1 - exp2
        dea_series = dif_series.ewm(span=9, adjust=False).mean()
        macd_hist = (dif_series - dea_series) * 2
        hist_val = float(macd_hist.iloc[-1])
        
        # 5日籌碼
        f_net, t_net = get_chip_data_5d(cleaned)
        f_today, t_today = get_chip_latest_day(cleaned)
        total_inst = f_net + t_net
        total_vol_5d = float(volume.tail(5).sum()) / 1000.0
        chip_concent = round((total_inst / (total_vol_5d + 0.001)) * 100, 2)
        
        # 融資券歷史
        df['YYYYMMDD'] = df.index.strftime('%Y%m%d')
        yfin_dates = df['YYYYMMDD'].tolist()
        margin_history = get_margin_data_5d(cleaned, yfin_dates)
        margin_diff = 0
        short_margin_ratio = 0.0
        
        if len(margin_history) >= 5:
            m_today = margin_history[-1][1]
            s_today = margin_history[-1][2]
            m_5d_ago = margin_history[0][1]
            margin_diff = m_today - m_5d_ago
            short_margin_ratio = round((s_today / (m_today + 0.001)) * 100, 2)
            
        p_today = float(close.iloc[-1])
        p_5d_ago = float(close.iloc[-5])
        price_diff = p_today - p_5d_ago
        
        margin_signal = False
        squeeze_signal = False
        if margin_diff < 0 and price_diff > 0:
            margin_signal = True
        if short_margin_ratio >= 20.0:
            squeeze_signal = True
            
        # --- 多空綜合評分卡 (0-5分) ---
        score = 0.0
        score_details = []
        
        if p_last > ma20:
            score += 1
            score_details.append("站上月線 (+1)")
        else:
            score_details.append("月線之下 (0)")
            
        if hist_val > 0:
            score += 1
            score_details.append("MACD紅柱 (+1)")
        else:
            score_details.append("MACD綠柱 (0)")
            
        if 50 <= rsi_val < 70:
            score += 1
            score_details.append("RSI強勢區 (+1)")
        elif rsi_val >= 70:
            score += 1
            score_details.append("RSI過熱 (+1)")
        elif rsi_val < 30:
            score += 1
            score_details.append("RSI超跌 (+1)")
        else:
            score_details.append("RSI整理 (0)")
            
        if chip_concent > 8 and total_inst > 0:
            score += 1
            score_details.append("法人鎖碼 (+1)")
        elif chip_concent > 0 and total_inst > 0:
            score += 0.5
            score_details.append("法人微買 (+0.5)")
        else:
            score_details.append("法人中性偏賣 (0)")
            
        if ma5 > ma10 > ma20:
            score += 1
            score_details.append("均線多頭 (+1)")
        elif ma5 > ma10:
            score += 0.5
            score_details.append("均線金叉 (+0.5)")
        else:
            score_details.append("均線偏弱 (0)")
            
        if margin_diff < 0 and price_diff > 0:
            score += 1.0
            score_details.append("主力洗盤 (+1)")
        if short_margin_ratio >= 20.0:
            score += 1.0
            score_details.append("軋空警戒 (+1)")
            
        # 評級符號
        if score >= 4.5:
            stars = "★★★★★"
            trend_status = "極度看多"
            trend_class = "trend-bull-extreme"
        elif score >= 3.5:
            stars = "★★★★☆"
            trend_status = "偏多操作"
            trend_class = "trend-bull"
        elif score >= 2.5:
            stars = "★★★☆☆"
            trend_status = "中性震盪"
            trend_class = "trend-neutral"
        elif score >= 1.5:
            stars = "★★☆☆☆"
            trend_status = "中性偏空"
            trend_class = "trend-bear"
        else:
            stars = "★☆☆☆☆"
            trend_status = "空頭保守"
            trend_class = "trend-bear-extreme"
            
        # 獲取個股配置與操作核心
        profile = STOCK_PROFILES.get(cleaned, {
            "name": STOCK_NAMES.get(cleaned, cleaned),
            "target_pct": 0.15,
            "stop_loss_pct": 0.05
        })
        target_mult = profile.get("target_pct", 0.15)
        stop_loss_mult = profile.get("stop_loss_pct", 0.05)
        
        # 戰術規劃
        far_from_support = p_last > p_bottom * (1 + stop_loss_mult * 2.5)
        high_60d = float(high.tail(60).max())
        
        if far_from_support:
            strategy_desc = "▲ 股價已大幅遠離轉折底部 (正乖離大，適合『有跌就買一點，有漲就賣一點』的網格分批吸納戰術)"
            buy_range = f"現價至月線 {ma20:.2f} 之間，逢回踩分批微量吸納"
            stop_loss = f"{p_bottom:.2f} 元 (中線防線)"
            target_val = f"{round(p_last * (1 + target_mult * 0.4), 2):.2f} ~ {round(p_last * (1 + target_mult * 0.8), 2):.2f} 元 (逢高分批獲利)"
        else:
            stop_loss = f"{p_bottom:.2f} 元 (近期前低防守)"
            buy_range = f"{round(p_bottom * (1 + stop_loss_mult * 0.3), 2):.2f} ~ {round(p_bottom * (1 + stop_loss_mult * 0.8), 2):.2f} 元 (底部與密集區下軌分批佈局)"
            
            if p_last < bin_left:
                strategy_desc = "■ 股價低於成交密集區 (處於套牢區下方，反彈面臨解套賣壓)"
                target_val = f"{p_poc:.2f} 元 (挑戰量能密集壓力POC)"
            elif p_last > bin_right:
                strategy_desc = "★ 股價站上成交密集區 (籌碼清洗完畢，密集區轉為強力支撐)"
                target_val = f"{round(max(high_60d, p_last * (1 + target_mult)), 2):.2f} 元以上 (站穩密集區，上看波段)"
            else:
                strategy_desc = "◆ 股價處於成交密集整理區 (籌碼反覆換手糾纏中)"
                target_val = f"{round(p_poc * (1 + target_mult * 0.4), 2):.2f} ~ {round(p_poc * (1 + target_mult * 0.8), 2):.2f} 元"

        if chip_concent > 8 and total_inst > 0:
            strategy_desc += " + [🔥 法人強勢鎖碼]"
            
        # 特別警示標籤
        extra_badges = []
        if margin_signal:
            extra_badges.append("🔥 主力洗盤")
        if squeeze_signal:
            extra_badges.append("⚡ 軋空訊號")
        if rsi_val < 30:
            extra_badges.append("⚔️ 超跌區")
        elif rsi_val > 70:
            extra_badges.append("🌋 超買區")
            
        return {
            "symbol": cleaned,
            "name": STOCK_NAMES.get(cleaned, cleaned),
            "price": p_last,
            "change": change,
            "change_pct": change_pct,
            "rsi": rsi_val,
            "ma20": ma20,
            "ma60": ma60,
            "p_poc": p_poc,
            "vp_type": vp_type,
            "vp_class": vp_class,
            "p_bottom": p_bottom,
            "pe_ratio": pe_ratio,
            "div_yield": div_yield,
            "chip_concent": chip_concent,
            "f_val": f_net,
            "t_val": t_net,
            "f_today": f_today,
            "t_today": t_today,
            "margin_diff": margin_diff,
            "short_ratio": short_margin_ratio,
            "score": score,
            "score_details": score_details,
            "stars": stars,
            "trend_status": trend_status,
            "trend_class": trend_class,
            "strategy_desc": strategy_desc,
            "buy_range": buy_range,
            "stop_loss": stop_loss,
            "target_val": target_val,
            "extra_badges": extra_badges,
            "bb_position": bb_position,
            "is_warning": is_warning_stock(cleaned),
            "is_state_owned": cleaned in STATE_OWNED_STOCKS
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

def build_dashboard():
    watchlist_path = os.path.join(os.path.dirname(__file__), "watch_list.json")
    if os.path.exists(watchlist_path):
        with open(watchlist_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            watchlist = [item["symbol"] for item in data]
    else:
        watchlist = list(STOCK_NAMES.keys())
        
    print("開始快取籌碼與融資券數據...")
    try:
        warm_chip_cache(10)
    except Exception as e:
        print(f"快取籌碼出錯: {e}")
        
    fetch_warning_stocks()
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(analyze_stock, watchlist))
        
    valid_results = [r for r in results if r]
    
    now_str = now_tw().strftime('%Y-%m-%d %H:%M:%S')
    
    # 建立卡片 HTML
    cards_html = ""
    for r in valid_results:
        price_change_class = "up-color" if r['change'] > 0 else ("down-color" if r['change'] < 0 else "neutral-color")
        change_symbol = "+" if r['change'] > 0 else ""
        
        # 標記
        badges = ""
        if r['is_warning']:
            badges += '<span class="badge badge-warn">⚠️ 警示股</span>'
        if r['is_state_owned']:
            badges += '<span class="badge badge-state">🏛️ 官股</span>'
        for b in r['extra_badges']:
            badges += f'<span class="badge badge-signal">{b}</span>'
            
        # RSI 顏色
        rsi_class = "rsi-low" if r['rsi'] < 30 else ("rsi-high" if r['rsi'] > 70 else "")
        # 籌碼集中度顏色
        chip_class = "chip-high" if r['chip_concent'] > 8.0 else ("chip-low" if r['chip_concent'] < -8.0 else "")
        # 融資變動顏色
        margin_class = "down-color" if r['margin_diff'] > 0 else "up-color" # 融資增加偏空, 減少偏多
        
        # 評分分數條
        score_pct = (r['score'] / 5.0) * 100
        
        cards_html += f"""
        <div class="card" data-symbol="{r['symbol']}" data-name="{r['name']}" data-signals="{','.join(r['extra_badges'])}" data-trend="{r['trend_class']}">
            <div class="card-header">
                <div>
                    <span class="stock-name">{r['name']}</span>
                    <span class="stock-symbol">{r['symbol']}</span>
                </div>
                <div class="trend-badge-group">
                    <div class="stars-rating">{r['stars']}</div>
                    <div class="trend-badge {r['trend_class']}">{r['trend_status']}</div>
                </div>
            </div>
            
            <div class="card-body">
                <div class="price-row">
                    <span class="price-val">{r['price']:.2f}</span>
                    <span class="price-change {price_change_class}">{change_symbol}{r['change']:.2f} ({change_symbol}{r['change_pct']:.2f}%)</span>
                </div>
                
                <div class="badges-row">
                    {badges}
                </div>
                
                <!-- 綜合戰略分析得分 -->
                <div class="score-section">
                    <div class="score-title">
                        <span>綜合多空評分</span>
                        <span class="score-val">{r['score']:.1f} / 5.0 分</span>
                    </div>
                    <div class="score-bar-container">
                        <div class="score-bar-fill {r['trend_class']}" style="width: {score_pct}%"></div>
                    </div>
                    <div class="score-details">{', '.join(r['score_details'])}</div>
                </div>
                
                <div class="metrics-grid">
                    <div class="metric-item">
                        <span class="metric-label">成交密集區 (POC)</span>
                        <span class="metric-val">{r['p_poc']:.2f} <small class="vp-badge {r['vp_class']}">{r['vp_type']}</small></span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">底部防守點</span>
                        <span class="metric-val">{r['p_bottom']:.2f}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">RSI(14)</span>
                        <span class="metric-val {rsi_class}">{r['rsi']:.1f}%</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">布林位置</span>
                        <span class="metric-val">{r['bb_position']:.1f}%</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">本益比</span>
                        <span class="metric-val">{r['pe_ratio']}</span>
                    </div>
                    <div class="metric-item">
                        <span class="metric-label">殖利率</span>
                        <span class="metric-val value-dy">{r['div_yield']}</span>
                    </div>
                </div>
                
                <div class="chip-section">
                    <div class="chip-summary">
                        <span>5日籌碼集中度</span>
                        <span class="chip-val {chip_class}">{r['chip_concent']:+.2f}%</span>
                    </div>
                    <div class="chip-details">
                        5日法人買賣超: 外資 {r['f_val']:+d}張 | 投信 {r['t_val']:+d}張<br/>
                        最新一日法人: 外資 {r['f_today']:+d}張 | 投信 {r['t_today']:+d}張
                    </div>
                </div>

                <div class="margin-section">
                    <div class="margin-summary">
                        <span>5日融資變動 / 券資比</span>
                        <span class="margin-val"><span class="{margin_class}">{r['margin_diff']:+d} 張</span> / {r['short_ratio']:.1f}%</span>
                    </div>
                </div>
                
                <div class="layout-strategy-box">
                    <div class="strat-title">🎯 戰略佈局規劃</div>
                    <div class="strat-desc">{r['strategy_desc']}</div>
                    <div class="strat-grid">
                        <div class="strat-item">
                            <span class="s-label">佈局點價：</span>
                            <span class="s-val text-buy">{r['buy_range']}</span>
                        </div>
                        <div class="strat-item">
                            <span class="s-label">防守停損：</span>
                            <span class="s-val text-stop">{r['stop_loss']}</span>
                        </div>
                        <div class="strat-item">
                            <span class="s-label">目標價位：</span>
                            <span class="s-val text-target">{r['target_val']}</span>
                        </div>
                    </div>
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
    <title>StockMaster Layout Strategy 戰略佈局儀表板</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Noto+Sans+TC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #080c10;
            --card-bg: #121820;
            --border-color: #212835;
            --text-main: #dbdee3;
            --text-dim: #8892b0;
            --link-color: #58a6ff;
            --up-color: #3fb950;
            --down-color: #f85149;
            --warn-color: #d29922;
            --state-color: #1f6feb;
            --signal-bg: rgba(88, 166, 255, 0.12);
            --signal-color: #58a6ff;
            --extreme-bull: #bc85ff;
        }}
        
        * {{
            box-spacing: border-box;
            font-family: 'Outfit', 'Noto Sans TC', sans-serif;
        }}

        body {{
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 15px;
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
            background-color: #161b22;
            border: 1px solid var(--border-color);
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
            color: var(--text-dim);
            font-family: monospace;
        }}

        .update-container {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 8px;
            margin-top: 15px;
            align-self: flex-start;
        }}

        @media(min-width: 768px) {{
            .update-container {{
                margin-top: 0;
                align-self: auto;
            }}
        }}

        .force-update-btn {{
            background: linear-gradient(135deg, #1f6feb, #58a6ff);
            border: none;
            color: #ffffff;
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            box-shadow: 0 4px 12px rgba(31, 111, 235, 0.2);
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .force-update-btn:hover {{
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(88, 166, 255, 0.3);
            filter: brightness(1.1);
        }}

        .force-update-btn:active {{
            transform: translateY(1px);
        }}

        .force-update-btn:disabled {{
            background: #212835;
            color: var(--text-dim);
            cursor: not-allowed;
            box-shadow: none;
            transform: none;
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
            background-color: #121820;
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
            background-color: #161b22;
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
            background-color: #212835;
        }}

        .filter-btn.active {{
            background-color: var(--link-color);
            color: #080c10;
            border-color: var(--link-color);
            font-weight: 700;
        }}

        /* 卡片網格 */
        .grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }}

        @media(min-width: 650px) {{
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
            box-shadow: 0 8px 25px rgba(0,0,0,0.5);
            border-color: #38445a;
        }}

        .card-header {{
            padding: 16px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: rgba(255,255,255,0.01);
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

        .trend-badge-group {{
            display: flex;
            flex-direction: column;
            align-items: flex-end;
            gap: 4px;
        }}

        .stars-rating {{
            font-size: 13px;
            color: #ffb74d;
            font-weight: bold;
            letter-spacing: 1px;
        }}

        .trend-badge {{
            font-size: 11px;
            font-weight: 600;
            padding: 2px 8px;
            border-radius: 10px;
        }}

        .trend-bull-extreme {{
            background-color: rgba(188, 133, 255, 0.15);
            color: var(--extreme-bull);
            border: 1px solid rgba(188, 133, 255, 0.3);
        }}

        .trend-bull {{
            background-color: rgba(63, 185, 80, 0.15);
            color: var(--up-color);
            border: 1px solid rgba(63, 185, 80, 0.3);
        }}

        .trend-neutral {{
            background-color: rgba(136, 146, 176, 0.15);
            color: var(--text-dim);
            border: 1px solid rgba(136, 146, 176, 0.3);
        }}

        .trend-bear {{
            background-color: rgba(248, 81, 73, 0.15);
            color: var(--down-color);
            border: 1px solid rgba(248, 81, 73, 0.3);
        }}

        .trend-bear-extreme {{
            background-color: rgba(248, 81, 73, 0.25);
            color: #ff6b6b;
            border: 1px solid rgba(248, 81, 73, 0.5);
            font-weight: 700;
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

        /* 評分條 */
        .score-section {{
            margin-bottom: 15px;
            background-color: rgba(255,255,255,0.015);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px;
        }}

        .score-title {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 6px;
        }}

        .score-val {{
            color: #ffb74d;
        }}

        .score-bar-container {{
            background-color: #161b22;
            height: 6px;
            border-radius: 3px;
            overflow: hidden;
            margin-bottom: 6px;
        }}

        .score-bar-fill {{
            height: 100%;
            border-radius: 3px;
        }}

        .score-bar-fill.trend-bull-extreme {{ background-color: var(--extreme-bull); }}
        .score-bar-fill.trend-bull {{ background-color: var(--up-color); }}
        .score-bar-fill.trend-neutral {{ background-color: var(--text-dim); }}
        .score-bar-fill.trend-bear {{ background-color: var(--down-color); }}
        .score-bar-fill.trend-bear-extreme {{ background-color: #ff6b6b; }}

        .score-details {{
            font-size: 10px;
            color: var(--text-dim);
            line-height: 1.3;
        }}

        /* 指標網格 */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 15px;
        }}

        .metric-item {{
            display: flex;
            flex-direction: column;
        }}

        .metric-label {{
            font-size: 10px;
            color: var(--text-dim);
            margin-bottom: 2px;
        }}

        .metric-val {{
            font-size: 13px;
            font-weight: 600;
            color: #f0f6fc;
            font-family: monospace;
            display: flex;
            align-items: center;
            gap: 4px;
        }}

        .vp-badge {{
            font-size: 9px;
            padding: 1px 4px;
            border-radius: 3px;
            font-weight: bold;
        }}
        .vp-bull {{ background: rgba(63, 185, 80, 0.15); color: var(--up-color); }}
        .vp-bear {{ background: rgba(248, 81, 73, 0.15); color: var(--down-color); }}
        .vp-neutral {{ background: rgba(136, 146, 176, 0.15); color: var(--text-dim); }}

        .rsi-low {{ color: var(--up-color); }}
        .rsi-high {{ color: var(--down-color); }}

        /* 籌碼與融資 */
        .chip-section, .margin-section {{
            border-top: 1px solid var(--border-color);
            padding-top: 10px;
            margin-bottom: 8px;
        }}

        .chip-summary, .margin-summary {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 3px;
        }}

        .chip-val, .margin-val {{
            font-weight: 700;
        }}

        .chip-high {{ color: var(--up-color); }}
        .chip-low {{ color: var(--down-color); }}

        .chip-details {{
            font-size: 11px;
            color: var(--text-dim);
            line-height: 1.4;
            font-family: monospace;
        }}

        /* 戰略佈局箱 */
        .layout-strategy-box {{
            background-color: #161c24;
            border: 1px solid #283548;
            border-radius: 8px;
            padding: 12px;
            margin-top: auto;
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}

        .strat-title {{
            font-size: 13px;
            font-weight: 700;
            color: #ffb74d;
            border-bottom: 1px dashed #283548;
            padding-bottom: 4px;
        }}

        .strat-desc {{
            font-size: 11px;
            color: #b1bac4;
            line-height: 1.4;
        }}

        .strat-grid {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            margin-top: 4px;
        }}

        .strat-item {{
            font-size: 11px;
            display: flex;
        }}

        .s-label {{
            color: var(--text-dim);
            flex-shrink: 0;
            width: 65px;
        }}

        .s-val {{
            font-weight: 600;
        }}

        .text-buy {{ color: #a5d6ff; }}
        .text-stop {{ color: #ffa5a5; }}
        .text-target {{ color: #d8b4fe; }}

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
                <h1>StockMaster 戰略佈局儀表板</h1>
                <p>21 檔核心觀察股 • Layout Strategy 多因子星級健檢中心</p>
            </div>
            <div class="update-container">
                <div class="update-tag">
                    最後更新: {now_str} (台灣時間)
                </div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <button id="force-update-btn" class="force-update-btn" onclick="triggerWorkflow()">⚡ 強制更新資料</button>
                    <a href="javascript:void(0)" onclick="resetToken()" id="reset-token-link" style="color: var(--text-dim); font-size: 11px; text-decoration: none; display: none;">重設 Token</a>
                </div>
            </div>
        </header>

        <div class="controls">
            <div class="search-box">
                <input type="text" id="search-input" placeholder="搜尋股票代號或名稱..." onkeyup="filterCards()">
            </div>
            
            <div class="filter-buttons">
                <button class="filter-btn active" onclick="setFilter('all', this)">全部</button>
                <button class="filter-btn" onclick="setFilter('signal', this)">⚠️ 特別訊號</button>
                <button class="filter-btn" onclick="setFilter('bull', this)">🟢 偏多 (4星以上)</button>
                <button class="filter-btn" onclick="setFilter('bear', this)">🔴 偏空 (2星以下)</button>
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
                
                const matchesSearch = name.includes(query) || symbol.includes(query);
                
                let matchesFilter = false;
                if (currentFilter === 'all') {{
                    matchesFilter = true;
                }} else if (currentFilter === 'signal') {{
                    matchesFilter = signals && signals.length > 0;
                }} else if (currentFilter === 'bull') {{
                    matchesFilter = trendClass === 'trend-bull' || trendClass === 'trend-bull-extreme';
                }} else if (currentFilter === 'bear') {{
                    matchesFilter = trendClass === 'trend-bear' || trendClass === 'trend-bear-extreme';
                }}
                
                if (matchesSearch && matchesFilter) {{
                    card.style.display = 'flex';
                }} else {{
                    card.style.display = 'none';
                }}
            }});
        }}

        async function triggerWorkflow() {{
            const btn = document.getElementById('force-update-btn');
            
            let token = localStorage.getItem('github_token');
            if (!token) {{
                token = prompt("請輸入您的 GitHub Personal Access Token (PAT) 以便觸發更新：\\n(此 Token 僅儲存於您手機瀏覽器的 localStorage 中，不會上傳到任何其他伺服器)");
                if (!token) return;
                token = token.trim();
                localStorage.setItem('github_token', token);
            }}

            btn.disabled = true;
            btn.innerHTML = '⏳ 正在發送更新請求...';

            try {{
                const owner = 'dapu25354-cloud';
                const repo = 'stock-monitor';
                const workflowId = 'stock_monitor.yml';
                
                const response = await fetch(`https://api.github.com/repos/${{owner}}/${{repo}}/actions/workflows/${{workflowId}}/dispatches`, {{
                    method: 'POST',
                    headers: {{
                        'Authorization': `Bearer ${{token}}`,
                        'Accept': 'application/vnd.github+json',
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{
                        ref: 'main',
                        inputs: {{
                            mode: 'intraday'
                        }}
                    }})
                }});

                if (response.status === 204) {{
                    alert('🎉 已成功觸發 GitHub Actions 雲端更新！\\n更新過程約需要 1~2 分鐘，請於 1-2 分鐘後重新整理網頁查看最新數據。');
                    btn.innerHTML = '✅ 已觸發更新 (請稍後重整理)';
                    setTimeout(() => {{
                        btn.disabled = false;
                        btn.innerHTML = '⚡ 強制更新資料';
                    }}, 60000);
                }} else {{
                    const errData = await response.json().catch(() => ({{}}));
                    const errMsg = errData.message || `HTTP ${{response.status}}`;
                    alert(`❌ 觸發失敗：${{errMsg}}\\n可能原因：Token 無效或沒有 Actions 權限。`);
                    
                    if (response.status === 401 || response.status === 403 || response.status === 404) {{
                        localStorage.removeItem('github_token');
                    }}
                    
                    btn.disabled = false;
                    btn.innerHTML = '⚡ 強制更新資料';
                }}
            }} catch (error) {{
                alert(`❌ 連線錯誤：${{error.message}}`);
                btn.disabled = false;
                btn.innerHTML = '⚡ 強制更新資料';
            }}
            checkTokenDisplay();
        }}

        function checkTokenDisplay() {{
            const token = localStorage.getItem('github_token');
            const link = document.getElementById('reset-token-link');
            if (token) {{
                link.style.display = 'inline';
            }} else {{
                link.style.display = 'none';
            }}
        }}

        function resetToken() {{
            localStorage.removeItem('github_token');
            alert('GitHub Token 已清除，下次點擊更新時將會重新提示輸入。');
            checkTokenDisplay();
        }}

        window.addEventListener('DOMContentLoaded', checkTokenDisplay);
        
        if (document.readyState === 'interactive' || document.readyState === 'complete') {{
            checkTokenDisplay();
    </script>
</body>
</html>
"""
    output_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_template)
    print(f"成功產生靜態網頁: {output_path}")

if __name__ == "__main__":
    build_dashboard()
