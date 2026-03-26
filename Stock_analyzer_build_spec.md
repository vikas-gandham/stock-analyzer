# Stock Market Analysis Dashboard — Complete Build Specification

## Overview

Build a **web-based Stock Market Analysis Dashboard** using **Streamlit** (Python). This is a single-page financial tool for Indian stock markets (NSE/BSE) that combines interactive charting, risk management, news aggregation, and AI-powered analysis.

**Target deployment:** Streamlit Community Cloud (free) via GitHub.

---

## CRITICAL CONSTRAINT — 100% FREE TOOLS ONLY

Every library, API, and data source **MUST** be completely free. No paid subscriptions, no credit cards, no rate-limited services that require upgrades.

**BANNED services:** AlphaVantage, Polygon.io, any paid News API, any paid AI tier.

---

## 1. Project Structure

```
stock-dashboard/
├── app.py                    # Main Streamlit application (single file)
├── requirements.txt          # All Python dependencies
├── .streamlit/
│   └── config.toml           # Dark theme configuration
├── README.md                 # Deployment instructions
└── .gitignore
```

---

## 2. Tech Stack (All Free)

| Component            | Library / Service     | Purpose                                     |
| -------------------- | --------------------- | ------------------------------------------- |
| Framework            | `streamlit`           | Web UI framework                            |
| Market Data          | `yfinance`            | Free daily OHLCV data + corporate calendars |
| Technical Indicators | `pandas`, `pandas_ta` | Moving averages, pivot points               |
| Charting             | `plotly`              | Interactive candlestick + volume charts     |
| News Fetching        | `gnews`               | Free RSS-style Google News scraper          |
| AI Summarization     | `google-generativeai` | Gemini API free tier (user provides key)    |

---

## 3. File: `.streamlit/config.toml`

```toml
[theme]
primaryColor = "#00D4AA"
backgroundColor = "#0E1117"
secondaryBackgroundColor = "#1A1D23"
textColor = "#FAFAFA"
font = "sans serif"

[server]
headless = true
```

---

## 4. File: `requirements.txt`

```
streamlit>=1.32.0
yfinance>=0.2.36
pandas>=2.0.0
pandas_ta>=0.3.14b1
plotly>=5.18.0
gnews>=0.3.7
google-generativeai>=0.5.0
```

---

## 5. File: `.gitignore`

```
__pycache__/
*.pyc
.env
venv/
.venv/
```

---

## 6. File: `app.py` — COMPLETE SPECIFICATION

### 6.1 Page Configuration

- `st.set_page_config` must be the **very first** Streamlit command.
- Title: `"Stock Market Analysis Dashboard"`
- Icon: `"📈"`
- Layout: `"wide"`
- Sidebar: `"expanded"`

### 6.2 Custom CSS

Inject custom CSS via `st.markdown` with `unsafe_allow_html=True` for:

- Tighter top padding on `.block-container` (about `1.5rem`)
- Larger `stMetricValue` font sizes (`1.8rem`, bold)
- A pulsing red `.earnings-warning` box with:
  - Red gradient background (`#ff4b4b` to `#cc0000`)
  - White bold text, centered, rounded corners
  - CSS `@keyframes pulse` animation on `box-shadow`
- A `.story-section` class with dark background (`#1A1D23`), left green border (`#00D4AA`), padding, border-radius

### 6.3 Helper Functions

#### `fetch_ohlcv(ticker: str) -> pd.DataFrame`

- **Cached** with `@st.cache_data(ttl=900)` (15 min cache)
- Downloads 1 year of daily OHLCV data via `yf.download(ticker, start, end, progress=False, auto_adjust=True)`
- Start date = today minus 365 days
- **IMPORTANT:** Handle yfinance multi-level columns — if `df.columns` is a `MultiIndex`, flatten it with `df.columns = df.columns.get_level_values(0)`
- Return empty DataFrame on failure

#### `compute_indicators(df: pd.DataFrame) -> pd.DataFrame`

