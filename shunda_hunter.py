# -*- coding: utf-8 -*-
"""
順達 (3211.TWO) 專屬 成交量獵殺燈號  v2 (量 + 法人 三合一)
------------------------------------------------------------
核心理念 (來自實戰檢討，治「巴來巴去」)：
  * 同樣是跌，看價格(跌幾%)會兩根都怕、都被巴；看「量」才分得出真假。
        - 跌 + 量縮(窒息)  → 假跌，是洗盤   → 抱住          (例: 6/17、4/13)
        - 跌 + 爆量        → 真出貨         → 跑            (例: 4/23 半年最大量)
  * 法人「近3日合計」當輔助：淨買加強綠燈、淨賣加強紅燈。
  * 沒訊號就亮黃燈「按兵不動」，幫你踩煞車、不要手癢進出。

資料來源：
  * 價量：預設連網抓 3211.TWO；若有 shunda_data.csv 則優先讀(你自己餵)。
  * 法人：讀 shunda_foreign.csv (Date,外資,投信,自營,合計)，每天加一行即可；
          沒有這檔也能跑，只是少了法人輔助。
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

SYMBOL = "3211.TWO"
NAME = "順達"
HERE = os.path.dirname(__file__)
DATA_CSV = os.path.join(HERE, "shunda_data.csv")
FOREIGN_CSV = os.path.join(HERE, "shunda_foreign.csv")

# ===== 順達專屬參數 (「感性」就調這裡) =====
VOL_SPIKE = 1.5      # 量比 ≥ 此值 = 爆量 (順達平均量約 1000 萬)
VOL_DRY = 0.80       # 量比 < 此值 = 窒息/量縮
HIGH_ZONE = 0.70     # 收盤位於近20日 70% 以上 = 高檔
DRY_DAYS = 3         # 起漲前要先看到幾天量縮
FOREIGN_DAYS = 3     # 法人合計看最近幾天


def load_prices():
    if os.path.exists(DATA_CSV):
        print(f"[價量] 讀取你提供的 {os.path.basename(DATA_CSV)}")
        df = pd.read_csv(DATA_CSV, parse_dates=["Date"]).set_index("Date")
    else:
        print(f"[價量] 連網抓 {SYMBOL} (近6個月)")
        import yfinance as yf
        df = yf.Ticker(SYMBOL).history(period="6mo")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def load_foreign():
    """回傳法人近 N 日合計 (張)，沒有檔案就回 None。"""
    if not os.path.exists(FOREIGN_CSV):
        return None, None
    f = pd.read_csv(FOREIGN_CSV, parse_dates=["Date"]).set_index("Date").sort_index()
    recent = f["合計"].tail(FOREIGN_DAYS)
    return int(recent.sum()), recent


def analyze(df):
    vol = df["Volume"]
    avg20 = vol.rolling(20).mean()
    last = df.iloc[-1]

    v_ratio = last["Volume"] / avg20.iloc[-1]
    hi20 = df["Close"].rolling(20).max().iloc[-1]
    lo20 = df["Close"].rolling(20).min().iloc[-1]
    pos = (last["Close"] - lo20) / (hi20 - lo20) if hi20 > lo20 else 0.5
    day_chg = (last["Close"] - last["Open"]) / last["Open"] * 100
    prev_ratio = (vol.iloc[-(DRY_DAYS + 1):-1] / avg20.iloc[-(DRY_DAYS + 1):-1]).mean()

    return {
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "close": last["Close"], "avg20": avg20.iloc[-1],
        "v_ratio": v_ratio, "pos": pos, "day_chg": day_chg, "prev_ratio": prev_ratio,
    }


def decide(a, f_sum):
    """回傳 (燈號, 標題, 說明)。f_sum = 法人近3日合計(可能 None)。"""
    is_down = a["day_chg"] < 0
    spike = a["v_ratio"] >= VOL_SPIKE
    dry = a["v_ratio"] < VOL_DRY
    f_txt = ""
    if f_sum is not None:
        f_txt = f"（法人近{FOREIGN_DAYS}日合計 {f_sum:+,} 張，{'淨買' if f_sum>=0 else '淨賣'}）"

    # === 持股診斷：遇到下跌，該抱還是該跑 ===
    if is_down and spike:
        extra = "，且法人也在賣 → 紅燈更硬" if (f_sum is not None and f_sum < 0) else ""
        return ("🔴 紅燈", "帶量下殺 → 真出貨，建議跑",
                f"跌且爆量(量比{a['v_ratio']:.2f})，是真的有人在倒貨{extra}。{f_txt}")
    if is_down and dry:
        extra = "，法人近期還在買 → 更該抱" if (f_sum is not None and f_sum >= 0) else ""
        return ("🟢 綠燈(抱)", "窒息量假跌 → 洗盤，抱住別被洗",
                f"跌但量縮(量比{a['v_ratio']:.2f})，沒人真的在賣，是洗盤{extra}。{f_txt}")

    # === 進場訊號：量縮見底後放量起漲 ===
    if a["prev_ratio"] <= VOL_DRY and spike and a["day_chg"] > 0 and a["pos"] <= 0.6:
        extra = "，法人同步進場 → 訊號更強" if (f_sum is not None and f_sum > 0) else ""
        return ("🟢 綠燈(進)", "量縮見底後放量起漲 → 接刀訊號",
                f"先沒人賣(量縮)、今天放量上攻，是你等的那一根{extra}。{f_txt}")

    # === 高檔爆量收弱：出貨疑慮 ===
    if a["pos"] >= HIGH_ZONE and spike and a["day_chg"] <= 0:
        return ("🔴 紅燈", "高檔爆量收弱 → 疑似出貨",
                f"高檔放量但收不上去，小心倒貨，別追。{f_txt}")

    # === 其他：量縮整理，按兵不動 ===
    if dry:
        return ("🟡 黃燈", "量縮整理 → 按兵不動",
                f"沒量、沒方向，還在洗。亂進出最容易被巴，先別動。{f_txt}")

    return ("⚪ 白燈", "量價普通 → 觀望", f"沒有明確量訊號，等綠燈或避開紅燈。{f_txt}")


def main():
    df = load_prices()
    if len(df) < 25:
        print("資料太少 (需至少 25 筆)。")
        return

    a = analyze(df)
    f_sum, f_recent = load_foreign()
    light, title, desc = decide(a, f_sum)

    print("=" * 56)
    print(f"  {NAME} ({SYMBOL})  成交量獵殺燈號 v2")
    print("=" * 56)
    print(f"  日期       : {a['date']}")
    print(f"  收盤       : {a['close']:.1f}   ({a['day_chg']:+.1f}%)")
    print(f"  牠的正常量 : {a['avg20']:,.0f}  (近20日均量)")
    state = "爆量" if a["v_ratio"] >= VOL_SPIKE else "窒息/量縮" if a["v_ratio"] < VOL_DRY else "普通"
    print(f"  今日量比   : {a['v_ratio']:.2f} 倍   ({state})")
    print(f"  價格位階   : {a['pos']*100:.0f}%   (0%=近月低, 100%=近月高)")
    if f_sum is not None:
        print(f"  法人近{FOREIGN_DAYS}日   : {f_sum:+,} 張  ({'淨買' if f_sum>=0 else '淨賣'})")
    else:
        print("  法人        : (無 shunda_foreign.csv，略過法人輔助)")
    print("-" * 56)
    print(f"  >>> {light}  {title}")
    print(f"      {desc}")
    print("=" * 56)

    print("\n最近10天 價 / 量 / 量比：")
    vol = df["Volume"]
    avg20 = vol.rolling(20).mean()
    for d, row in df.tail(10).iterrows():
        r = row["Volume"] / avg20.loc[d] if not pd.isna(avg20.loc[d]) else 0
        chg = (row["Close"] - row["Open"]) / row["Open"] * 100
        print(f"  {d.strftime('%m-%d')}  收 {row['Close']:>6.1f}  漲跌 {chg:>+5.1f}%  量 {int(row['Volume']):>11,}  量比 {r:.2f}")


if __name__ == "__main__":
    main()
