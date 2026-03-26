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
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
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
    fig.update_layout(
        title=dict(text=f"{symbol} — Daily Chart (1 Year)", font=dict(size=20)),
        template="plotly_dark",
        paper_bgcolor="#0E1117",
        plot_bgcolor="#0E1117",
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
        return f"⚠️ Gemini API error: {e}"


def get_company_name(ticker: str) -> str:
    """Retrieve the company long/short name from yfinance, fallback to ticker."""
    try:
        info = yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or ticker
    except Exception:
        return ticker


# ===================================================================
# SIDEBAR — 1% Risk Calculator + Gemini Key
# ===================================================================
st.sidebar.title("📐 1% Risk Calculator")
st.sidebar.divider()
st.sidebar.markdown("_Never risk more than 1% of your capital on a single trade._")

capital = st.sidebar.number_input(
    "Total Account Capital (₹)", min_value=0.0, value=100000.0, step=10000.0
)
entry_price = st.sidebar.number_input(
    "Entry Price (₹)", min_value=0.01, value=100.0, step=0.5
)
stop_loss = st.sidebar.number_input(
    "Stop-Loss Price (₹)", min_value=0.01, value=95.0, step=0.5
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
# MAIN AREA — Top Section
# ===================================================================
st.title("📈 Stock Market Analysis Dashboard")

col_sym, col_exch = st.columns([7, 3])
with col_sym:
    raw_symbol = st.text_input(
        "Stock Symbol",
        value="",
        placeholder="e.g., RELIANCE, TCS, INFY",
    )
with col_exch:
    exchange = st.selectbox("Exchange", ["NSE", "BSE"])

if not raw_symbol:
    st.info("Enter a stock symbol above to get started.")
    st.stop()

ticker_suffix = ".NS" if exchange == "NSE" else ".BO"
full_ticker = raw_symbol.strip().upper() + ticker_suffix
display_label = f"{raw_symbol.strip().upper()} ({exchange})"

# ===================================================================
# MAIN AREA — Data Fetch & Chart
# ===================================================================
with st.spinner("Fetching market data..."):
    df = fetch_ohlcv(full_ticker)

if df.empty:
    st.error(
        f"No data found for **{full_ticker}**. "
        "Please verify the stock symbol and exchange selection."
    )
    st.stop()

df = compute_indicators(df)
company_name = get_company_name(full_ticker)

# --- Quick stats row ---
latest = df.iloc[-1]
prev_close = df["Close"].iloc[-2] if len(df) >= 2 else latest["Close"]
day_change = latest["Close"] - prev_close
week52_high = df["High"].max()
week52_low = df["Low"].min()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Current Price", f"₹{latest['Close']:,.2f}")
c2.metric("Day Change", f"₹{day_change:,.2f}", delta=f"{day_change:+,.2f}")
c3.metric("52-Week High", f"₹{week52_high:,.2f}")
c4.metric("52-Week Low", f"₹{week52_low:,.2f}")

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
st.subheader("📰 The Story Engine: Recent Catalysts")

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