- Copy the DataFrame first
- Add `SMA_50` = `ta.sma(df["Close"], length=50)`
- Add `SMA_200` = `ta.sma(df["Close"], length=200)`
- **Pivot Point calculation** from the last 20 trading days:
  - `pp_high` = max of `High` in last 20 rows
  - `pp_low` = min of `Low` in last 20 rows
  - `pp_close` = last `Close` value
  - `Pivot = (pp_high + pp_low + pp_close) / 3`
  - `Support_1 = 2 * Pivot - pp_high`
  - `Resistance_1 = 2 * Pivot - pp_low`
- Store Pivot, Support_1, Resistance_1 as constant columns in the DataFrame
- Return the enriched DataFrame

#### `check_earnings(ticker: str) -> Optional[datetime.date]`

- Wrap everything in try/except, return `None` on any failure
- Use `yf.Ticker(ticker).calendar`
- Handle both DataFrame and dict return formats from yfinance:
  - If DataFrame: look for `"Earnings Date"` in index, get first value
  - If dict: look for `"Earnings Date"` key, get first element of list
- Convert the raw value to a `datetime.date`
- Return the date **only if** it is within the next 7 days (0 to 7 days from today), otherwise return `None`

#### `build_chart(df: pd.DataFrame, symbol: str) -> go.Figure`

- Use `make_subplots` with 2 rows, 1 column:
  - Row heights: `[0.78, 0.22]`
  - `shared_xaxes=True`, `vertical_spacing=0.03`
- **Row 1 — Candlestick + Overlays:**
  - `go.Candlestick` with green (`#00D4AA`) for up, red (`#FF4B4B`) for down
  - `go.Scatter` for 50-DMA line (gold `#FFD700`, width 1.5)
  - `go.Scatter` for 200-DMA line (blue `#1E90FF`, width 1.5)
  - `fig.add_hline` for Support (red dotted `#FF6B6B`), Resistance (teal dotted `#4ECDC4`), Pivot (gray dotted `#AAAAAA`)
  - Each hline gets an annotation with the label and value formatted as `₹{value:,.2f}`
- **Row 2 — Volume bars:**
  - `go.Bar` colored green/red based on whether `Close >= Open`
  - `showlegend=False`
- **Layout:**
  - Title: `"{symbol} — Daily Chart (1 Year)"`, font size 20
  - Template: `"plotly_dark"`
  - `paper_bgcolor` and `plot_bgcolor`: `"#0E1117"`
  - Height: `660px`
  - Disable range slider: `xaxis_rangeslider_visible=False`
  - Horizontal legend at top-right
  - Grid color: `"#1E222D"` on both axes

#### `fetch_news(company_name: str) -> list[dict]`

- **Cached** with `@st.cache_data(ttl=1800)` (30 min cache)
- Use `gnews.GNews(language="en", country="IN", max_results=5, period="7d")`
- Search query: `f"{company_name} stock"`
- If no results, retry with just `company_name`
- Return up to 5 articles
- Wrap in try/except, return empty list on failure, show `st.warning` with the error

#### `summarize_with_gemini(headlines: list[str], company: str, api_key: str) -> str`

- Import `google.generativeai as genai`
- Configure with the provided API key
- Use model `"gemini-2.0-flash"` (free tier)
- Build prompt:

  ```
  Read these recent news headlines for {company}:
  {bulleted list of headlines}

  Give me a 3-bullet-point summary explaining the fundamental or
  macroeconomic catalysts driving this stock's recent price action.
  Ignore noise, focus on business moves, volume drivers, or sector news.
  Keep each bullet concise (1-2 sentences).
  ```

- Return `response.text`
- On any exception, return `"⚠️ Gemini API error: {error}"`

#### `get_company_name(ticker: str) -> str`

- Use `yf.Ticker(ticker).info`
- Try keys in order: `"longName"`, `"shortName"`
- If all fail or exception, return the ticker string as fallback

