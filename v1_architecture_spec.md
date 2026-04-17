# V1 Architecture Blueprint & Specification

This document serves as the absolute source of truth and reference blueprint for the V1 Stock Market Analysis Dashboard. It details the existing monolithic Streamlit application (`app.py`), documenting its internal systems, mathematical models, databases, and UI/UX mechanics. This specification is designed to guide the upcoming refactoring into a decoupled FastAPI + React architecture.

---

## 1. System Overview & Tech Stack

**Purpose:**
The V1 application is a comprehensive, free-tier stock market analysis dashboard designed for the Indian markets (NSE/BSE). It aggregates live market data, calculates advanced technical and fundamental indicators, performs automated backend scans, maintains a live portfolio, and delivers real-time swing trading analysis. 

**Libraries & External Integrations:**
*   **Frontend & Core Framework:** Streamlit (`streamlit`), Streamlit Components (`streamlit.components.v1`).
*   **Market Data APIs:** Yahoo Finance (`yfinance`).
*   **Technical analysis:** Pandas TA (`pandas_ta`).
*   **News Aggregation:** Google News (`gnews`).
*   **Charting Visualization:** Plotly (`plotly.graph_objects`, `plotly.subplots`).
*   **Database Integration:** Google Sheets via `streamlit_gsheets` (`GSheetsConnection`) and internal local CSV mirroring.
*   **Math & Data Processing:** `pandas`, `math`, `datetime`, `pytz`, `time`, `io`.

---

## 2. The Mathematical Engine (Crucial)

This section details the proprietary predictive engines embedded in the system.

### 2.1. The 11-Point Master Score (`calculate_master_score`)
This engine assigns a score ranging from 0 to 11 to classify a stock into STRONG BUY (>=7), MODERATE BUY (>=5), HOLD/WATCHLIST (>=3) or AVOID (<3).

1.  **Safety Score (up to 2 points):**
    *   Determines relative position within the Support-Resistance channel: `Risk_Pct = ((Close - Active_Support) / (Active_Resistance - Active_Support)) * 100` (Bounded 0-100).
    *   *Points:* If `Risk_Pct` <= 30% (close to support), assigns **2 pts**. If <= 60%, assigns **1 pt**.
2.  **Trend Strength / ADX (up to 2 points):**
    *   Uses 14-period Average Directional Index (ADX).
    *   *Points:* If `ADX` >= 50, assigns **2 pts**. If >= 25, assigns **1 pt**.
3.  **Volume Surge (up to 2 points):**
    *   Measures current volume vs 20-Day Volume SMA. Direction-aware (identifies accumulation vs distribution).
    *   *Points:* If Volume Ratio >= 1.5x **AND** Close >= Open (Green Candle), assigns **2 pts** (Accumulation). If Volume Ratio >= 1.0x **AND** Green Candle, assigns **1 pt**. High volume on a red candle yields **0 pts** (Distribution).
4.  **Fundamentals (up to 2 points):**
    *   *Points:* If Return on Capital Employed (ROCE) > 15%, assigns **1 pt**. If Debt-to-Equity < 0.5, assigns **1 pt**.
5.  **Structural Strength / Confluence (up to 1 point):**
    *   Checks historical respect of support zones.
    *   *Points:* If the `S1_Strength` (touches on 1% S1 boundary over 20 days) is >= 3, assigns **1 pt**.
6.  **SMA Proximity / Ignition Zone (up to 1 point):**
    *   *Points:* If the Close is above the 50-DMA but less than 10% away from it `Close < (SMA_50 * 1.1)`, assigns **1 pt**.
7.  **Support Defense / Bear Trap (up to 1 point):**
    *   Looks for reversals at support. Checks if Close is within 5% of Active Support.
    *   *Points:* If within the 5% support boundary AND (`RSI_Rising` [Current RSI > RSI 3 days ago] OR `Wick_Ratio` > 1.5), assigns **1 pt**.

### 2.2. Indicator Computations (`compute_indicators`)
*   **50/200 DMA:** Calculated using `pandas_ta.sma` with string lengths of 50 and 200.
*   **ADX:** Calculated using `pandas_ta.adx` on High, Low, Close with a length of 14.
*   **20-Day Volume SMA:** Calculated using `pandas_ta.sma` on the Volume column with a length of 20 (`VOL_20SMA`).
*   **Bear Trap Wick Detection:** `Lower Wick = (Close if Close > Open else Open) - Low`. Returns `Wick_Ratio = Lower_Wick / Body_Size`.
*   **RSI Divergence:** 14-length relative strength computed via `pandas_ta.rsi`. Boolean flag `RSI_Rising` if current RSI > RSI from 3 days ago (`shift(3)`).

