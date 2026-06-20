# -*- coding: utf-8 -*-
"""
順達 (3211.TWO) 實戰案例研究 + 任意日回放
==========================================================
這支腳本把我們這次討論的結論整理成「可執行的教材」。
核心心法 (治「巴來巴去」)：
    同樣是漲/跌，看價格(漲跌%)會被情緒騙；
    看「量」才分得出真假 ── 量才是大錢有沒有真的進出的證據。

四種盤面 (純用『量比 = 當日量 ÷ 近20日均量』就能分)：
  ┌─────────────────────────────────────────────────────────┐
  │ ① 假跌(洗盤)   : 跌 + 量縮(<0.8)   → 沒人真的賣 → 抱住    │
  │ ② 真出貨       : 跌 + 爆量(>=1.5)  → 有人在倒貨 → 跑      │
  │ ③ 高檔出貨     : 高檔 + 爆量 + 收黑/長上影 → 崩盤前兆 → 跑│
  │ ④ 起漲(接刀)   : 量縮見底 + 放量上漲 + 中低檔 → 進        │
  └─────────────────────────────────────────────────────────┘
看不出來的(誠實版)：量很小的「偷偷分批出貨」會慢半拍 → 要靠法人庫存方向補。

用法：
    python shunda_cases.py            # 回放 5 個經典案例 (附當時實際結果)
    python shunda_cases.py 2026-06-17 # 回放你指定的任一天
"""

import sys
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SYMBOL = "3211.TWO"

# ===== 量的門檻 (順達專屬，平均量約 1000 萬) =====
VOL_SPIKE = 1.5    # 爆量
VOL_DRY = 0.80     # 窒息/量縮
HIGH_ZONE = 0.70   # 近20日 70% 以上 = 高檔

# ===== 經典案例：日期 → (你當時的反應, 實際結果) 給回放時對照 =====
CASES = {
    "2026-04-13": ("看到 -4.13% 大跌 + 法人賣2693，想跑", "量比僅0.80窒息，是假跌，7天後彈到415 → 該抱"),
    "2026-04-23": ("(對照組) 半年最大量爆跌 -6.9%",        "量比2.89帶大量下殺，真出貨，後面續跌 → 該跑"),
    "2026-05-27": ("(對照組) 衝上492.5高點後",             "高檔爆量收黑，隔天 -6.2%崩 → 出貨前兆，該跑"),
    "2026-06-04": ("(對照組) 又一根衝高",                  "爆量長上影衝高被打下，隔天 -6.1% → 出貨，該跑"),
    "2026-06-17": ("看到綠棒跌到428，怕起跌，430跑了",     "量比0.43窒息假跌，隔天彈436 → 被洗出去，該抱"),
}


def get_data():
    import yfinance as yf
    df = yf.Ticker(SYMBOL).history(period="6mo")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def judge(df, day=None):
    """判斷某一天屬於哪種盤面。day=None 取最後一天。回傳 dict。"""
    sub = df.loc[:day] if day else df
    avg20 = sub["Volume"].rolling(20).mean()
    row = sub.iloc[-1]

    v_ratio = row["Volume"] / avg20.iloc[-1]
    hi20 = sub["Close"].rolling(20).max().iloc[-1]
    lo20 = sub["Close"].rolling(20).min().iloc[-1]
    pos = (row["Close"] - lo20) / (hi20 - lo20) if hi20 > lo20 else 0.5
    chg = (row["Close"] - row["Open"]) / row["Open"] * 100
    upper_shadow = (row["High"] - row["Close"]) / (row["High"] - row["Low"] + 1e-9)
    # 起漲前幾天是否量縮
    prev_dry = (sub["Volume"].iloc[-4:-1] / avg20.iloc[-4:-1]).mean()

    spike = v_ratio >= VOL_SPIKE
    dry = v_ratio < VOL_DRY

    # ③ 高檔出貨 (最優先警示)
    if pos >= HIGH_ZONE and spike and (chg <= 0 or upper_shadow > 0.5):
        light, verdict = "🔴 紅燈", "高檔爆量收弱 → 出貨前兆，建議跑"
    # ② 真出貨
    elif chg < 0 and spike:
        light, verdict = "🔴 紅燈", "帶量下殺 → 真出貨，建議跑"
    # ① 假跌洗盤
    elif chg < 0 and dry:
        light, verdict = "🟢 綠燈", "窒息量假跌 → 洗盤，抱住別被洗"
    # ④ 起漲接刀
    elif prev_dry <= VOL_DRY and spike and chg > 0 and pos <= 0.6:
        light, verdict = "🟢 綠燈", "量縮見底後放量起漲 → 接刀訊號"
    # 量縮整理
    elif dry:
        light, verdict = "🟡 黃燈", "量縮整理 → 按兵不動"
    else:
        light, verdict = "⚪ 白燈", "量價普通 → 觀望"

    state = "爆量" if spike else "窒息" if dry else "普通"
    return {
        "date": sub.index[-1].strftime("%Y-%m-%d"), "close": row["Close"],
        "chg": chg, "v_ratio": v_ratio, "state": state, "pos": pos,
        "upper_shadow": upper_shadow, "light": light, "verdict": verdict,
    }


def show(r, case=None):
    print("-" * 60)
    print(f"  {r['date']}   收 {r['close']:.1f}  ({r['chg']:+.1f}%)")
    print(f"  量比 {r['v_ratio']:.2f} ({r['state']})   價格位階 {r['pos']*100:.0f}%   上影 {r['upper_shadow']*100:.0f}%")
    print(f"  程式判讀 >>> {r['light']}  {r['verdict']}")
    if case:
        print(f"  當時你的反應 : {case[0]}")
        print(f"  實際結果     : {case[1]}")


def main():
    df = get_data()
    args = [a for a in sys.argv[1:]]

    if args:  # 回放指定日期
        for day in args:
            r = judge(df, day)
            show(r, CASES.get(day))
        return

    # 預設：回放 5 個經典案例
    print("=" * 60)
    print("  順達 3211 ── 5 個實戰案例回放 (量看真假)")
    print("=" * 60)
    correct = 0
    for day, case in CASES.items():
        r = judge(df, day)
        show(r, case)
        # 簡單對帳：判讀方向(抱/跑)是否符合實際結果
        said_run = "跑" in r["verdict"]
        should_run = "該跑" in case[1]
        ok = (said_run == should_run)
        correct += ok
        print(f"  對帳         : {'✅ 判讀正確' if ok else '❌ 判讀錯誤'}")
    print("=" * 60)
    print(f"  5 個案例命中 {correct}/5")
    print("  ⚠️ 提醒：這5天是已知歷史(考古題)，全中正常；")
    print("     真正價值是『窒息假跌時抱得住、帶量出貨時跑得掉』，不是預測未來。")
    print("=" * 60)


if __name__ == "__main__":
    main()