---

### 6.4 Sidebar — "1% Risk Calculator"

- Title: `st.sidebar.title("📐 1% Risk Calculator")`
- Divider line
- Description text: _"Never risk more than 1% of your capital on a single trade."_
- Three `st.sidebar.number_input` fields:
  - `"Total Account Capital (₹)"` — min 0.0, default 100000.0, step 10000.0
  - `"Entry Price (₹)"` — min 0.01, default 100.0, step 0.5
  - `"Stop-Loss Price (₹)"` — min 0.01, default 95.0, step 0.5
- **Validation:** Entry Price must be greater than Stop-Loss Price
- **Calculation logic (strict):**
  ```python
  max_risk = capital * 0.01
  risk_per_share = entry_price - stop_loss
  shares_to_buy = math.floor(max_risk / risk_per_share)
  total_deployed = shares_to_buy * entry_price
  ```
- **Display** (only if `shares_to_buy > 0`):
  - Divider
  - Subheader: "📊 Position Size"
  - `st.sidebar.metric("Max Risk (1%)", f"₹{max_risk:,.2f}")`
  - `st.sidebar.metric("Risk Per Share", f"₹{risk_per_share:,.2f}")`
  - `st.sidebar.metric("Shares to Buy", f"{shares_to_buy:,}")`
  - `st.sidebar.metric("Capital Deployed", f"₹{total_deployed:,.2f}")`
  - If `total_deployed > capital`: show `st.sidebar.warning("⚠️ Position exceeds your total capital!")`
- If entry <= stop-loss: show `st.sidebar.error("Entry Price must be greater than Stop-Loss Price.")`

Also in sidebar, add a section for the **Gemini API Key**:

- `st.sidebar.divider()`
- `st.sidebar.subheader("🤖 AI Settings")`
- Try to read from `st.secrets["GEMINI_API_KEY"]` first
- If not found, show `st.sidebar.text_input("Gemini API Key", type="password")` with a help tooltip: _"Get a free key at aistudio.google.com"_

---

### 6.5 Main Area — Top Section

- `st.title("📈 Stock Market Analysis Dashboard")`
- Two columns for inputs:
  - **Column 1 (wider, ~70%):** `st.text_input` for Stock Symbol with placeholder `"e.g., RELIANCE, TCS, INFY"`
  - **Column 2 (~30%):** `st.selectbox` for Exchange: `["NSE", "BSE"]`
- Build the full ticker:
  - If exchange is `"NSE"`: append `".NS"` to the symbol
  - If exchange is `"BSE"`: append `".BO"` to the symbol
  - Always convert to uppercase and strip whitespace

---

### 6.6 Main Area — Data Fetch & Chart (only when symbol is entered)

When the user has entered a symbol:

1. Show `st.spinner("Fetching market data...")` while loading
2. Call `fetch_ohlcv(full_ticker)`
3. If data is empty, show `st.error` with a helpful message and `st.stop()`
4. Call `compute_indicators(df)`
5. Get the company name via `get_company_name(full_ticker)`

**Quick stats row** — display 4 metrics in columns:

- Current Price (last Close): formatted `₹{:,.2f}`
- Day Change: difference between last two closes, with delta shown
- 52-Week High: max of High column, formatted
- 52-Week Low: min of Low column, formatted

**Earnings Warning:**

- Call `check_earnings(full_ticker)`
- If earnings date found, render the `.earnings-warning` div via `st.markdown`:
  ```
  🚨 EARNINGS ALERT: {company_name} reports earnings on {date}!
  Trade with extreme caution — expect high volatility.
  ```

**Chart:**

- Call `build_chart(df, display_label)` where display_label is something like `"RELIANCE (NSE)"`
- Render with `st.plotly_chart(fig, use_container_width=True)`

---

### 6.7 Main Area — "The Story Engine" Section