### 2.3. Polarity Engine & Pivot Logic
It establishes dynamic, weighted S/R bounds using recent windows rather than standardized monthly pivots.
*   **Time Windows:** Macro context uses the last 20 days (`iloc[-21:-1]`), Momentum context uses the last 5 days (`iloc[-6:-1]`).
*   **Weighted Averages:** Gives 2x weight to the recent 5 days. `W_High = (MaxHigh_20d + MaxHigh_5d) / 2`. `W_Low = (MinLow_20d + MinLow_5d) / 2`.
*   **Calculation:** 
    *   `Pivot = (W_High + W_Low + W_Close) / 3`
    *   `S1 = (2 * Pivot) - W_High`
    *   `R1 = (2 * Pivot) - W_Low`
    *   `S2 = Pivot - (W_High - W_Low)`
    *   `R2 = Pivot + (W_High - W_Low)`
*   **Polarity States:**
    *   **RANGE (Default):** Close is between S1 and R1. `Active_Support = S1`, `Active_Resistance = R1`.
    *   **BREAKOUT:** Close > R1. Old resistance becomes support. `Active_Support = R1`, `Active_Resistance = R2`.
    *   **BREAKDOWN:** Close < S1. Old support becomes resistance. `Active_Resistance = S1`, `Active_Support = S2`.
*   **Touches:** System counts the number of times `Low` hits within 1% of S1 (`S1_Strength`) and `High` hits within 1% of R1 (`R1_Strength`) over the 20-day timeframe to determine validity.

### 2.4. Market Condition Engine (`get_market_condition`)
Unifies momentum mapping (RSI) with structural risk limits (`Risk_Pct` within the S/R range):
*   **"🚀 BREAKOUT" (cyan):** Triggers if Volume Surge >= 1.5, Risk > 80%, and close is Green. (Normally an overextended entry, but validated by massive volume breakout).
*   **"🔵 OVERSOLD" (blue):** Triggers if RSI < 30.
*   **"🟣 OVERBOUGHT" (purple):** Triggers if RSI > 70.
*   **"🟢 SAFE" (green):** Triggers if Risk_Pct < 45%.
*   **"🔴 OVEREXTENDED" (red):** Triggers if Risk_Pct > 85%.
*   **"🟡 FAIR" (yellow):** Triggers for all intermediate ranges.

---

## 3. Core Features & Modules

### 3.1. The Status Hub & Automated Scan Scheduler
*   **Macro Baseline:** Fetches NIFTY 50 (^NSEI) comparing current price to 20-SMA and 50-SMA to declare the overarching market status as "BULLISH", "CAUTION", or "BEARISH".
*   **Automated Scheduling:** Scans portfolios/watchlists automatically at designated times: `["09:30", "11:30", "13:30", "14:30", "15:15"]`. Relies on Streamlit UI reruns but guards execution via the `Metadata` Google sheet, ensuring a scan loop doesn't double-trigger. 

### 3.2. Search & Individual Analysis
*   **Fundamentals Engine:** Fetches standard limits (ROCE, Debt/Equity) via `yfinance Ticker.info`, gracefully falling back to raw computations on `tk.income_stmt` and `tk.balance_sheet` (e.g., EBIT / (Total Assets - Current Liabilities)) if info dicts are missing/None.
*   **Earnings Proximity:** Evaluates calendar objects to warn if an earnings date is slated within the next 7 days.
*   **Swing Report:** Contextually generates rich text bullets summarizing Risk/Reward setup, Volume Accumulation/Distribution, Macro Structure relative to the 52W High or baseline support, and the exact Actionable Verdict based on the master score.
*   **Candlestick Charting:** Plotly subplot integration displaying OHLC bars, 50-DMA/200-DMA, horizontal dashed S1/R1, S2/R2 overlays matched to Polarity States, and color-matched volume bars below.

