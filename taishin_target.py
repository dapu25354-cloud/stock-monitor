# -*- coding: utf-8 -*-
import os
import sys
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone, timedelta

# 確保輸出支援 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

TW_TZ = timezone(timedelta(hours=8))
def now_tw():
    return datetime.now(TW_TZ)

def analyze_taishin():
    symbol = "2887.TW"
    name = "台新新光金"
    print(f"正在分析 {name} ({symbol}) 的最新數據與基本面...")
    try:
        df = yf.download(symbol, period="1y", progress=False)
        if df.empty or len(df) < 60:
            print("無法獲取台新新光金的 K 線數據")
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

        # 均線計算
        ma5 = float(close.rolling(window=5).mean().iloc[-1])
        ma10 = float(close.rolling(window=10).mean().iloc[-1])
        ma20 = float(close.rolling(window=20).mean().iloc[-1])
        ma60 = float(close.rolling(window=60).mean().iloc[-1])
        ma120 = float(close.rolling(window=120).mean().iloc[-1])
        
        # RSI 14
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        rsi_val = float(100 - (100 / (1 + rs)).iloc[-1])

        # Bollinger Bands
        std20 = close.rolling(window=20).std()
        bb_up = float((ma20 + 2 * std20).iloc[-1])
        bb_low = float((ma20 - 2 * std20).iloc[-1])
        bb_pos = ((p_last - bb_low) / (bb_up - bb_low + 1e-9)) * 100

        # MACD
        exp1 = close.ewm(span=12, adjust=False).mean()
        exp2 = close.ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = float(((dif - dea) * 2).iloc[-1])

        # POC 成交量密集區 (1年)
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
            vp_type = "量能密集壓力區"
            vp_class = "vp-bear"
        elif p_last > bin_right:
            vp_type = "量能密集支撐區"
            vp_class = "vp-bull"
        else:
            vp_type = "量能密集整理區"
            vp_class = "vp-neutral"

        # 底部轉折點
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

        # 獲取基本面資料
        pe_ratio = 12.5  # 預設估計值
        div_yield = 0.05  # 預設 5% 估計值
        eps = 1.45  # 預設估計值
        dividend = 0.75  # 預設估計值
        
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            pe = info.get("trailingPE")
            if pe: pe_ratio = pe
            dy = info.get("dividendYield")
            if dy: div_yield = dy if dy < 0.5 else dy / 100.0
            
            # 從 info 中推估 EPS
            e = info.get("trailingEps")
            if e: eps = e
            else: eps = p_last / pe_ratio
            
            # 股利推估
            d = info.get("dividendRate")
            if d: dividend = d
            else: dividend = p_last * div_yield
        except Exception:
            pass

        # --- 多空綜合評分卡 (0-5分) ---
        score = 0.0
        score_details = []
        
        if p_last > ma20:
            score += 1.0
            score_details.append("站上月線 (+1.0)")
        else:
            score_details.append("月線之下 (0)")

        if p_last > ma60:
            score += 1.0
            score_details.append("站上季線 (+1.0)")
        else:
            score_details.append("季線之下 (0)")

        if macd_hist > 0:
            score += 1.0
            score_details.append("MACD紅柱 (+1.0)")
        else:
            score_details.append("MACD綠柱 (0)")

        if 50 <= rsi_val < 70:
            score += 1.0
            score_details.append("RSI強勢區 (+1.0)")
        else:
            score_details.append("RSI非強勢區 (0)")

        if ma5 > ma10 > ma20:
            score += 1.0
            score_details.append("短均多頭排列 (+1.0)")
        else:
            score_details.append("短均非排列 (0)")

        # 評星與評語
        if score >= 4.5:
            stars = "★★★★★"
            trend_desc = "極度看多"
            trend_class = "trend-bull-extreme"
        elif score >= 3.5:
            stars = "★★★★☆"
            trend_desc = "偏多操作"
            trend_class = "trend-bull"
        elif score >= 2.5:
            stars = "★★★☆☆"
            trend_desc = "中性整理"
            trend_class = "trend-neutral"
        elif score >= 1.5:
            stars = "★★☆☆☆"
            trend_desc = "弱勢修正"
            trend_class = "trend-bear"
        else:
            stars = "★☆☆☆☆"
            trend_desc = "空頭防禦"
            trend_class = "trend-bear-extreme"

        now_str = now_tw().strftime('%Y-%m-%d %H:%M:%S')

        # 估算目標價模型 (3個場景)
        target_conservative = round(ma20, 2)
        target_neutral = round(p_poc * 1.10, 2)
        target_optimistic = round(p_last * 1.25, 2)

        # 產生 HTML
        price_change_class = "up-color" if change > 0 else ("down-color" if change < 0 else "neutral-color")
        change_sign = "+" if change > 0 else ""

        # 使用一般字串與 replace 避免 f-string 解析 {} 錯誤
        html_template = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>台新新光金 (2887) 估值與戰略目標價決策系統</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Noto+Sans+TC:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f19;
            --card-bg: #151d30;
            --border-color: #24314f;
            --text-main: #e2e8f0;
            --text-dim: #7f92b0;
            --link-color: #38bdf8;
            --up-color: #4ade80;
            --down-color: #f87171;
            --warn-color: #fbbf24;
            --extreme-bull: #bc85ff;
        }

        * {
            box-sizing: border-box;
            font-family: 'Outfit', 'Noto Sans TC', sans-serif;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 15px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        .container {
            width: 100%;
            max-width: 900px;
        }

        header {
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
            margin-bottom: 25px;
            text-align: center;
        }

        .title-section h1 {
            margin: 0;
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(45deg, #38bdf8, #bc85ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .title-section p {
            margin: 5px 0 0 0;
            color: var(--text-dim);
            font-size: 14px;
        }

        .update-tag {
            background-color: #1e293b;
            border: 1px solid var(--border-color);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 10px;
            display: inline-block;
            font-family: monospace;
        }

        /* 雙欄主版面 */
        .main-layout {
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }

        @media(min-width: 768px) {
            .main-layout {
                grid-template-columns: 3fr 2fr;
            }
        }

        /* 卡片共用樣式 */
        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }

        /* 即時報價卡 */
        .price-card {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: radial-gradient(circle at top right, #1e293b, var(--card-bg));
        }

        .price-info h2 {
            margin: 0;
            font-size: 22px;
            color: #fff;
        }

        .price-info .symbol {
            font-size: 13px;
            color: var(--text-dim);
            font-family: monospace;
        }

        .price-details {
            text-align: right;
        }

        .price-val {
            font-size: 38px;
            font-weight: 700;
            font-family: monospace;
            display: block;
            line-height: 1.1;
        }

        .price-change {
            font-size: 15px;
            font-weight: 600;
        }

        /* 目標價動態計算器 */
        .calculator-card {
            border: 2px solid var(--link-color);
            box-shadow: 0 10px 25px rgba(56, 189, 248, 0.12);
        }

        .card-title {
            font-size: 16px;
            font-weight: 700;
            color: #fff;
            margin-top: 0;
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .calculator-grid {
            display: flex;
            flex-direction: column;
            gap: 15px;
            margin-bottom: 20px;
        }

        .slider-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }

        .slider-header {
            display: flex;
            justify-content: space-between;
            font-size: 13px;
        }

        .slider-label {
            color: var(--text-dim);
        }

        .slider-value {
            font-weight: 700;
            color: var(--link-color);
            font-family: monospace;
        }

        .slider-group input[type="range"] {
            width: 100%;
            height: 6px;
            background: #0b0f19;
            border-radius: 3px;
            outline: none;
            accent-color: var(--link-color);
        }

        .calc-result-box {
            background-color: rgba(0,0,0,0.25);
            border-radius: 8px;
            padding: 15px;
            text-align: center;
            border: 1px dashed var(--border-color);
        }

        .calc-result-title {
            font-size: 12px;
            color: var(--text-dim);
            text-transform: uppercase;
        }

        .calc-result-val {
            font-size: 32px;
            font-weight: 700;
            color: var(--up-color);
            font-family: monospace;
            margin: 5px 0;
        }

        .calc-result-desc {
            font-size: 11px;
            color: var(--text-dim);
        }

        /* 多空評級與均線 */
        .stars-rating {
            font-size: 18px;
            color: #ffb74d;
            font-weight: bold;
            letter-spacing: 1px;
        }

        .trend-badge {
            font-size: 12px;
            font-weight: 600;
            padding: 4px 10px;
            border-radius: 20px;
            display: inline-block;
            margin-top: 5px;
        }

        .trend-bull-extreme { background: rgba(188, 133, 255, 0.15); color: var(--extreme-bull); border: 1px solid rgba(188, 133, 255, 0.3); }
        .trend-bull { background: rgba(74, 222, 128, 0.15); color: var(--up-color); border: 1px solid rgba(74, 222, 128, 0.3); }
        .trend-neutral { background: rgba(127, 146, 176, 0.15); color: var(--text-dim); border: 1px solid rgba(127, 146, 176, 0.3); }
        .trend-bear { background: rgba(248, 113, 113, 0.15); color: var(--down-color); border: 1px solid rgba(248, 113, 113, 0.3); }

        /* 技術指標網格 */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }

        .metric-item {
            background-color: rgba(255,255,255,0.01);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px;
        }

        .metric-label {
            font-size: 11px;
            color: var(--text-dim);
            display: block;
            margin-bottom: 2px;
        }

        .metric-val {
            font-size: 15px;
            font-weight: 600;
            color: #fff;
            font-family: monospace;
        }

        .vp-badge {
            font-size: 9px;
            padding: 1px 4px;
            border-radius: 3px;
            font-weight: bold;
            margin-left: 4px;
        }
        .vp-bull { background: rgba(74, 222, 128, 0.15); color: var(--up-color); }
        .vp-bear { background: rgba(248, 113, 113, 0.15); color: var(--down-color); }
        .vp-neutral { background: rgba(127, 146, 176, 0.15); color: var(--text-dim); }

        /* 目標價場景卡 */
        .scenario-box {
            border-left: 4px solid var(--link-color);
            padding: 12px;
            background-color: rgba(255,255,255,0.015);
            border-radius: 0 8px 8px 0;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .scenario-box.conserv { border-left-color: var(--text-dim); }
        .scenario-box.neut { border-left-color: var(--link-color); }
        .scenario-box.optim { border-left-color: var(--extreme-bull); }

        .scen-title {
            font-weight: 700;
            color: #fff;
            font-size: 14px;
        }

        .scen-desc {
            font-size: 11px;
            color: var(--text-dim);
            margin-top: 2px;
        }

        .scen-val {
            font-size: 20px;
            font-weight: 700;
            font-family: monospace;
        }

        .up-color { color: var(--up-color); }
        .down-color { color: var(--down-color); }
        .neutral-color { color: var(--text-dim); }

        footer {
            margin-top: 40px;
            padding: 20px 0;
            border-top: 1px solid var(--border-color);
            text-align: center;
            font-size: 11px;
            color: var(--text-dim);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="title-section">
                <h1>台新新光金 (2887) 估值與目標價</h1>
                <p>Layout Strategy 多因子分析與動態估值系統</p>
            </div>
            <div class="update-tag">
                最後更新: __NOW_STR__
            </div>
        </header>

        <!-- 即時報價卡片 -->
        <div class="card price-card">
            <div class="price-info">
                <h2>台新新光金</h2>
                <span class="symbol">__SYMBOL__ • 合併存續公司</span>
                <div>
                    <div class="stars-rating">__STARS__</div>
                    <span class="trend-badge __TREND_CLASS__">__TREND_DESC__</span>
                </div>
            </div>
            <div class="price-details">
                <span class="price-val">__PRICE__</span>
                <span class="price-change __PRICE_CHANGE_CLASS__">__CHANGE_SIGN____CHANGE__ (__CHANGE_SIGN____CHANGE_PCT__%)</span>
            </div>
        </div>

        <!-- 雙欄佈局 -->
        <div class="main-layout">
            <!-- 左欄：動態目標價估算器 -->
            <div>
                <div class="card calculator-card">
                    <div class="card-title">
                        <span>🧮 動態目標價試算器</span>
                        <span style="font-size:11px;color:var(--text-dim);font-weight:normal;">拉動滑桿即時計算</span>
                    </div>
                    
                    <div class="calculator-grid">
                        <!-- EPS 滑桿 -->
                        <div class="slider-group">
                            <div class="slider-header">
                                <span class="slider-label">預估每股盈餘 (EPS)</span>
                                <span class="slider-value" id="val-eps">__EPS__ 元</span>
                            </div>
                            <input type="range" id="slide-eps" min="0.5" max="3.0" value="__EPS__" step="0.05" oninput="calculateTarget()">
                        </div>

                        <!-- PE 本益比滑桿 -->
                        <div class="slider-group">
                            <div class="slider-header">
                                <span class="slider-label">預估本益比倍數 (P/E)</span>
                                <span class="slider-value" id="val-pe">__PE__ 倍</span>
                            </div>
                            <input type="range" id="slide-pe" min="8" max="20" value="__PE__" step="0.5" oninput="calculateTarget()">
                        </div>

                        <!-- 股利分配率滑桿 -->
                        <div class="slider-group">
                            <div class="slider-header">
                                <span class="slider-label">預估配息股利</span>
                                <span class="slider-value" id="val-div">__DIVIDEND__ 元</span>
                            </div>
                            <input type="range" id="slide-div" min="0.2" max="2.0" value="__DIVIDEND__" step="0.05" oninput="calculateTarget()">
                        </div>

                        <!-- 目標殖利率滑桿 -->
                        <div class="slider-group">
                            <div class="slider-header">
                                <span class="slider-label">目標殖利率要求</span>
                                <span class="slider-value" id="val-yield">__YIELD_PCT__%</span>
                            </div>
                            <input type="range" id="slide-yield" min="3.0" max="8.0" value="__YIELD_PCT__" step="0.1" oninput="calculateTarget()">
                        </div>
                    </div>

                    <!-- 計算結果呈現 -->
                    <div class="calc-result-box">
                        <div class="calc-result-title">🎯 本益比法推估目標價</div>
                        <div class="calc-result-val" id="result-pe-target">__PE_TARGET__ 元</div>
                        <div class="calc-result-desc __PE_DIFF_CLASS__" id="result-pe-diff">較現價空間: __PE_DIFF__%</div>
                    </div>

                    <div class="calc-result-box" style="margin-top:15px; border-color:var(--extreme-bull);">
                        <div class="calc-result-title">💰 股利殖利率法折現目標價</div>
                        <div class="calc-result-val" id="result-yield-target" style="color:var(--extreme-bull)">__YIELD_TARGET__ 元</div>
                        <div class="calc-result-desc __YIELD_DIFF_CLASS__" id="result-yield-diff">較現價空間: __YIELD_DIFF__%</div>
                    </div>
                </div>
            </div>

            <!-- 右欄：技術指標與目標場景 -->
            <div>
                <!-- 關鍵指標 -->
                <div class="card" style="padding-bottom:10px;">
                    <div class="card-title">📊 關鍵量能與均線關卡</div>
                    <div class="metrics-grid">
                        <div class="metric-item">
                            <span class="metric-label">成交密集 POC</span>
                            <span class="metric-val">__POC__ <small class="vp-badge __VP_CLASS__">__VP_TYPE__</small></span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-label">前波底部防守</span>
                            <span class="metric-val">__BOTTOM__</span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-label">月線 (20MA)</span>
                            <span class="metric-val">__MA20__</span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-label">季線 (60MA)</span>
                            <span class="metric-val">__MA60__</span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-label">半年線 (120MA)</span>
                            <span class="metric-val">__MA120__</span>
                        </div>
                        <div class="metric-item">
                            <span class="metric-label">RSI(14)強度</span>
                            <span class="metric-val">__RSI__%</span>
                        </div>
                    </div>
                </div>

                <!-- 目標場景規劃 -->
                <div class="card">
                    <div class="card-title">🎯 戰略目標價場景規劃</div>
                    
                    <div class="scenario-box conserv">
                        <div>
                            <div class="scen-title">保守回測支撐</div>
                            <div class="scen-desc">回測月線尋求防守</div>
                        </div>
                        <div class="scen-val neutral-color">__TARGET_CONSERVATIVE__</div>
                    </div>

                    <div class="scenario-box neut">
                        <div>
                            <div class="scen-title">中性量能突破</div>
                            <div class="scen-desc">站穩密集區往上挑戰</div>
                        </div>
                        <div class="scen-val text-buy" style="color:var(--link-color)">__TARGET_NEUTRAL__</div>
                    </div>

                    <div class="scenario-box optim">
                        <div>
                            <div class="scen-title">樂觀估值重估</div>
                            <div class="scen-desc">合併綜效顯現上看波段</div>
                        </div>
                        <div class="scen-val text-target" style="color:var(--extreme-bull)">__TARGET_OPTIMISTIC__</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 評分明細說明 -->
        <div class="card" style="font-size:12px;color:var(--text-dim);line-height:1.5;">
            <strong>Layout Strategy 得分明細：</strong> __SCORE_DETAILS__ (總得分: __SCORE__ / 5.0 分)
        </div>

        <footer>
            <p>© 2026 StockMaster 戰略決策中心. 由 GitHub Actions 提供雲端運算。</p>
        </footer>
    </div>

    <script>
        const currentPrice = __PRICE__;

        function calculateTarget() {
            const eps = parseFloat(document.getElementById('slide-eps').value);
            const pe = parseFloat(document.getElementById('slide-pe').value);
            const div = parseFloat(document.getElementById('slide-div').value);
            const yld = parseFloat(document.getElementById('slide-yield').value) / 100.0;

            // 更新滑桿數值文字顯示
            document.getElementById('val-eps').innerText = eps.toFixed(2) + ' 元';
            document.getElementById('val-pe').innerText = pe.toFixed(1) + ' 倍';
            document.getElementById('val-div').innerText = div.toFixed(2) + ' 元';
            document.getElementById('val-yield').innerText = (yld * 100).toFixed(1) + '%';

            // 1. 本益比法目標價
            const peTarget = eps * pe;
            const peDiff = ((peTarget - currentPrice) / currentPrice * 100);
            document.getElementById('result-pe-target').innerText = peTarget.toFixed(2) + ' 元';
            
            const peDiffEl = document.getElementById('result-pe-diff');
            peDiffEl.innerText = '較現價空間: ' + (peDiff >= 0 ? '+' : '') + peDiff.toFixed(1) + '%';
            peDiffEl.className = 'calc-result-desc ' + (peDiff >= 0 ? 'up-color' : 'down-color');

            // 2. 殖利率折現法目標價
            const yldTarget = div / yld;
            const yldDiff = ((yldTarget - currentPrice) / currentPrice * 100);
            document.getElementById('result-yield-target').innerText = yldTarget.toFixed(2) + ' 元';
            
            const yldDiffEl = document.getElementById('result-yield-diff');
            yldDiffEl.innerText = '較現價空間: ' + (yldDiff >= 0 ? '+' : '') + yldDiff.toFixed(1) + '%';
            yldDiffEl.className = 'calc-result-desc ' + (yldDiff >= 0 ? 'up-color' : 'down-color');
        }
    </script>
</body>
</html>
"""

        # 替換標籤
        pe_target = eps * pe_ratio
        pe_diff = ((pe_target - p_last) / p_last) * 100
        pe_diff_class = "up-color" if pe_diff >= 0 else "down-color"
        
        yield_target = dividend / div_yield
        yield_diff = ((yield_target - p_last) / p_last) * 100
        yield_diff_class = "up-color" if yield_diff >= 0 else "down-color"

        html_content = html_template \
            .replace("__NOW_STR__", now_str) \
            .replace("__SYMBOL__", symbol) \
            .replace("__STARS__", stars) \
            .replace("__TREND_CLASS__", trend_class) \
            .replace("__TREND_DESC__", trend_desc) \
            .replace("__PRICE__", f"{p_last:.2f}") \
            .replace("__PRICE_CHANGE_CLASS__", price_change_class) \
            .replace("__CHANGE_SIGN__", change_sign) \
            .replace("__CHANGE__", f"{change:.2f}") \
            .replace("__CHANGE_PCT__", f"{change_pct:.2f}") \
            .replace("__EPS__", f"{eps:.2f}") \
            .replace("__PE__", f"{pe_ratio:.1f}") \
            .replace("__DIVIDEND__", f"{dividend:.2f}") \
            .replace("__YIELD_PCT__", f"{(div_yield * 100):.1f}") \
            .replace("__PE_TARGET__", f"{pe_target:.2f}") \
            .replace("__PE_DIFF_CLASS__", pe_diff_class) \
            .replace("__PE_DIFF__", f"{pe_diff:+.1f}") \
            .replace("__YIELD_TARGET__", f"{yield_target:.2f}") \
            .replace("__YIELD_DIFF_CLASS__", yield_diff_class) \
            .replace("__YIELD_DIFF__", f"{yield_diff:+.1f}") \
            .replace("__POC__", f"{p_poc:.2f}") \
            .replace("__VP_CLASS__", vp_class) \
            .replace("__VP_TYPE__", vp_type) \
            .replace("__BOTTOM__", f"{p_bottom:.2f}") \
            .replace("__MA20__", f"{ma20:.2f}") \
            .replace("__MA60__", f"{ma60:.2f}") \
            .replace("__MA120__", f"{ma120:.2f}") \
            .replace("__RSI__", f"{rsi_val:.1f}") \
            .replace("__TARGET_CONSERVATIVE__", f"{target_conservative:.2f}") \
            .replace("__TARGET_NEUTRAL__", f"{target_neutral:.2f}") \
            .replace("__TARGET_OPTIMISTIC__", f"{target_optimistic:.2f}") \
            .replace("__SCORE_DETAILS__", ", ".join(score_details)) \
            .replace("__SCORE__", f"{score:.1f}")

        # 寫入檔案
        output_path = os.path.join(os.path.dirname(__file__), "taishin_target.html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"成功產生台新新光金估值網頁: {output_path}")

    except Exception as e:
        print(f"處理台新金估值時出錯: {e}")

if __name__ == "__main__":
    analyze_taishin()