- `st.subheader("📰 The Story Engine: Recent Catalysts")`
- Fetch news: `fetch_news(company_name)`
- If articles found:
  - Show each headline with its published date and source, and a link
  - Use an expander or clean list format
  - If Gemini API key is available:
    - Extract headline titles into a list
    - Call `summarize_with_gemini(headlines, company_name, api_key)`
    - Display the AI summary inside the `.story-section` styled div
    - Label it: "🤖 AI-Powered Catalyst Summary"
  - If no API key: show `st.info` telling the user to add their Gemini key in the sidebar
- If no articles: show `st.info("No recent news found.")`

---

### 6.8 Main Area — Footer

- `st.divider()`
- Small caption: `"Data sourced from Yahoo Finance. News via Google News. AI by Google Gemini. Built with Streamlit."`
- Another caption: `"⚠️ This tool is for educational purposes only. Not financial advice."`

---

## 7. Deployment Instructions (Include as README.md)

### File: `README.md`

```markdown
# 📈 Stock Market Analysis Dashboard

A free, full-featured stock analysis tool for Indian markets (NSE/BSE).

## Features

- Interactive candlestick charts with 50-DMA, 200-DMA, support/resistance
- Earnings date warnings
- 1% risk position sizing calculator
- AI-powered news catalyst summaries (via Google Gemini)

## Deploy to Streamlit Community Cloud (Free)

### Step 1: Push to GitHub

1. Create a new GitHub repository (public or private).
2. Upload all project files maintaining this structure:
```

your-repo/
├── app.py
├── requirements.txt
├── .streamlit/
│ └── config.toml
└── README.md

````
3. Commit and push.

### Step 2: Deploy on Streamlit Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **"New app"**.
3. Select your repository, branch (`main`), and main file (`app.py`).
4. Click **"Deploy"**.

### Step 3: (Optional) Add Gemini API Key as a Secret
1. Get a free API key from [aistudio.google.com](https://aistudio.google.com).
2. In your Streamlit Cloud app dashboard, go to **Settings → Secrets**.
3. Add:
```toml
GEMINI_API_KEY = "your-api-key-here"
````

4. Alternatively, paste the key into the sidebar input field at runtime.

### Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Disclaimer

This tool is for **educational purposes only**. It is not financial advice.

```

---

## 8. Key Implementation Notes for the Developer

1. **yfinance MultiIndex columns:** Since yfinance v0.2.37+, `yf.download()` returns MultiIndex columns when downloading a single ticker. Always check `isinstance(df.columns, pd.MultiIndex)` and flatten with `df.columns.get_level_values(0)`.

2. **Graceful degradation:** Every external call (yfinance, gnews, Gemini) must be wrapped in try/except. The dashboard should remain functional even if news or AI features fail.

3. **No network calls at import time.** All data fetching happens inside functions triggered by user interaction.

4. **The Gemini API key** should first be checked in `st.secrets` (for Streamlit Cloud deployment), and fall back to a sidebar password input for local use. Never hardcode the key.

5. **Currency:** All monetary values should be displayed with the ₹ symbol and Indian-style comma formatting (use `f"₹{value:,.2f}"`).

6. **pandas_ta import:** Just `import pandas_ta as ta` — it monkey-patches pandas but we use the standalone functions like `ta.sma()`.

7. **gnews quirk:** The `GNews` class period parameter uses strings like `"7d"`, `"1m"`. Use `"7d"` for recency. The `.get_news(query)` method returns a list of dicts with keys: `"title"`, `"description"`, `"published date"`, `"url"`, `"publisher"`.

8. **Chart responsiveness:** Always use `st.plotly_chart(fig, use_container_width=True)` so the chart fills the available width.

9. **All code goes in a single `app.py` file.** No multi-file architecture. Keep it simple for Streamlit Cloud deployment.

10. **Test with these tickers:** `RELIANCE.NS`, `TCS.NS`, `INFY.NS`, `HDFCBANK.NS` for NSE; `RELIANCE.BO` for BSE.
```
