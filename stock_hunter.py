# -*- coding: utf-8 -*-
"""
庫存清單 成交量獵殺燈號 ── 一次掃描全部 + 輸入編號看單檔
============================================================
心法同順達：看「量」分真假 (量比 = 當日量 ÷ 近20日均量)
  🔴 帶量下殺 / 高檔爆量收弱  → 出貨，跑
  🟢 窒息量假跌               → 洗盤，抱
  🟢 量縮見底+放量起漲        → 接刀，進
  🟡 量縮整理                 → 按兵不動
  ⚪ 量價普通                 → 觀望

用法：
  python stock_hunter.py          → 掃描全部 24 檔，列總表 (紅燈優先排前面)
  python stock_hunter.py 20       → 看第 20 檔的細節
  python stock_hunter.py 3211     → 用股票代碼看細節
  python stock_hunter.py 順達     → 用名稱看細節
"""

import os
import sys
import json
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(__file__)
WATCHLIST = os.path.join(HERE, "watch_list.json")

VOL_SPIKE = 1.5
VOL_DRY = 0.80
HIGH_ZONE = 0.70

# 燈號排序優先度 (紅燈最該看 → 排最前)
LIGHT_ORDER = {"🔴": 0, "🟢": 1, "🟡": 2, "⚪": 3, "⚠️": 4}


