"""
Stock Market Analysis Dashboard
A free, full-featured stock analysis tool for Indian markets (NSE/BSE).
Tech: Streamlit · yfinance · pandas_ta · Plotly · GNews · Gemini Free Tier.
"""

import math
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from gnews import GNews
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Page configuration — MUST be the very first Streamlit command
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Stock Market Analysis Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# INITIALIZE SESSION STATE
# ---------------------------------------------------------------------------
if "entry_price_key" not in st.session_state:
    st.session_state["entry_price_key"] = 100.0
if "stop_loss_key" not in st.session_state:
    st.session_state["stop_loss_key"] = 95.0
if "capital_key" not in st.session_state:
    st.session_state["capital_key"] = 100000.0
if "sync_ticker" not in st.session_state:
    st.session_state["sync_ticker"] = None
if "last_search_query" not in st.session_state:
    st.session_state["last_search_query"] = ""
if "search_results" not in st.session_state:
    st.session_state["search_results"] = []
if "capital_ext" not in st.session_state:
    st.session_state["capital_ext"] = 100000.0
if "theme_light" not in st.session_state:
    st.session_state["theme_light"] = False

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    header {visibility: hidden;}
    footer {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    .block-container {
        padding-top: 1.5rem;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: bold;
    }
    .earnings-warning {
        background: linear-gradient(135deg, #ff4b4b, #cc0000);
        color: white;
        font-weight: bold;
        text-align: center;
        padding: 1rem 1.5rem;
        border-radius: 0.75rem;
        margin-bottom: 1rem;
        font-size: 1.15rem;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%   { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.7); }
        50%  { box-shadow: 0 0 20px 10px rgba(255, 75, 75, 0.25); }
        100% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0); }
    }
    .story-section {
        background-color: #1A1D23;
        border-left: 4px solid #00D4AA;
        padding: 1.25rem;
        border-radius: 0.5rem;
        margin-top: 0.5rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ===================================================================
# HELPER FUNCTIONS
# ===================================================================


@st.cache_data(ttl=900)
def fetch_ohlcv(ticker: str) -> pd.DataFrame:
    """Download 1 year of daily OHLCV data via yfinance."""
    try:
        end = datetime.today()
        start = end - timedelta(days=365)
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return pd.DataFrame()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add 50/200 SMA and pivot-based support/resistance."""
    df = df.copy()
    df["SMA_50"] = ta.sma(df["Close"], length=50)
    df["SMA_200"] = ta.sma(df["Close"], length=200)

    # Momentum/Trend indicators
    adx_df = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    if adx_df is not None and not adx_df.empty:
        df["ADX"] = adx_df.iloc[:, 0]
    else:
        df["ADX"] = 0
    df["Vol_20SMA"] = ta.sma(df["Volume"], length=20).fillna(1)

    recent = df.tail(20)
    pp_high = recent["High"].max()
    pp_low = recent["Low"].min()
    pp_close = recent["Close"].iloc[-1]

    pivot = (pp_high + pp_low + pp_close) / 3
    support_1 = 2 * pivot - pp_high
    resistance_1 = 2 * pivot - pp_low

    df["Pivot"] = pivot
    df["Support_1"] = support_1
    df["Resistance_1"] = resistance_1

    return df


def check_earnings(ticker: str) -> Optional[datetime]:
    """Return the next earnings date if within 7 days, else None."""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is None:
            return None

        earnings_date_raw = None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed:
                earnings_date_raw = ed[0] if isinstance(ed, list) else ed
        elif isinstance(cal, pd.DataFrame):
            if "Earnings Date" in cal.index:
                earnings_date_raw = cal.loc["Earnings Date"].iloc[0]
            elif "Earnings Date" in cal.columns:
                earnings_date_raw = cal["Earnings Date"].iloc[0]

        if earnings_date_raw is None:
            return None

        dt = pd.Timestamp(earnings_date_raw).date()
        days_away = (dt - datetime.today().date()).days
        if 0 <= days_away <= 7:
            return dt
        return None
    except Exception:
        return None


def build_chart(df: pd.DataFrame, symbol: str) -> go.Figure:
    """Build a candlestick + volume chart with overlays."""
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.78, 0.22],
    )

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="OHLC",
            increasing_line_color="#00D4AA",
            decreasing_line_color="#FF4B4B",
        ),
        row=1,
        col=1,
    )

    # 50-DMA
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["SMA_50"],
            mode="lines",
            name="50 DMA",
            line=dict(color="#FFD700", width=1.5),
        ),
        row=1,
        col=1,
    )

    # 200-DMA
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["SMA_200"],
            mode="lines",
            name="200 DMA",
            line=dict(color="#1E90FF", width=1.5),
        ),
        row=1,
        col=1,
    )

    # Support / Resistance / Pivot horizontal lines
    support_val = df["Support_1"].iloc[-1]
    resistance_val = df["Resistance_1"].iloc[-1]
    pivot_val = df["Pivot"].iloc[-1]

    fig.add_hline(
        y=support_val,
        line_dash="dot",
        line_color="#FF6B6B",
        annotation_text=f"Support ₹{support_val:,.2f}",
        row=1,
        col=1,
    )
    fig.add_hline(
        y=resistance_val,
        line_dash="dot",
        line_color="#4ECDC4",
        annotation_text=f"Resistance ₹{resistance_val:,.2f}",
        row=1,
        col=1,
    )
    fig.add_hline(
        y=pivot_val,
        line_dash="dot",
        line_color="#AAAAAA",
        annotation_text=f"Pivot ₹{pivot_val:,.2f}",
        row=1,
        col=1,
    )

    # Volume bars
    colors = ["#00D4AA" if c >= o else "#FF4B4B" for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["Volume"],
            marker_color=colors,
            name="Volume",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Layout
    is_light = st.session_state.get("theme_light", False)
    bg_color = "#FFFFFF" if is_light else "#0E1117"
    text_color = "#000000" if is_light else "white"

    fig.update_layout(
        title=dict(text=f"{symbol} — Daily Chart (1 Year)", font=dict(size=20, color=text_color)),
        template="plotly_white" if is_light else "plotly_dark",
        paper_bgcolor=bg_color,
        plot_bgcolor=bg_color,
        font=dict(color=text_color),
        height=660,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=30, t=60, b=30),
    )
    fig.update_xaxes(gridcolor="#1E222D")
    fig.update_yaxes(gridcolor="#1E222D")
    fig.update_yaxes(title_text="Price (₹)", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    return fig


@st.cache_data(ttl=1800)
def fetch_news(company_name: str) -> list[dict]:
    """Fetch top 5 recent news articles via GNews."""
    try:
        gn = GNews(language="en", country="IN", max_results=5, period="7d")
        articles = gn.get_news(f"{company_name} stock")
        if not articles:
            articles = gn.get_news(company_name)
        return articles[:5] if articles else []
    except Exception as e:
        st.warning(f"News fetch error: {e}")
        return []


def summarize_with_gemini(headlines: list[str], company: str, api_key: str) -> str:
    """Send headlines to Gemini and return a 3-bullet catalyst summary."""
    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        bullet_list = "\n".join(f"- {h}" for h in headlines)
        prompt = (
            f"Read these recent news headlines for {company}:\n\n"
            f"{bullet_list}\n\n"
            "Give me a 3-bullet-point summary explaining the fundamental or "
            "macroeconomic catalysts driving this stock's recent price action. "
            "Ignore noise, focus on business moves, volume drivers, or sector news. "
            "Keep each bullet concise (1-2 sentences)."
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "quota" in err_str or "exhausted" in err_str:
            return "⚠️ AI Summary currently unavailable: API Quota Exceeded."
        return f"⚠️ Gemini API error: {e}"


def get_company_name(ticker: str) -> str:
    """Retrieve the company long/short name from yfinance, fallback to ticker."""
    try:
        info = yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or ticker
    except Exception:
        return ticker

# ===================================================================
# INITIALIZE SESSION STATE
# ===================================================================
# INITIALIZE SESSION STATE (Moved to top level file)

# ===================================================================
# TOP SECTION — Search & Ticker Selection
# ===================================================================
st.title("📈 Stock Market Analysis Dashboard")

col_sym, col_tick = st.columns([7, 3])
with col_sym:
    search_query = st.text_input(
        "Search Company Name or Ticker",
        value="",
        placeholder="e.g., Narmada, RELIANCE, TCS",
        key="search_input",
    )

if not search_query:
    st.info("Enter a stock symbol to get started.")
    st.stop()

search_term = search_query.strip()
if search_term != st.session_state["last_search_query"]:
    st.session_state["last_search_query"] = search_term
    st.session_state["search_results"] = []
    try:
        if search_term.upper().endswith(".NS") or search_term.upper().endswith(".BO"):
             st.session_state["search_results"] = [search_term.upper()]
        else:
            s_res = yf.Search(search_term, max_results=5).quotes
            options = []
            for q in s_res:
                sym = q.get('symbol', '')
                if sym.endswith(".NS") or sym.endswith(".BO"):
                    options.append(sym)
                else:
                    options.append(sym + ".NS")
            if not options:
                options = [search_term.upper() + ".NS"]
                
            # Prioritize NSE (.NS) tickers over BSE (.BO)
            options.sort(key=lambda x: 0 if x.endswith(".NS") else 1)
            
            st.session_state["search_results"] = options
    except Exception:
        st.session_state["search_results"] = [search_term.upper() + ".NS"]

options = st.session_state["search_results"]

with col_tick:
    if len(options) > 0:
        full_ticker = st.selectbox("Select Matching Ticker", options=options, key="ticker_select")
    else:
        full_ticker = search_term.upper() + ".NS"

display_label = full_ticker

# ===================================================================
# FETCH DATA & SILENT SYNC
# ===================================================================
with st.spinner("Fetching market data..."):
    df = fetch_ohlcv(full_ticker)

if df.empty or len(df) < 50:
    st.info(f"Not enough market data found for **{full_ticker}**. Please verify the symbol.")
    st.stop()

df = compute_indicators(df)
company_name = get_company_name(full_ticker)

try:
    latest = df.iloc[-1]
    prev_close = df["Close"].iloc[-2] if len(df) >= 2 else latest["Close"]
    day_change = latest["Close"] - prev_close
    day_change_pct = (day_change / prev_close) * 100
    support_val = df["Support_1"].iloc[-1]
    resistance_val = df["Resistance_1"].iloc[-1]
    week52_high = df["High"].max()
    week52_low = df["Low"].min()
except (IndexError, KeyError) as e:
    st.info(f"Market structure algorithms currently unavailable for **{full_ticker}**.")
    st.stop()

if st.session_state["sync_ticker"] != full_ticker:
    st.session_state["sync_ticker"] = full_ticker
    st.session_state["entry_price_key"] = float(latest["Close"])
    st.session_state["stop_loss_key"] = float(support_val)
    # Silent Sync: Values update in session_state before sidebar renders below

# ===================================================================
# SIDEBAR — 1% Risk Calculator + Gemini Key + Batch Processor
# ===================================================================
if "theme_light" not in st.session_state:
    st.session_state["theme_light"] = False
light_mode = st.sidebar.toggle("☀️ Light Mode", value=st.session_state["theme_light"], key="theme_toggle")
if light_mode != st.session_state["theme_light"]:
    st.session_state["theme_light"] = light_mode
    import os
    os.makedirs(".streamlit", exist_ok=True)
    with open(".streamlit/config.toml", "w") as f:
        f.write(f'[theme]\nbase="{"light" if light_mode else "dark"}"\n')
    st.rerun()

st.sidebar.title("📐 1% Risk Calculator")
st.sidebar.divider()
st.sidebar.markdown("_Never risk more than 1% of your capital on a single trade._")

capital = st.sidebar.number_input(
    "Total Account Capital (₹)", min_value=0.0, step=10000.0, key="capital_key"
)
st.session_state["capital_ext"] = capital

entry_price = st.sidebar.number_input(
    "Entry Price (₹)", min_value=0.01, step=0.5, key="entry_price_key"
)
stop_loss = st.sidebar.number_input(
    "Stop-Loss Price (₹)", min_value=0.01, step=0.5, key="stop_loss_key"
)

if entry_price > stop_loss:
    max_risk = capital * 0.01
    risk_per_share = entry_price - stop_loss
    shares_to_buy = math.floor(max_risk / risk_per_share)
    total_deployed = shares_to_buy * entry_price

    if shares_to_buy > 0:
        st.sidebar.divider()
        st.sidebar.subheader("📊 Position Size")
        st.sidebar.metric("Max Risk (1%)", f"₹{max_risk:,.2f}")
        st.sidebar.metric("Risk Per Share", f"₹{risk_per_share:,.2f}")
        st.sidebar.metric("Shares to Buy", f"{shares_to_buy:,}")
        st.sidebar.metric("Capital Deployed", f"₹{total_deployed:,.2f}")
        if total_deployed > capital:
            st.sidebar.warning("⚠️ Position exceeds your total capital!")
else:
    st.sidebar.error("Entry Price must be greater than Stop-Loss Price.")

# Batch Processor (Watchlist Upload)
st.sidebar.divider()
st.sidebar.subheader("📂 Batch Processor")
st.sidebar.markdown("_Upload a Screener.in CSV to rank setups._")
watchlist_file = st.sidebar.file_uploader("Upload CSV", type=["csv"])
if watchlist_file is not None:
    try:
        w_df = pd.read_csv(watchlist_file)
        w_df.columns = [str(c).strip() for c in w_df.columns]
        lower_cols = [c.lower() for c in w_df.columns]
        ticker_col = None
        for c, lc in zip(w_df.columns, lower_cols):
            if lc in ["ticker", "symbol", "name"]:
                ticker_col = c
                break
        
        if ticker_col is not None:
            if st.sidebar.button("Run Batch Scan"):
                with st.spinner("Scanning Watchlist (Top 50)..."):
                    results = []
                    tickers = w_df[ticker_col].dropna().astype(str).unique()[:50]
                    for t in tickers:
                        if ticker_col.lower() == "name":
                            try:
                                s_res = yf.Search(t, max_results=1).quotes
                                if s_res:
                                    sym = s_res[0].get('symbol', '')
                                    t_sym = sym if ".NS" in sym or ".BO" in sym else sym + ".NS"
                                else:
                                    t_sym = t.strip().upper() + ".NS"
                            except Exception:
                                t_sym = t.strip().upper() + ".NS"
                        else:
                            t_sym = t.strip().upper()
                            if not t_sym.endswith(".NS") and not t_sym.endswith(".BO"):
                                t_sym += ".NS"
                                
                        batch_ticker = t_sym
                        b_df = fetch_ohlcv(batch_ticker)
                        if not b_df.empty and len(b_df) > 50:
                            b_df = compute_indicators(b_df)
                            try:
                                b_close = b_df["Close"].iloc[-1]
                                b_sup1 = b_df["Support_1"].iloc[-1]
                                b_res1 = b_df["Resistance_1"].iloc[-1]
                                
                                risk_pct = ((b_close - b_sup1) / b_close) * 100
                                if b_res1 > b_sup1:
                                    raw_s = ((b_res1 - b_close) / (b_res1 - b_sup1)) * 100
                                    b_score = max(0, min(100, int(raw_s)))
                                else:
                                    b_score = 50
                                    
                                is_buy = (b_sup1 <= b_close <= b_sup1 * 1.05)
                                    
                                results.append({
                                    "Select": False,
                                    "Ticker": t_sym,
                                    "Price": round(b_close, 2),
                                    "Support1": round(b_sup1, 2),
                                    "Risk to Stop %": round(risk_pct, 2),
                                    "Safety Score": b_score,
                                    "Buyable": "🟩 BUYABLE" if is_buy else "⬛ NO"
                                })
                            except (IndexError, KeyError):
                                pass
                    if results:
                        res_df = pd.DataFrame(results).sort_values("Risk to Stop %")
                        st.session_state["batch_results"] = res_df
                        st.sidebar.success("Scan Complete! View results below.")
        else:
            st.sidebar.error("Could not find 'Name', 'Ticker', or 'Symbol' column in CSV.")
    except Exception as e:
        st.sidebar.error(f"Error processing CSV: {e}")

# Gemini API Key
st.sidebar.divider()
st.sidebar.subheader("🤖 AI Settings")

gemini_key: str | None = None
try:
    gemini_key = st.secrets["GEMINI_API_KEY"]
    st.sidebar.success("Gemini key loaded from secrets.")
except (KeyError, FileNotFoundError):
    gemini_key = st.sidebar.text_input(
        "Gemini API Key",
        type="password",
        help="Get a free key at aistudio.google.com",
    )

# ===================================================================
# MAIN AREA — Visuals
# ===================================================================

# --- Batch Results View ---
if "batch_results" in st.session_state:
    st.markdown("---")
    st.subheader("🔥 Watchlist Batch Results")
    edited_df = st.data_editor(
        st.session_state["batch_results"],
        hide_index=True,
        use_container_width=True
    )
    st.session_state["batch_results"] = edited_df
    
    selected_rows = edited_df[edited_df["Select"] == True]
    if not selected_rows.empty:
        cap = st.session_state.get("capital_ext", 100000.0)
        export_list = []
        for _, row in selected_rows.iterrows():
            ep = row["Price"]
            sl = row["Support1"]
            shares = math.floor((cap * 0.01) / (ep - sl)) if ep > sl else 0
            export_list.append({
                "Ticker": row["Ticker"],
                "Entry Price": ep,
                "Stop Loss": sl,
                "Shares to Buy": shares
            })
            
        st.download_button(
            label="⬇️ Download Trade Plan",
            data=pd.DataFrame(export_list).to_csv(index=False),
            file_name="Batch_Trade_Plan.csv",
            mime="text/csv",
        )

# --- Visual Scoring (Gauge) & Metrics ---
# --- Metrics Row ---
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Current Price", f"₹{latest['Close']:,.2f}")
c2.metric("Day Change %", f"{day_change_pct:,.2f}%", delta=f"{day_change:+,.2f}")
c3.metric("Support (S1)", f"₹{support_val:,.2f}")
c4.metric("Resistance (R1)", f"₹{resistance_val:,.2f}")
c5.metric("52W High", f"₹{week52_high:,.2f}")
c6.metric("52W Low", f"₹{week52_low:,.2f}")

# --- Visual Scoring (Gauge & Momentum) ---
c_gauge, c_mom = st.columns([1, 1])

is_light = st.session_state.get("theme_light", False)
text_clr = "black" if is_light else "white"

with c_gauge:
    current_price = latest["Close"]
    
    if resistance_val > support_val:
        # Lower score means closer to support (safer entry)
        raw_score = ((current_price - support_val) / (resistance_val - support_val)) * 100
        safe_score = max(0, min(100, int(raw_score)))
    else:
        safe_score = 50

    gauge_fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=safe_score,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "Entry Safety Gauge", 'font': {'size': 20, 'color': text_clr}},
        gauge={
            'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': text_clr},
            'bar': {'color': "#00D4AA"},
            'bgcolor': "rgba(0,0,0,0)",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, 30], 'color': 'rgba(0, 212, 170, 0.3)'},
                {'range': [30, 60], 'color': 'rgba(255, 215, 0, 0.3)'},
                {'range': [60, 100], 'color': 'rgba(255, 75, 75, 0.3)'}],
        }
    ))
    gauge_fig.update_layout(height=260, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={'color': text_clr})
    st.plotly_chart(gauge_fig, use_container_width=True)
    st.markdown("<p style='text-align: center; font-size: 0.9em; margin-top: -10px;'><span style='color: #00FF00;'>0-30: Safe Entry</span> | <span style='color: #FFFF00;'>31-60: Fair</span> | <span style='color: #FF0000;'>61-100: Overextended</span></p>", unsafe_allow_html=True)

with c_mom:
    vol_today = latest.get("Volume", 1)
    vol_20sma = latest.get("Vol_20SMA", 1)
    if pd.isna(vol_20sma) or vol_20sma == 0:
        vol_20sma = 1
    vol_ratio = vol_today / vol_20sma
    
    adx_val = latest.get("ADX", 0)
    if pd.isna(adx_val):
        adx_val = 0
        
    adx_fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=adx_val,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "Trend Strength (ADX)", 'font': {'size': 20, 'color': text_clr}},
        gauge={
            'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': text_clr},
            'bar': {'color': "#00D4AA"},
            'bgcolor': "rgba(0,0,0,0)",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, 25], 'color': 'gray'},
                {'range': [25, 50], 'color': 'green'},
                {'range': [50, 100], 'color': 'darkgreen'}],
        }
    ))
    adx_fig.update_layout(height=260, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={'color': text_clr})
    st.plotly_chart(adx_fig, use_container_width=True)
    
    st.markdown("<p style='text-align: center; font-size: 0.9em; margin-top: -10px;'><span style='color: gray;'>0-25: Weak</span> | <span style='color: green;'>25-50: Strong</span> | <span style='color: darkgreen;'>50-100: Very Strong</span></p>", unsafe_allow_html=True)
    
    vol_text = f"📈 **Volume:** {vol_ratio:.2f}x Avg"
    if vol_ratio > 2.0:
        vol_text += " <span style='color: #00FF00;'>(Institutional Surge)</span>"
    st.markdown(f"<p style='text-align: center; font-size: 1.1em; margin-top: 10px;'>{vol_text}</p>", unsafe_allow_html=True)

# --- Earnings Warning ---
earnings_date = check_earnings(full_ticker)
if earnings_date:
    formatted_date = earnings_date.strftime("%d %b %Y")
    st.markdown(
        f'<div class="earnings-warning">'
        f"🚨 EARNINGS ALERT: {company_name} reports earnings on {formatted_date}! "
        f"Trade with extreme caution — expect high volatility."
        f"</div>",
        unsafe_allow_html=True,
    )

# --- Chart ---
fig = build_chart(df, display_label)
st.plotly_chart(fig, use_container_width=True)

# ===================================================================
# MAIN AREA — The Story Engine
# ===================================================================
st.subheader("📰 Recent Catalysts")

with st.spinner("Fetching latest news..."):
    articles = fetch_news(company_name)

if articles:
    for i, art in enumerate(articles, 1):
        title = art.get("title", "No title")
        publisher = art.get("publisher", {})
        pub_name = publisher.get("title", "") if isinstance(publisher, dict) else str(publisher)
        pub_date = art.get("published date", "")
        url = art.get("url", "")

        link = f"[{title}]({url})" if url else title
        st.markdown(f"**{i}.** {link}  \n<sub>{pub_name} · {pub_date}</sub>", unsafe_allow_html=True)

    # AI Summary
    headlines = [art.get("title", "") for art in articles if art.get("title")]
    if gemini_key and headlines:
        st.markdown("---")
        with st.spinner("Generating AI catalyst summary..."):
            summary = summarize_with_gemini(headlines, company_name, gemini_key)

        st.markdown("**🤖 AI-Powered Catalyst Summary**")
        st.markdown(
            f'<div class="story-section">{summary}</div>',
            unsafe_allow_html=True,
        )
    elif not gemini_key:
        st.info("Add your free Gemini API key in the sidebar to enable AI-powered catalyst summaries.")
else:
    st.info("No recent news found.")

# ===================================================================
# Footer
# ===================================================================
st.divider()
st.caption("Data sourced from Yahoo Finance. News via Google News. AI by Google Gemini. Built with Streamlit.")
st.caption("⚠️ This tool is for educational purposes only. Not financial advice.")