### 3.3. The 1% Risk Calculator
Position sizing module governed by dual-bounded mathematical restrictions:
*   **Risk Cap:** `Max_Risk_Budget = Capital * 0.01`. Calculates `Max_Shares_by_Risk = floor(Max_Risk_Budget / (Entry_Price - Stop_Loss))`.
*   **Capital Cap:** `Max_Shares_by_Capital = floor(Capital / Entry_Price)`.
*   **Position Sizing:** Asserts the final share calculation strictly as `min(Max_Shares_by_Risk, Max_Shares_by_Capital)`. 
*   Allows the user to enter a manual override quantity which automatically reverses the math to show by what scalar their position exceeds the strict 1% risk threshold.

### 3.4. The Batch Processor
*   **Input Mechanics:** Allows parsing tab-separated inputs (via copy-pasting from standard web tables like Screener.in) or uploading localized CSV/Excel sheets.
*   **Loop Processing:** Limits checks to 50 active items to prevent yfinance rate-limiting. Calculates Master Score and unified Market Conditions offline per ticker dynamically.
*   **O(1) Bulk Actions System:** Uses a multiselect wrapper combined with pre-computed DataFrame chunks. It identifies which rows are not already in the tracked Watchlist database and adds them asynchronously via a single `pd.concat` merge, heavily overriding individual API update latency.

### 3.5. Live Portfolio, Watchlist & Ratcheting Stops
*   Renders dual unified dataframes sorted dynamically via user-selected keys. 
*   **Ratcheting Trailing Stop Logic:** As part of the `background_batch_scan` sweep, it compares the daily recalculated structural `Active_Support (s1)`. If `s1 > Highest_Trail` metric, it aggressively ratchets the trailing stop upward, saving the localized profit floor to the portfolio sheets.

### 3.6. Trade Journal (Position Closure)
*   User closes the position ("Log & Close"). Backend accesses the row values (`Buy_Price`, `CMP`, `Quantity`) from the live table, and creates a strict diff check for holding time: `Days_Held = max(0, Sell_Date - Buy_Date)`.
*   Appends `PnL_Value`, `PnL_Pct`, and standard footprint entries to `ClosedTrades` database layer and permanently drops the index from the `Portfolio` layer.

---

## 4. Database Schema
Controlled via `ensure_worksheets_exist` and unified `load_sheet_data`, bridging Google Sheets APIs and local CSV backups.

| Worksheet Tab | Column Schema Structure |
| :--- | :--- |
| **Watchlist** | `["Ticker", "Price", "Rating", "Entry Context", "Trend Strength", "Stop Loss", "Vol Footprint"]` |
| **Portfolio** | `["Ticker", "Buy_Price", "Initial_Stop", "Highest_Trail", "Quantity", "Date_Added", "CMP", "RSI_HTML", "T1_HTML", "PCT_HTML", "Vol_Foot", "Verdict_HTML", "_verdict_rank", "_vol_rank"]` |
| **Metadata** | `["Key", "Value"]` |
| **ScanHistory** | `["Window", "Timestamp", "SignalCount"]` |
| **ClosedTrades** | `["Ticker", "Buy_Date", "Sell_Date", "Buy_Price", "Sell_Price", "Quantity", "PnL_Value", "PnL_Pct", "Exit_State", "Days_Held"]` |

---

## 5. Performance & UX Optimizations
The V1 system circumvented standard Streamlit synchronous limitations using specific "hacks":
1.  **Strict Caching (`@st.cache_data`):** Implemented time-to-live restrictions across APIs to manage rate constraints and bypass repetitive network requests. (`fetch_nifty_baseline` -> 5m, `fetch_ohlcv` -> 15m, `fetch_news` -> 30m, `fetch_fundamentals` -> 60m). 
2.  **Fragmented Rerendering (`@st.fragment`):** Sits strictly over `render_trade_journal()`. Toggling the massive mathematical dataframes and calculations in the Trade Journal avoids a full un-cached repaint of the entire web app thread.
3.  **Lazy Loaded DOM Trees (`st.expander`):** Forces heavy Plotly graph payloads into `expanded=False` states, skipping expensive HTML DOM calculations until the user fundamentally opts-in.
4.  **Anti-Spam Deduping:** Stores hashed `seen_alerts` sets inside ephemeral session state to block overlapping identical WebSocket toast calls when `st.rerun` bounces.
5.  **Browser Hash Warp:** Manipulates JS via `components.html` to inject a `hash = "top"` trigger directly causing the native client browser to aggressively anchor the scrollbar after a ticker search. 
6.  **Persistent Connectivity (`@st.cache_resource`):** Holds the Google Sheets API Object open via `get_persistent_conn()` up to an hour continuously, dropping 70% of network handshake latency on save iterations.
