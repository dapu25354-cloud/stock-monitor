# Project Context: Professional Stock Indicator System

## Core Requirements
- **Watchlist**: Always monitor the specific 24 Taiwan stocks: 
    6561.TWO 是方, 7703.TWO 銳澤, 4551.TW 智伸科, 6640.TWO 均華, 3231.TW 緯創, 5347.TWO 世界, 
    6669.TW 緯穎, 2330.TW 台積電, 9907.TW 統一實, 2891.TW 中信金, 2889.TW 國票金, 3362.TWO 先進光, 
    3008.TW 大立光, 2308.TW 台達電, 2885.TW 元大金, 2618.TW 長榮航, 9904.TW 寶成, 1527.TW 鑽全, 
    2002.TW 中鋼, 3211.TWO 順達, 2395.TW 研華, 3551.TWO 世禾, 6830.TW 汎銓, 2887.TW 台新金.
- **Technical Indicators**: 
    - Use the professional logic: TD (DeMark Sequential), KD, MACD, RSI, and 20MA.
    - Include **Chip Concentration** analysis (Three Institutional Investors data from TWSE/TPEx).
- **Notifications**: Automatic Telegram alerts triggered by:
    - Main Force buying/selling (Chip concentration > 8% or < -8%).
    - Technical pivots (MACD/KD Golden Cross, TD low point reversal).
- **Credentials**: Use the `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` as configured in the backend environment.

## File Locations
- **Backend**: `backend/main.py` contains the core indicator and notification logic.
- **Frontend**: `frontend/index.html` and `app.js` provide the real-time monitoring dashboard.

## Cloud Execution (GitHub Actions)
- **Workflow**: `.github/workflows/stock_monitor.yml` handles manual dispatch updates.
- **Trigger Mode**: 
    - Triggered manually via the **"⚡ 強制更新資料" (Force Update)** button on the "庫存股雷達" dashboard.
    - Utilizes a locally stored GitHub PAT (`localStorage`) to send direct workflow dispatch API calls.

## Migrated Hunter Scripts (Cloud-Ready)
- **`cold_blooded_hunter.py`**: Refactored for cloud use. Supports environment variables and relative paths.
- **`panic_bottom_hunter.py`**: Refactored for cloud use. Detects extreme oversold/panic conditions.
- **Requirements**: Requires `ta` library for technical indicators.

## Maintenance Notes
- **Local vs Cloud**: Local scripts in `python/` are for manual/GUI use. Scripts in `python/TODOLIST/` are synchronized with GitHub for 24/7 cloud monitoring.
- Use the full professional indicator logic (TD / KD / MACD / RSI / 20MA + chip concentration). Do not regress to simplified 20MA-only versions.
