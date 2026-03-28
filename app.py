"""
Stock Market Analysis Dashboard
A free, full-featured stock analysis tool for Indian markets (NSE/BSE).
Tech: Streamlit · yfinance · pandas_ta · Plotly · GNews · Gemini Free Tier.
"""

import io
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
if "capital_key" not in st.session_state or st.session_state["capital_key"] == 0.0:
    st.session_state["capital_key"] = 300000.0
if "sync_ticker" not in st.session_state:
    st.session_state["sync_ticker"] = None
if "last_search_query" not in st.session_state:
    st.session_state["last_search_query"] = ""
if "search_results" not in st.session_state:
    st.session_state["search_results"] = []
if "capital_ext" not in st.session_state or st.session_state["capital_ext"] == 0.0:
    st.session_state["capital_ext"] = 300000.0

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    header[data-testid="stHeader"] {background-color: transparent !important;}
    [data-testid="stToolbar"] {display: none !important;}
    [data-testid="collapsedControl"] {
        visibility: visible !important;
        display: flex !important;
        z-index: 9999 !important;
        color: #00D4AA !important;
    }
    footer {visibility: hidden;}
    #MainMenu {visibility: hidden;}
    .block-container {
        padding-top: 1.5rem;
    }
    div[data-baseweb="input"] > div:focus-within {
        border-color: #00D4AA !important;
        box-shadow: 0 0 0 1px #00D4AA !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: bold;
    }
    .icon-3d {
        display: inline-block;
        transform: scale(1.2);
        text-shadow: 2px 2px 4px rgba(0,0,0,0.4);
        margin-right: 0.2rem;
    }
    .analyst-badge {
        font-size: 0.9rem;
        background-color: #333;
        color: #fff;
        padding: 0.2rem 0.5rem;
        border-radius: 0.5rem;
        vertical-align: middle;
        margin-left: 10px;
        opacity: 0.8;
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
    try:
        end = datetime.today()
        start = end - timedelta(days=365)
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        
        if df.empty:
            return pd.DataFrame()

        # Fix MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # CRITICAL FIX: Drop duplicate dates from Yahoo Finance
        df = df.loc[~df.index.duplicated(keep='first')].copy()
        
        return df
    except Exception:
        return pd.DataFrame()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    df = df.copy()
    # Ensure index is unique and sorted before TA calculations
    df = df.loc[~df.index.duplicated(keep='first')].sort_index()
    
    df["SMA_50"] = ta.sma(df["Close"], length=50)
    df["SMA_200"] = ta.sma(df["Close"], length=200)

    # Momentum/Trend indicators
    adx_df = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    if adx_df is not None and not adx_df.empty:
        df["ADX"] = adx_df.iloc[:, 0]
    else:
        df["ADX"] = 0
    
    vol_sma = ta.sma(df["Volume"], length=20)
    if vol_sma is not None and not vol_sma.empty:
        df["Vol_20SMA"] = vol_sma.fillna(1)
    else:
        df["Vol_20SMA"] = 1

    previous_window = df.iloc[-21:-1]
    pp_high = previous_window["High"].max()
    pp_low = previous_window["Low"].min()
    pp_close = previous_window["Close"].iloc[-1]

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
    bg_color = "#0E1117"
    text_color = "white"

    fig.update_layout(
        title=dict(text=f"{symbol} — Daily Chart (1 Year)", font=dict(size=20, color=text_color)),
        template="plotly_dark",
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


@st.cache_data(ttl=3600)
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


def get_analyst_rating(ticker: str) -> Optional[str]:
    """Retrieve the recommendation key from yfinance."""
    try:
        info = yf.Ticker(ticker).info
        return info.get("recommendationKey")
    except Exception:
        return None


def render_control_center():
    st.markdown("---")
    st.markdown("<h2>🛠️ Trading Tools & Batch Scanner</h2>", unsafe_allow_html=True)
    col_calc, col_batch = st.columns(2)
    
    with col_calc:
        st.subheader("📐 1% Risk Calculator")
        st.markdown("_Never risk more than 1% of your capital on a single trade._")

        capital = st.number_input(
            "Total Account Capital (₹)", min_value=0.0, step=10000.0, key="capital_key"
        )
        st.session_state["capital_ext"] = capital

        entry_price = st.number_input(
            "Entry Price (₹)", min_value=0.01, step=0.5, key="entry_price_key"
        )
        stop_loss = st.number_input(
            "Stop-Loss Price (₹)", min_value=0.01, step=0.5, key="stop_loss_key"
        )

        if entry_price > stop_loss:
            max_risk = capital * 0.01
            risk_per_share = entry_price - stop_loss
            shares_to_buy = math.floor(max_risk / risk_per_share)
            total_deployed = shares_to_buy * entry_price

            if shares_to_buy > 0:
                st.divider()
                st.subheader("📊 Position Size")
                st.metric("Max Risk (1%)", f"₹{max_risk:,.2f}")
                st.metric("Risk Per Share", f"₹{risk_per_share:,.2f}")
                st.metric("Shares to Buy", f"{shares_to_buy:,}")
                st.metric("Capital Deployed", f"₹{total_deployed:,.2f}")
                if total_deployed > capital:
                    st.warning("⚠️ Position exceeds your total capital!")
        else:
            st.error("Entry Price must be greater than Stop-Loss Price.")

    with col_batch:
        st.subheader("📂 Batch Processor")
        tab1, tab2 = st.tabs(["📝 Quick Paste", "📁 Upload File"])
        
        w_df = None
        run_scan = False
        
        with tab1:
            st.markdown("_Highlight web tables, press Ctrl+C, and paste below._")
            pasted_data = st.text_area("Paste Web Table Here:", height=100, placeholder="Paste data here...")
            if st.button("Run Paste Scan", type="primary"):
                if pasted_data:
                    try:
                        # Read as raw data without headers to prevent immediate Pandas crash
                        raw_data = pd.read_csv(io.StringIO(pasted_data), sep='\t', header=None)
                        if not raw_data.empty:
                            # 1. Take the first row as headers
                            header_row = raw_data.iloc[0].astype(str).tolist()
                            # 2. Generate unique names for every column manually
                            unique_headers = []
                            seen = {}
                            for h in header_row:
                                h_clean = h.strip() if h.strip() != "" else "Unnamed"
                                if h_clean in seen:
                                    seen[h_clean] += 1
                                    unique_headers.append(f"{h_clean}_{seen[h_clean]}")
                                else:
                                    seen[h_clean] = 0
                                    unique_headers.append(h_clean)
                            
                            # 3. Reconstruct DF with data only (row 1 onwards) and clean headers
                            w_df = raw_data.iloc[1:].copy()
                            w_df.columns = unique_headers
                            w_df = w_df.reset_index(drop=True)
                            run_scan = True
                    except Exception as e:
                        st.error(f"Format error: {e}")
                else:
                    st.warning("Please paste data first.")
                    
        with tab2:
            watchlist_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx"])
            if st.button("Run File Scan"):
                if watchlist_file is not None:
                    try:
                        if watchlist_file.name.endswith('.csv'):
                            raw_data = pd.read_csv(watchlist_file, header=None)
                        else:
                            raw_data = pd.read_excel(watchlist_file, header=None)
                        
                        header_row = raw_data.iloc[0].astype(str).tolist()
                        unique_headers = []
                        seen = {}
                        for h in header_row:
                            h_clean = h.strip() if h.strip() != "" else "Unnamed"
                            if h_clean in seen:
                                seen[h_clean] += 1
                                unique_headers.append(f"{h_clean}_{seen[h_clean]}")
                            else:
                                seen[h_clean] = 0
                                unique_headers.append(h_clean)
                        
                        w_df = raw_data.iloc[1:].copy()
                        w_df.columns = unique_headers
                        w_df = w_df.reset_index(drop=True)
                        run_scan = True
                    except Exception as e:
                        st.error(f"File reading error: {e}")
                else:
                    st.warning("Please upload a file first.")

        if run_scan and w_df is not None:
            try:
                # Find ticker column
                ticker_col = next((c for c in w_df.columns if c.lower() in ["ticker", "symbol", "name"]), None)
                
                if ticker_col:
                    tickers_to_scan = w_df[ticker_col].dropna().astype(str).unique().tolist()[:50]

                    with st.spinner("Scanning Watchlist (Top 50)..."):
                        results = []
                        for t in tickers_to_scan:
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
                            
                            if b_df.empty or len(b_df) < 50:
                                continue
                                
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

                                # Master Algorithmic Rating for Batch
                                m_score = 0
                                if b_score <= 30: m_score += 2
                                elif b_score <= 60: m_score += 1
                                
                                b_adx = b_df["ADX"].iloc[-1] if not pd.isna(b_df["ADX"].iloc[-1]) else 0
                                if b_adx >= 50: m_score += 2
                                elif b_adx >= 25: m_score += 1
                                
                                b_vol = b_df["Volume"].iloc[-1]
                                b_vol20 = b_df["Vol_20SMA"].iloc[-1]
                                if pd.isna(b_vol20) or b_vol20 == 0: b_vol20 = 1
                                v_ratio = b_vol / b_vol20
                                
                                if v_ratio >= 1.5: m_score += 2
                                elif v_ratio >= 1.0: m_score += 1
                                
                                if m_score >= 5: m_rating = "🟢 STRONG BUY"
                                elif m_score >= 3: m_rating = "🔵 MODERATE BUY"
                                elif m_score >= 1: m_rating = "🟡 HOLD"
                                else: m_rating = "🔴 AVOID"

                                results.append({
                                    "Select": False,
                                    "Ticker": t_sym,
                                    "Price": round(b_close, 2),
                                    "Support1": round(b_sup1, 2),
                                    "Risk to Stop %": round(risk_pct, 2),
                                    "Safety Score": b_score,
                                    "Buyable": "🟩 BUYABLE" if is_buy else "⬛ NO",
                                    "Master Rating": m_rating
                                })
                            except (IndexError, KeyError):
                                pass
                        if results:
                            res_df = pd.DataFrame(results).sort_values("Risk to Stop %")
                            st.session_state["batch_results"] = res_df
                            st.success("Scan Complete! View results below.")
                else:
                    st.error("Could not find 'Name', 'Ticker', or 'Symbol' column in input data.")
            except Exception as e:
                st.error(f"Error processing data: {e}")

        # Gemini API Key
        st.divider()
        st.subheader("🤖 AI Settings")

        api_key = None
        try:
            api_key = st.secrets["GEMINI_API_KEY"]
            st.success("Gemini key loaded from secrets.")
        except (KeyError, FileNotFoundError):
            api_key = st.text_input(
                "Gemini API Key",
                type="password",
                help="Get a free key at aistudio.google.com",
            )
        st.session_state["gemini_key"] = api_key


# ===================================================================
# INITIALIZE SESSION STATE
# ===================================================================
# INITIALIZE SESSION STATE (Moved to top level file)

# ===================================================================
# TOP SECTION — Search & Ticker Selection
# ===================================================================
st.markdown("<h1><span class='icon-3d'>📈</span> Stock Market Analysis Dashboard</h1>", unsafe_allow_html=True)

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
    render_control_center() # Render tools when empty
    st.stop() # Stop the heavy chart fetching

search_term = search_query.strip()
if search_term != st.session_state["last_search_query"]:
    st.session_state["last_search_query"] = search_term
    st.session_state["search_results"] = []
    try:
        if search_term.upper().endswith(".NS") or search_term.upper().endswith(".BO"):
             st.session_state["search_results"] = [search_term.upper()]
        else:
            s_res = yf.Search(search_term, max_results=8).quotes
            options = []
            for q in s_res:
                sym = q.get('symbol', '')
                exch = str(q.get('exchange', '')).upper()
                if not sym: continue
                if sym.endswith(".NS") or sym.endswith(".BO"):
                    options.append(sym)
                elif exch in ["NSI", "NSE"]:
                    options.append(sym + ".NS")
                elif exch in ["BSE", "BOM"]:
                    options.append(sym + ".BO")
                else: 
                    options.append(sym + ".NS")
            if not options:
                options = [search_term.upper() + ".NS"]
                
            # Prioritize NSE (.NS) tickers
            options.sort(key=lambda x: 0 if x.endswith(".NS") else 1)
            
            # Remove any duplicates while preserving order
            options = list(dict.fromkeys(options))
            
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
    with st.spinner("Fetching fundamentals..."):
        tk = yf.Ticker(full_ticker)
        info = tk.info
        
        # --- ROCE Logic ---
        roce = info.get("returnOnCapitalEmployed") or info.get("returnOnEquity") or info.get("returnOnAssets", 0)
        
        if not roce or roce == 0:
            try:
                inc = tk.income_stmt
                bs = tk.balance_sheet
                if not inc.empty and not bs.empty:
                    ebit = inc.loc['EBIT'].iloc[0] if 'EBIT' in inc.index else inc.loc['Operating Income'].iloc[0]
                    ta = bs.loc['Total Assets'].iloc[0]
                    cl = bs.loc['Current Liabilities'].iloc[0] if 'Current Liabilities' in bs.index else 0
                    ce = ta - cl
                    roce = (ebit / ce) if ce > 0 else 0
            except:
                pass

        if roce is not None:
            roce = float(roce)
            if -2.0 < roce < 2.0 and roce != 0.0: roce *= 100
        else:
            roce = 0.0

        # --- Debt to Equity Logic ---
        debt_to_equity = info.get("debtToEquity", 0)
        
        if not debt_to_equity or debt_to_equity == 0:
            try:
                bs = tk.balance_sheet
                if not bs.empty:
                    td = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0
                    te = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 1
                    debt_to_equity = td / te
            except:
                pass
                
        if debt_to_equity is not None:
            debt_to_equity = float(debt_to_equity)
            if debt_to_equity > 5.0: debt_to_equity /= 100
        else:
            debt_to_equity = 0.0
except Exception:
    roce = 0.0
    debt_to_equity = 0.0

analyst_rec = get_analyst_rating(full_ticker)

if analyst_rec:
    analyst_str = str(analyst_rec).replace("_", " ").title()
    st.markdown(f"<h3>{company_name} <span class='analyst-badge'>Analyst Consensus: {analyst_str}</span></h3>", unsafe_allow_html=True)
else:
    st.markdown(f"<h3>{company_name}</h3>", unsafe_allow_html=True)

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
    pass

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
c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
c1.metric("Current Price", f"₹{latest['Close']:,.2f}")
c2.metric("Day Change %", f"{day_change_pct:,.2f}%", delta=f"{day_change:+,.2f}")
c3.metric("Support (S1)", f"₹{support_val:,.2f}")
c4.metric("Resistance (R1)", f"₹{resistance_val:,.2f}")
c5.metric("52W High", f"₹{week52_high:,.2f}")
c6.metric("52W Low", f"₹{week52_low:,.2f}")
c7.metric("Entry Price (Sync)", f"₹{latest['Close']:,.2f}")
c8.metric("Stop Loss (Sync)", f"₹{support_val:,.2f}")

# --- Health & Volume Metrics ---
vol_today_raw = latest.get("Volume", 1)
vol_20sma_raw = latest.get("Vol_20SMA", 1)
if pd.isna(vol_20sma_raw) or vol_20sma_raw == 0: vol_20sma_raw = 1
v_ratio_raw = vol_today_raw / vol_20sma_raw

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("##### 🏥 Fundamental & Volume Health")
h1, h2, h3, h4, h5 = st.columns(5)
h1.metric("ROCE (Efficiency)", f"{roce:.2f}%")
h2.metric("Debt-to-Equity", f"{debt_to_equity:.2f}")
h3.metric("Current Volume", f"{int(vol_today_raw):,}")
h4.metric("20-Day Avg Vol", f"{int(vol_20sma_raw):,}")

surge_label = "🔥 Institutional Buy" if v_ratio_raw >= 1.5 else "Normal"
surge_color = "normal" if v_ratio_raw >= 1.5 else "off"
h5.metric("Volume Surge", f"{v_ratio_raw:.2f}x", delta=surge_label, delta_color=surge_color)
st.markdown("<br>", unsafe_allow_html=True)

# --- Master Algorithmic Rating ---
score = 0
current_price_for_rating = latest["Close"]
if resistance_val > support_val:
    raw_s = ((current_price_for_rating - support_val) / (resistance_val - support_val)) * 100
    s_score = max(0, min(100, int(raw_s)))
else:
    s_score = 50

if s_score <= 30: score += 2
elif s_score <= 60: score += 1

adx_val_for_rating = latest.get("ADX", 0)
if pd.isna(adx_val_for_rating): adx_val_for_rating = 0

if adx_val_for_rating >= 50: score += 2
elif adx_val_for_rating >= 25: score += 1

vol_td = latest.get("Volume", 1)
vol_20s = latest.get("Vol_20SMA", 1)
if pd.isna(vol_20s) or vol_20s == 0: vol_20s = 1
v_ratio = vol_td / vol_20s

if v_ratio >= 1.5: score += 2
elif v_ratio >= 1.0: score += 1

if roce > 15: score += 1
if debt_to_equity < 0.5: score += 1

if score >= 7: master_rating, rating_color_hex = "STRONG BUY (Techno-Funda)", "#00FF00"
elif score >= 5: master_rating, rating_color_hex = "MODERATE BUY", "#00D4AA"
elif score >= 3: master_rating, rating_color_hex = "WATCHLIST / HOLD", "#FFD700"
else: master_rating, rating_color_hex = "AVOID (Weak Fundamentals/Trend)", "#FF4B4B"

rating_html = f'''
<div style="text-align: center; padding: 10px; margin: 15px 0; border-radius: 8px; border: 2px solid {rating_color_hex}; background: {rating_color_hex}1A;">
    <div style="font-size: 1.8em; font-weight: bold; margin: 0; color: {rating_color_hex}; text-shadow: 1px 1px 2px rgba(0,0,0,0.5);">MASTER ALGORITHMIC RATING: {master_rating}</div>
</div>
'''
st.markdown(rating_html, unsafe_allow_html=True)

# --- Visual Scoring (Gauge & Momentum) ---
c_gauge, c_mom = st.columns([1, 1])

text_clr = "white"

with c_gauge:
    current_price = latest["Close"]
    
    if resistance_val > support_val:
        # Lower score means closer to support (safer entry)
        raw_score = ((current_price - support_val) / (resistance_val - support_val)) * 100
        safe_score = max(0, min(100, int(raw_score)))
    else:
        safe_score = 50

    gauge_num_color = "#00FF00" if safe_score <= 30 else "#FFD700" if safe_score <= 60 else "#FF4B4B"

    gauge_fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=safe_score,
        number={'font': {'color': gauge_num_color}},
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
        
    adx_num_color = "#FF4B4B" if adx_val <= 25 else "#00D4AA" if adx_val <= 50 else "#00FF00"
        
    adx_fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=adx_val,
        number={'font': {'color': adx_num_color}},
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
    
    weak_clr = "gray"
    strong_clr = "green"
    vstrong_clr = "darkgreen"

    st.markdown(f"<p style='text-align: center; font-size: 0.9em; margin-top: -10px;'><span style='color: {weak_clr};'>0-25: Weak</span> | <span style='color: {strong_clr};'>25-50: Strong</span> | <span style='color: {vstrong_clr};'>50-100: Very Strong</span></p>", unsafe_allow_html=True)
    
# --- Earnings Warning ---
earnings_date = check_earnings(full_ticker)
if earnings_date:
    formatted_date = earnings_date.strftime("%d %b %Y")
    st.markdown(
        f'<div class="earnings-warning">'
        f"<span class='icon-3d'>🚨</span> EARNINGS ALERT: {company_name} reports earnings on {formatted_date}! "
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
    saved_key = st.session_state.get("gemini_key")
    if saved_key and headlines:
        st.markdown("---")
        st.markdown("**🤖 AI-Powered Catalyst Summary**")
        
        summary_key = f"ai_summary_{full_ticker}"
        
        if summary_key not in st.session_state:
            st.session_state[summary_key] = None
            
        if st.session_state[summary_key] is None:
            if st.button("Generate AI Catalyst Summary"):
                with st.spinner("Generating AI catalyst summary..."):
                    summary = summarize_with_gemini(headlines, company_name, saved_key)
                    st.session_state[summary_key] = summary
                    st.rerun()
        else:
            st.markdown(
                f'<div class="story-section">{st.session_state[summary_key]}</div>',
                unsafe_allow_html=True,
            )
    elif not saved_key:
        st.info("Add your free Gemini API key in the sidebar to enable AI-powered catalyst summaries.")
else:
    st.info("No recent news found.")

render_control_center()

# ===================================================================
# Footer
# ===================================================================
st.divider()
st.caption("Data sourced from Yahoo Finance. News via Google News. AI by Google Gemini. Built with Streamlit.")
st.caption("⚠️ This tool is for educational purposes only. Not financial advice.")