def load_list():
    with open(WATCHLIST, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_all(symbols):
    """一次抓全部，較快。回傳 {symbol: DataFrame}。"""
    import yfinance as yf
    # auto_adjust=True → 還原除權息/分割，價格才連續 (否則緯穎那種拆股會亂掉)
    data = yf.download(symbols, period="6mo", group_by="ticker",
                       auto_adjust=True, progress=False, threads=True)
    out = {}
    for s in symbols:
        try:
            df = data[s][["Open", "High", "Low", "Close", "Volume"]].dropna()
            if len(df) >= 25:
                out[s] = df
        except Exception:
            pass
    return out


def classify(df):
    """判斷最後一天屬於哪種盤面。"""
    # 防呆：偵測近20日有沒有「除權斷層」(單日收盤跳動 >35%，yfinance 沒還原的)
    close = df["Close"]
    jump = close.pct_change().abs().tail(20)
    if (jump > 0.35).any():
        row = df.iloc[-1]
        chg = (row["Close"] - row["Open"]) / row["Open"] * 100
        return {"close": row["Close"], "chg": chg, "v_ratio": float("nan"),
                "state": "除權", "pos": float("nan"), "light": "⚠️",
                "act": "近期除權、資料斷層→暫不判讀(等20天)"}

    vol = df["Volume"]
    avg20 = vol.rolling(20).mean()
    row = df.iloc[-1]

    v_ratio = row["Volume"] / avg20.iloc[-1]
    hi20 = df["Close"].rolling(20).max().iloc[-1]
    lo20 = df["Close"].rolling(20).min().iloc[-1]
    pos = (row["Close"] - lo20) / (hi20 - lo20) if hi20 > lo20 else 0.5
    chg = (row["Close"] - row["Open"]) / row["Open"] * 100
    upper = (row["High"] - row["Close"]) / (row["High"] - row["Low"] + 1e-9)
    prev_dry = (vol.iloc[-4:-1] / avg20.iloc[-4:-1]).mean()

    spike = v_ratio >= VOL_SPIKE
    dry = v_ratio < VOL_DRY

    if pos >= HIGH_ZONE and spike and (chg <= 0 or upper > 0.5):
        light, act = "🔴", "高檔爆量收弱→出貨,跑"
    elif chg < 0 and spike:
        light, act = "🔴", "帶量下殺→真出貨,跑"
    elif chg < 0 and dry:
        light, act = "🟢", "窒息量假跌→洗盤,抱"
    elif prev_dry <= VOL_DRY and spike and chg > 0 and pos <= 0.6:
        light, act = "🟢", "量縮見底放量起漲→接刀,進"
    elif dry:
        light, act = "🟡", "量縮整理→按兵不動"
    else:
        light, act = "⚪", "量價普通→觀望"

    state = "爆量" if spike else "窒息" if dry else "普通"
    return {"close": row["Close"], "chg": chg, "v_ratio": v_ratio,
            "state": state, "pos": pos, "light": light, "act": act}


def scan_all(items, data):
    rows = []
    for i, it in enumerate(items, 1):
        s = it["symbol"]
        if s not in data:
            rows.append((i, s, it["name"], None))
            continue
        rows.append((i, s, it["name"], classify(data[s])))

    # 紅燈優先排序 (有資料的)
    ok = [r for r in rows if r[3]]
    bad = [r for r in rows if not r[3]]
    ok.sort(key=lambda r: LIGHT_ORDER[r[3]["light"]])

    print("=" * 64)
    print("  庫存清單 成交量燈號  (紅燈=該動手, 排最前面)")
    print("=" * 64)
    print(f"  {'編號':<4}{'燈':<3}{'名稱':<7}{'收盤':>8}{'漲跌%':>7}{'量比':>6}  動作")
    print("-" * 64)
    for i, s, name, c in ok:
        nm = name + "　" * (4 - len(name))  # 對齊
        vr = "  --" if pd.isna(c["v_ratio"]) else f"{c['v_ratio']:>6.2f}"
        print(f"  {i:<4}{c['light']:<3}{nm}{c['close']:>8.1f}{c['chg']:>+7.1f}{vr:>6}  {c['act']}")
    if bad:
        print("-" * 64)
        for i, s, name, _ in bad:
            print(f"  {i:<4}⚫  {name}  (抓不到資料 {s})")
    print("=" * 64)
    reds = [r for r in ok if r[3]["light"] == "🔴"]
    if reds:
        print(f"  ⚠️ 今天有 {len(reds)} 檔紅燈要注意：" + "、".join(r[2] for r in reds))
    else:
        print("  今天沒有紅燈，手上的續抱、沒進的等綠燈。")
    print("  想看單檔細節：python stock_hunter.py 編號 (或代碼/名稱)")


def show_one(items, data, key):
    # 找出是哪一檔 (編號 / 代碼 / 名稱)
    target = None
    if key.isdigit() and 1 <= int(key) <= len(items):
        target = items[int(key) - 1]
    else:
        for it in items:
            if key in it["symbol"] or key in it["name"]:
                target = it
                break
    if not target:
        print(f"找不到「{key}」。用編號(1~{len(items)})、代碼(如3211)或名稱(如順達)。")
        return

    s = target["symbol"]
    if s not in data:
        print(f"{target['name']} ({s}) 抓不到資料。")
        return
    df = data[s]
    c = classify(df)
    print("=" * 56)
    print(f"  {target['name']} ({s})  成交量燈號")
    print("=" * 56)
    print(f"  日期     : {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  收盤     : {c['close']:.1f}  ({c['chg']:+.1f}%)")
    avg20 = df['Volume'].rolling(20).mean().iloc[-1]
    print(f"  正常量   : {avg20:,.0f} (近20日均量)")
    print(f"  今日量比 : {c['v_ratio']:.2f} ({c['state']})")
    print(f"  價格位階 : {c['pos']*100:.0f}%")
    print("-" * 56)
    print(f"  >>> {c['light']}  {c['act']}")
    print("=" * 56)
    print("\n  最近10天 價/量/量比：")
    avg = df['Volume'].rolling(20).mean()
    for d, row in df.tail(10).iterrows():
        r = row['Volume'] / avg.loc[d] if not pd.isna(avg.loc[d]) else 0
        ch = (row['Close'] - row['Open']) / row['Open'] * 100
        print(f"    {d.strftime('%m-%d')}  收{row['Close']:>7.1f}  {ch:>+5.1f}%  量比{r:.2f}")


def main():
    items = load_list()
    print(f"抓取 {len(items)} 檔資料中…(約20~30秒)")
    data = fetch_all([it["symbol"] for it in items])
    args = sys.argv[1:]
    if args:
        show_one(items, data, args[0])
    else:
        scan_all(items, data)


if __name__ == "__main__":
    main()
