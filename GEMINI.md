# Project Context: Professional Stock Indicator System

## Core Requirements
- **Watchlist**: Always monitor the specific 21 Taiwan stocks: 
    6561.TWO 是方, 7703.TWO 銳澤, 4551.TW 智伸科, 6640.TW 均華, 3231.TW 緯創, 5347.TWO 世界, 
    6669.TW 緯穎, 2330.TW 台積電, 9907.TW 統一實, 2891.TW 中信金, 2889.TW 國票金, 3362.TWO 先進光, 
    3008.TW 大立光, 2308.TW 台達電, 2885.TW 元大金, 2618.TW 長榮航, 9904.TW 寶成, 1527.TW 鑽全, 
    2002.TW 中鋼, 3211.TWO 順達, 2395.TW 研華.
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

## Maintenance Notes
- Whenever starting a new session, verify that the FastAPI backend is running on port 8000 and the scheduler is active for the 30-minute periodic scans.
- Use the full professional indicator logic (TD / KD / MACD / RSI / 20MA + chip concentration). Do not regress to simplified 20MA-only versions.
