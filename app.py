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
import gspread
import streamlit as st
import yfinance as yf
from gnews import GNews
from plotly.subplots import make_subplots
from streamlit_gsheets import GSheetsConnection

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
if "sheets_error" not in st.session_state:
    st.session_state["sheets_error"] = False
if "m_ticker_input" not in st.session_state:
    st.session_state["m_ticker_input"] = ""
if "m_price_input" not in st.session_state:
    st.session_state["m_price_input"] = 0.0
if "m_qty_input" not in st.session_state:
    st.session_state["m_qty_input"] = 1
if "w_ticker_input" not in st.session_state:
    st.session_state["w_ticker_input"] = ""

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
# DATA HELPERS & SANITIZATION
# ===================================================================

def sanitize_ticker(ticker: str) -> str:
    """Correct common typos and map aliases for Indian stocks."""
    if not ticker or not isinstance(ticker, str):
        return ""
    
    # 1. Basic Cleaning
    t = ticker.strip().upper()
    
    # 2. Fix Common Suffix Typos
    if ".N" in t and not t.endswith(".NS") and not t.endswith(".BO"):
        t = t.replace(".N", ".NS")
    t = t.replace(".NS.NS", ".NS")
    
    # 3. Typo Mapping (Alias)
    TYPO_MAP = {
        "NANDAN DENIM.NS": "NDL.NS",
        "NANDAN.NS": "NDL.NS",
        "NANDAM.NS": "NDL.NS",
        "NANDAM DENIM.NS": "NDL.NS",
        "SHREE RAMA.NS": "SHREERAMA.NS",
        "TATA MOTORS.NS": "TATAMOTORS.NS",
        "TATA STEEL.NS": "TATASTEEL.NS"
    }
    return TYPO_MAP.get(t, t)


# ===================================================================
# DATA CONNECTION (Google Sheets) — Non-Blocking & Robust
# ===================================================================

def ensure_worksheets_exist(conn):
    """Verify existence of Watchlist and Portfolio tabs, create if missing."""
    try:
        # 1. Watchlist
        try:
            conn.read(worksheet="Watchlist", ttl=0)
        except Exception:
            conn.create(worksheet="Watchlist", data=pd.DataFrame(columns=["Ticker"]))
        
        # 2. Portfolio
        try:
            conn.read(worksheet="Portfolio", ttl=0)
        except Exception:
            conn.create(worksheet="Portfolio", data=pd.DataFrame(columns=["Ticker", "Buy_Price", "Quantity"]))
            
    except Exception:
        # Flag error but do not stop the app
        st.session_state["sheets_error"] = True


# Global Connection Handle
conn = None

# 1. Robust Secrets Check
if "connections" not in st.secrets or "gsheets" not in st.secrets["connections"]:
    st.session_state["sheets_error"] = True

# 2. Key Sanitization (As Requested)
try:
    if not st.session_state["sheets_error"]:
        private_key = st.secrets["connections"]["gsheets"]["private_key"].replace('\\n', '\n').strip()
except Exception:
    st.session_state["sheets_error"] = True

# 3. Main Connection Initialization (Bypass hard-stop)
if not st.session_state["sheets_error"]:
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        ensure_worksheets_exist(conn)
    except Exception:
        st.session_state["sheets_error"] = True


def load_sheet_data(worksheet: str, columns: list) -> pd.DataFrame:
    """Read a worksheet with non-blocking error handling."""
    if st.session_state["sheets_error"] or conn is None:
        return pd.DataFrame(columns=columns)
    try:
        df = conn.read(worksheet=worksheet, ttl=0)
        if df is None or df.empty:
            return pd.DataFrame(columns=columns)
        # Ensure all columns exist
        df = df.dropna(how="all")
        for col in columns:
            if col not in df.columns:
                df[col] = None
        return df[columns]
    except Exception:
        return pd.DataFrame(columns=columns)


def save_sheet_data(worksheet: str, df: pd.DataFrame, columns: list):
    """Update a worksheet with non-blocking error handling."""
    if st.session_state["sheets_error"] or conn is None:
        st.error("⚠️ Cannot save: Google Sheets Connection is currently offline.")
        return
    if df.empty:
        df = pd.DataFrame(columns=columns)
    try:
        conn.update(worksheet=worksheet, data=df)
    except Exception:
        try:
            conn.create(worksheet=worksheet, data=df)
        except Exception:
            st.error(f"⚠️ Failed to save to {worksheet}. Please check Google Sheets permissions.")


@st.cache_data(ttl=900)
def fetch_ohlcv(ticker: str) -> pd.DataFrame:
    try:
        # Standardize for yfinance MultiIndex (requires yfinance >= 0.2.40)
        df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True, multi_level_index=False)
        if df.empty: return pd.DataFrame()
        
        # Force flatten columns and handle edge cases
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # Clean column names
        df.columns = [str(c).strip().title() for c in df.columns]
        
        # Nuke duplicates and sort
        df = df.loc[~df.index.duplicated(keep='last')]
        return df.sort_index()
    except Exception:
        return pd.DataFrame()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    # 1. Force a clean copy with a unique index
    df = df.copy().loc[~df.index.duplicated(keep='first')]
    
    # 2. Add indicators one by one using 'concat' instead of direct assignment
    sma50 = ta.sma(df["Close"], length=50)
    sma200 = ta.sma(df["Close"], length=200)
    adx_res = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    vol_sma = ta.sma(df["Volume"], length=20)
    
    # Force uppercase columns for uniform mapping
    df.columns = [str(c).upper() for c in df.columns]
    
    df = pd.concat([df, sma50, sma200, adx_res, vol_sma], axis=1)
    
    # Rename specifically assigned columns
    df = df.rename(columns={
        'SMA_50': 'SMA_50', 
        'SMA_200': 'SMA_200', 
        'ADX_14': 'ADX',
        'SMA_20': 'VOL_20SMA'
    })
    
    # Pivot logic
    previous_window = df.iloc[-21:-1]
    if not previous_window.empty:
        pp_high = previous_window["HIGH"].max()
        pp_low = previous_window["LOW"].min()
        pp_close = previous_window["CLOSE"].iloc[-1]

        pivot = (pp_high + pp_low + pp_close) / 3
        df["PIVOT"] = pivot
        df["SUPPORT_1"] = 2 * pivot - pp_high
        df["RESISTANCE_1"] = 2 * pivot - pp_low
    else:
        # Fallback if window is too small
        last_close = df["CLOSE"].iloc[-1]
        df["PIVOT"] = last_close
        df["SUPPORT_1"] = last_close
        df["RESISTANCE_1"] = last_close
        
    if "VOL_20SMA" not in df.columns:
        df["VOL_20SMA"] = 1

    # Map back to standard names for compatibility with the rest of the app
    df = df.rename(columns={
        'CLOSE': 'Close', 'HIGH': 'High', 'LOW': 'Low', 'OPEN': 'Open', 'VOLUME': 'Volume',
        'PIVOT': 'Pivot', 'SUPPORT_1': 'Support_1', 'RESISTANCE_1': 'Resistance_1',
        'VOL_20SMA': 'Vol_20SMA'
    })
    
    return df.fillna(0)


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


@st.cache_data(ttl=3600)
def fetch_fundamentals(ticker: str):
    """Fetch key fundamental metrics for a ticker."""
    try:
        tk = yf.Ticker(ticker)
        info = tk.info
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
            except: pass
        if roce is not None:
            roce = float(roce)
            if -2.0 < roce < 2.0 and roce != 0.0: roce *= 100
        else: roce = 0.0

        debt_to_equity = info.get("debtToEquity", 0)
        if not debt_to_equity or debt_to_equity == 0:
            try:
                bs = tk.balance_sheet
                if not bs.empty:
                    td = bs.loc['Total Debt'].iloc[0] if 'Total Debt' in bs.index else 0
                    te = bs.loc['Stockholders Equity'].iloc[0] if 'Stockholders Equity' in bs.index else 1
                    debt_to_equity = td / te
            except: pass
        if debt_to_equity is not None:
            debt_to_equity = float(debt_to_equity)
            if debt_to_equity > 5.0: debt_to_equity /= 100
        else: debt_to_equity = 0.0
        
        return {"roce": roce, "debt_to_equity": debt_to_equity}
    except Exception:
        return {"roce": 0.0, "debt_to_equity": 0.0}


def calculate_master_score(df: pd.DataFrame, fundamentals: dict):
    """Calculate the 8-point Master Rating score."""
    if df.empty: return 0, 0, 0, 0, 0
    latest = df.iloc[-1]
    support_val = df["Support_1"].iloc[-1]
    resistance_val = df["Resistance_1"].iloc[-1]
    
    # 1. Safety Score
    s_points = 0
    if resistance_val > support_val:
        raw_s = ((latest["Close"] - support_val) / (resistance_val - support_val)) * 100
        s_score = max(0, min(100, int(raw_s)))
    else: s_score = 50
    if s_score <= 30: s_points = 2
    elif s_score <= 60: s_points = 1
    
    # 2. Trend (ADX)
    t_points = 0
    adx_v = latest.get("ADX", 0)
    if adx_v >= 50: t_points = 2
    elif adx_v >= 25: t_points = 1
    
    # 3. Vol (Volume Surge)
    v_points = 0
    vol_today = latest.get("Volume", 1)
    vol_20sma = latest.get("Vol_20SMA", 1)
    if pd.isna(vol_20sma) or vol_20sma == 0: vol_20sma = 1
    v_ratio = vol_today / vol_20sma
    if v_ratio >= 1.5: v_points = 2
    elif v_ratio >= 1.0: v_points = 1
    
    # 4. Funda
    f_points = 0
    if fundamentals["roce"] > 15: f_points += 1
    if fundamentals["debt_to_equity"] < 0.5: f_points += 1
    
    total_score = s_points + t_points + v_points + f_points
    return total_score, t_points, v_points, s_points, f_points


def render_control_center():
    # --- Row 1: Batch Processor (Full-Width) ---
    st.markdown("<div style='padding-top: 2rem;'>", unsafe_allow_html=True)
    st.subheader("📂 Batch Processor")
    tab1, tab2 = st.tabs(["📝 Quick Paste", "📁 Upload File"])
    
    def run_batch_scan(w_df):
        try:
            # Force Column Strip
            w_df.columns = [str(c).strip() for c in w_df.columns]
            
            # Find ticker column
            search_terms = ["ticker", "symbol", "name", "company name", "stock", "identifier"]
            ticker_col = next((c for c in w_df.columns if any(term in str(c).lower() for term in search_terms)), None)
            
            if ticker_col:
                tickers_to_scan = w_df[ticker_col].dropna().astype(str).unique().tolist()[:50]

                with st.spinner("Scanning Watchlist (Top 50)..."):
                    st.session_state["batch_results"] = None
                    results = []
                    progress_text = st.empty()
                    for i, t in enumerate(tickers_to_scan):
                        progress_text.text(f"🔍 Scanning {i+1}/{len(tickers_to_scan)}: {t}...")
                        clean_name = str(t).strip()
                        
                        try:
                            s_res = yf.Search(clean_name, max_results=1).quotes
                            if s_res:
                                sym = s_res[0].get('symbol', '')
                                t_sym = sym if (".NS" in sym or ".BO" in sym) else f"{sym}.NS"
                            else:
                                t_sym = clean_name.upper().replace(" ", "") + ".NS"
                        except Exception:
                            t_sym = clean_name.upper().replace(" ", "") + ".NS"

                        b_df = fetch_ohlcv(t_sym)
                        if b_df.empty or len(b_df) < 50:
                            continue
                            
                        try:
                            b_df = compute_indicators(b_df)
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
                        except:
                            continue
                    
                    progress_text.empty()
                    if results:
                        st.session_state["batch_results"] = pd.DataFrame(results).sort_values("Risk to Stop %")
                        st.success(f"✅ Success: {len(results)} stocks matched your criteria.")
                    else:
                        st.error("❌ No stocks passed the scan.")
            else:
                st.error(f"Could not find a Ticker/Name column. Detected headers: {list(w_df.columns)}")
        except Exception as e:
            st.error(f"Error processing data: {e}")

    with tab1:
        st.markdown("_Highlight web tables, press Ctrl+C, and paste below._")
        pasted_data = st.text_area("Paste Web Table Here:", height=100, placeholder="Paste data here...")
        if st.button("Run Paste Scan", type="primary"):
            if pasted_data:
                try:
                    raw_data = pd.read_csv(io.StringIO(pasted_data), sep='\t', header=None)
                    if not raw_data.empty:
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
                        run_batch_scan(w_df)
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
                    run_batch_scan(w_df)
                except Exception as e:
                    st.error(f"File reading error: {e}")
            else:
                st.warning("Please upload a file first.")



# ===================================================================
# INITIALIZE SESSION STATE
# ===================================================================
# INITIALIZE SESSION STATE (Moved to top level file)

st.markdown("<h1><span class='icon-3d'>📈</span> Stock Market Analysis Dashboard</h1>", unsafe_allow_html=True)

col_sym, col_tick = st.columns([7, 3])
with col_sym:
    search_query = st.text_input(
        "Search Company Name or Ticker",
        value="",
        placeholder="e.g., Narmada, RELIANCE, TCS",
        key="search_input",
    )


if search_query:
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
                options.sort(key=lambda x: 0 if x.endswith(".NS") else 1)
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

    # --- FETCH DATA & SILENT SYNC ---
    with st.spinner("Fetching market data..."):
        df = fetch_ohlcv(full_ticker)

    if df.empty or len(df) < 50:
        st.info(f"Not enough market data found for **{full_ticker}**. Please verify the symbol.")
    else:
        df = compute_indicators(df)
        company_name = get_company_name(full_ticker)

        with st.spinner("Fetching fundamentals..."):
            funda = fetch_fundamentals(full_ticker)
            roce = funda["roce"]
            debt_to_equity = funda["debt_to_equity"]

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

            st.divider()
            

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

            # --- Fundamental health ---
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
            h5.metric("Volume Surge", f"{v_ratio_raw:.2f}x", delta=surge_label, delta_color="normal" if v_ratio_raw >= 1.5 else "off")

            # --- Master Rating ---
            total_score, t_points, v_points, s_points, f_points = calculate_master_score(df, {"roce": roce, "debt_to_equity": debt_to_equity})
            s_score = (s_points / 2) * 100
            adx_v = float(df["ADX"].iloc[-1])

            if total_score >= 7: master_rating, rating_color_hex = "STRONG BUY (Techno-Funda)", "#00FF00"
            elif total_score >= 5: master_rating, rating_color_hex = "MODERATE BUY", "#00D4AA"
            elif total_score >= 3: master_rating, rating_color_hex = "WATCHLIST / HOLD", "#FFD700"
            else: master_rating, rating_color_hex = "AVOID", "#FF4B4B"

            rating_html = f'''
            <div style="text-align: center; padding: 10px; margin: 15px 0; border-radius: 8px; border: 2px solid {rating_color_hex}; background: {rating_color_hex}1A;">
                <div style="font-size: 1.8em; font-weight: bold; margin: 0; color: {rating_color_hex};">MASTER ALGORITHMIC RATING: {master_rating}</div>
                <div style="font-size: 0.9em; color: gray; margin-top: 5px;">
                    Trend: {t_points}/2 | Vol: {v_points}/2 | Safety: {s_points}/2 | Funda: {f_points}/2
                </div>
            </div>
            '''
            st.markdown(rating_html, unsafe_allow_html=True)
            
            # --- Pin to Watchlist Button ---
            w_col1, w_col2, w_col3 = st.columns([1, 1, 1])
            with w_col2:
                if st.button("⭐ Pin to Watchlist", use_container_width=True):
                    clean_p = sanitize_ticker(full_ticker)
                    w_df = load_sheet_data("Watchlist", ["Ticker"])
                    if clean_p not in w_df["Ticker"].values:
                        new_row = pd.DataFrame([{"Ticker": clean_p}])
                        w_df = pd.concat([w_df, new_row], ignore_index=True)
                        save_sheet_data("Watchlist", w_df, ["Ticker"])
                        st.success(f"Pinned {clean_p} to Watchlist!")
                    else:
                        st.info(f"{clean_p} is already in Watchlist.")
                    st.rerun()

            # --- Visual Indicators (Gauge) ---
            c_gauge, c_mom = st.columns(2)
            with c_gauge:
                # Color code safety number
                gauge_num_color = "#00D4AA" if s_score <= 30 else "#FFD700" if s_score <= 60 else "#FF4B4B"
                g_fig = go.Figure(go.Indicator(mode="gauge+number", value=s_score, number={'font': {'color': gauge_num_color}}, title={'text': "Entry Safety Gauge", 'font': {'size': 20, 'color': "white"}}, gauge={'axis': {'range': [None, 100]}, 'bar': {'color': "#00D4AA"}, 'steps': [{'range': [0, 30], 'color': 'rgba(0, 212, 170, 0.3)'}, {'range': [30, 60], 'color': 'rgba(255, 215, 0, 0.3)'}, {'range': [60, 100], 'color': 'rgba(255, 75, 75, 0.3)'}]}))
                g_fig.update_layout(height=260, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={'color': "white"})
                st.plotly_chart(g_fig, use_container_width=True)
                st.markdown("<p style='text-align: center; color: gray;'><span style='color: #00D4AA;'>Safe</span> | <span style='color: #FFD700;'>Fair</span> | <span style='color: #FF4B4B;'>Overextended</span></p>", unsafe_allow_html=True)
            with c_mom:
                # Color code ADX number
                adx_num_color = "#808080" if adx_v <= 25 else "#00D4AA" if adx_v <= 50 else "#006400"
                adx_fig = go.Figure(go.Indicator(mode="gauge+number", value=adx_v, number={'font': {'color': adx_num_color}}, title={'text': "Trend Strength (ADX)", 'font': {'size': 20, 'color': "white"}}, gauge={'axis': {'range': [None, 100]}, 'bar': {'color': "#00D4AA"}, 'steps': [{'range': [0, 25], 'color': 'gray'}, {'range': [25, 50], 'color': 'green'}, {'range': [50, 100], 'color': 'darkgreen'}]}))
                adx_fig.update_layout(height=260, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={'color': "white"})
                st.plotly_chart(adx_fig, use_container_width=True)
                st.markdown("<p style='text-align: center; color: gray;'><span style='color: #808080;'>Weak</span> | <span style='color: #00D4AA;'>Strong</span> | <span style='color: #006400;'>Very Strong</span></p>", unsafe_allow_html=True)

            # --- Chart & Earnings ---
            earnings_date = check_earnings(full_ticker)
            if earnings_date: st.warning(f"🚨 EARNINGS ALERT: {company_name} reports on {earnings_date.strftime('%d %b %Y')}!")
            fig = build_chart(df, display_label)
            st.plotly_chart(fig, use_container_width=True)

            # --- News Section ---
            st.subheader("📰 Recent Catalysts")
            with st.spinner("Fetching news..."):
                articles = fetch_news(company_name)
            if articles:
                for i, art in enumerate(articles, 1):
                    st.markdown(f"**{i}.** [{art.get('title')}]({art.get('url')})  \n<sub>{art.get('publisher', {}).get('title')} · {art.get('published date')}</sub>", unsafe_allow_html=True)
                # AI Summary
                headlines = [art.get("title") for art in articles if art.get("title")]
                saved_key = st.session_state.get("gemini_key")
                if saved_key and headlines:
                    st.markdown("---")
                    summary_key = f"ai_summary_{full_ticker}"
                    if summary_key not in st.session_state or st.session_state[summary_key] is None:
                        if st.button("Generate AI Catalyst Summary"):
                            with st.spinner("Generating..."):
                                summary = summarize_with_gemini(headlines, company_name, saved_key)
                                st.session_state[summary_key] = summary
                                st.rerun()
                    else:
                        st.markdown(f'<div class="story-section">{st.session_state[summary_key]}</div>', unsafe_allow_html=True)
            else: st.info("No recent news found.")

            st.divider()
            # --- 1% Risk Calculator (Decoupled & Synced) ---
            st.subheader("📐 1% Risk Calculator")
            st.markdown("_Direct analysis for **" + full_ticker + "** (Auto-synced)._")
            
            if st.session_state["sync_ticker"] != full_ticker:
                st.session_state["sync_ticker"] = full_ticker
                st.session_state["entry_price_key"] = float(latest["Close"])
                st.session_state["stop_loss_key"] = float(support_val)

            c_calc, c_gap, c_pos = st.columns([4.5, 1, 4.5])
            with c_calc:
                capital = st.number_input("Total Account Capital (₹)", min_value=0.0, step=10000.0, key="capital_key")
                st.session_state["capital_ext"] = capital
                entry_price = st.number_input("Entry Price (₹)", min_value=0.01, step=0.5, key="entry_price_key")
                stop_loss = st.number_input("Stop-Loss Price (₹)", min_value=0.01, step=0.5, key="stop_loss_key")

            with c_pos:
                if entry_price > stop_loss:
                    max_risk = capital * 0.01
                    risk_per_share = entry_price - stop_loss
                    shares_to_buy = math.floor(max_risk / risk_per_share)
                    total_deployed = shares_to_buy * entry_price
                    if shares_to_buy > 0:
                        st.subheader("📊 Position Size")
                        st.metric("Max Risk (1%)", f"₹{max_risk:,.2f}")
                        st.metric("Risk Per Share", f"₹{risk_per_share:,.2f}")
                        st.metric("Shares to Buy", f"{shares_to_buy:,}")
                        st.metric("Capital Deployed", f"₹{total_deployed:,.2f}")
                        
                        if st.button("💼 Add to Portfolio", type="primary", use_container_width=True):
                            clean_p = sanitize_ticker(full_ticker)
                            p_df = load_sheet_data("Portfolio", ["Ticker", "Buy_Price", "Quantity"])
                            if clean_p in p_df["Ticker"].values:
                                p_df.loc[p_df["Ticker"] == clean_p, ["Buy_Price", "Quantity"]] = [entry_price, shares_to_buy]
                                st.info(f"Updated {clean_p} in Portfolio.")
                            else:
                                new_trade = pd.DataFrame([{
                                    "Ticker": clean_p,
                                    "Buy_Price": entry_price,
                                    "Quantity": shares_to_buy
                                }])
                                p_df = pd.concat([p_df, new_trade], ignore_index=True)
                                st.success(f"Added {clean_p} to Portfolio!")
                            
                            save_sheet_data("Portfolio", p_df, ["Ticker", "Buy_Price", "Quantity"])
                            st.rerun()
                            
                        if total_deployed > capital: st.warning("⚠️ Position exceeds your total capital!")
                else: st.error("Entry Price must be greater than Stop-Loss Price.")

            st.divider()

        except (IndexError, KeyError) as e:
            st.info(f"Market structure algorithms currently unavailable for **{full_ticker}**.")

# ===================================================================
# LIVE PORTFOLIO & WATCHLIST — Middle Layer
# ===================================================================
st.markdown("---")
col_p1, col_p2 = st.columns([1, 1])

with col_p1:
    st.subheader("💼 Live Portfolio")
    if st.session_state["sheets_error"]:
        st.error("⚠️ Google Sheets Connection Error: Portfolio management is temporarily unavailable.")
    else:
        with st.expander("➕ Add Existing Trade Manually"):
            m_ticker = st.text_input("Ticker", placeholder="e.g. RELIANCE.NS", key="m_ticker_input")
            m_price = st.number_input("Average Buy Price", min_value=0.0, step=1.0, key="m_price_input")
            m_qty = st.number_input("Quantity", min_value=1, step=1, key="m_qty_input")
            if st.button("Save to Portfolio"):
                if m_ticker:
                    clean_t = sanitize_ticker(m_ticker)
                    p_df = load_sheet_data("Portfolio", ["Ticker", "Buy_Price", "Quantity"])
                    
                    if clean_t in p_df["Ticker"].values:
                        p_df.loc[p_df["Ticker"] == clean_t, ["Buy_Price", "Quantity"]] = [m_price, m_qty]
                        st.info(f"Updated {clean_t} in Portfolio.")
                    else:
                        new_row = pd.DataFrame([{"Ticker": clean_t, "Buy_Price": m_price, "Quantity": m_qty}])
                        p_df = pd.concat([p_df, new_row], ignore_index=True)
                        st.success(f"Added {clean_t} to Portfolio!")
                    
                    save_sheet_data("Portfolio", p_df, ["Ticker", "Buy_Price", "Quantity"])
                    # Reset via rerun
                    st.rerun()

    p_df = load_sheet_data("Portfolio", ["Ticker", "Buy_Price", "Quantity"])
    if not p_df.empty:
        # Header Row
        h_col = st.columns([2, 1.5, 1.5, 2, 2, 2])
        h_col[0].markdown("**Ticker**")
        h_col[1].markdown("**P&L%**")
        h_col[2].markdown("**Status**")
        h_col[3].markdown("**Master**")
        h_col[4].markdown("**Action**")
        h_col[5].markdown("**Delete**")
        
        for idx, row in p_df.iterrows():
            ticker = row["Ticker"]
            clean_ticker = sanitize_ticker(ticker)
            buy_price = row["Buy_Price"]
            
            try:
                p_data = fetch_ohlcv(clean_ticker)
                
                # Force Sync / Smart Search Fallback
                if p_data.empty:
                    try:
                        search_res = yf.Search(clean_ticker, max_results=1).quotes
                        if search_res:
                            new_sym = search_res[0]['symbol']
                            p_data = fetch_ohlcv(new_sym)
                            clean_ticker = new_sym
                    except Exception: pass

                if not p_data.empty:
                    p_data = compute_indicators(p_data)
                    funda = fetch_fundamentals(clean_ticker)
                    score, _, _, _, _ = calculate_master_score(p_data, funda)
                    cmp = p_data["Close"].iloc[-1]
                    s1 = p_data["Support_1"].iloc[-1]
                    pnl = ((cmp - buy_price) / buy_price * 100) if buy_price > 0 else 0
                    
                    # Exit Logic
                    if cmp < s1: status, color = "🚨 SELL (Below Support)", "#FF4B4B"
                    elif score < 4: status, color = "⚠️ WEAK (Watch)", "#FFD700"
                    else: status, color = "✅ HOLD", "#00D4AA"
                    
                    r_col = st.columns([2, 1.5, 1.5, 2, 2, 2])
                    r_col[0].write(clean_ticker)
                    r_col[1].write(f"{pnl:+.2f}%")
                    r_col[2].markdown(f"<span style='color:{color}; font-weight:bold;'>{status}</span>", unsafe_allow_html=True)
                    r_col[3].write(f"Rating: {score}/8")
                    if r_col[4].button("Analyze", key=f"p_an_{clean_ticker}_{idx}"):
                        st.session_state["search_input"] = str(clean_ticker)
                        st.rerun()
                    if r_col[5].button("🗑️", key=f"p_del_{clean_ticker}_{idx}"):
                        p_df = p_df.drop(idx)
                        save_sheet_data("Portfolio", p_df, ["Ticker", "Buy_Price", "Quantity"])
                        st.rerun()
                else:
                    r_col = st.columns([2, 1.5, 1.5, 2, 2, 2])
                    r_col[0].write(f"⚠️ {clean_ticker}")
                    r_col[1].write("N/A")
                    r_col[2].write("Invalid Ticker")
                    r_col[3].write("N/A")
                    r_col[4].write("")
                    if r_col[5].button("🗑️", key=f"p_del_err_{clean_ticker}_{idx}"):
                        p_df = p_df.drop(idx)
                        save_sheet_data("Portfolio", p_df, ["Ticker", "Buy_Price", "Quantity"])
                        st.rerun()
            except Exception:
                st.error(f"Error processing {clean_ticker}")
    else:
        st.info("Portfolio is empty. Add trades manually or from the calculator.")

with col_p2:
    st.subheader("⭐ Watchlist")
    if st.session_state["sheets_error"]:
        st.error("⚠️ Google Sheets Connection Error: Watchlist management is temporarily unavailable.")
    else:
        w_input = st.text_input("Add Ticker to Watchlist", placeholder="e.g. TCS (Press Enter)", key="w_ticker_input")
    w_df = load_sheet_data("Watchlist", ["Ticker"])
    if w_input:
        clean_w = sanitize_ticker(w_input)
        if clean_w not in w_df["Ticker"].values:
            new_row = pd.DataFrame([{"Ticker": clean_w}])
            w_df = pd.concat([w_df, new_row], ignore_index=True)
            save_sheet_data("Watchlist", w_df, ["Ticker"])
            st.success(f"Added {clean_w} to Watchlist!")
        else:
            st.info(f"{clean_w} is already in Watchlist.")
        
        # Reset via rerun
        st.rerun()

    if not w_df.empty:
        # Header
        wh_col = st.columns([1.5, 1.2, 1.2, 1.2, 1.2, 1, 1])
        wh_col[0].markdown("**Ticker**")
        wh_col[1].markdown("**Price**")
        wh_col[2].markdown("**Rating**")
        wh_col[3].markdown("**Safety**")
        wh_col[4].markdown("**S1 Support**")
        wh_col[5].markdown("**Action**")
        wh_col[6].markdown("**Delete**")
        
        for idx, row in w_df.iterrows():
            ticker = row["Ticker"]
            clean_ticker = sanitize_ticker(ticker)
            try:
                w_data = fetch_ohlcv(clean_ticker)
                
                # Force Sync / Smart Search Fallback
                if w_data.empty:
                    try:
                        search_res = yf.Search(clean_ticker, max_results=1).quotes
                        if search_res:
                            new_sym = search_res[0]['symbol']
                            w_data = fetch_ohlcv(new_sym)
                            clean_ticker = new_sym
                    except Exception: pass

                if not w_data.empty:
                    w_data = compute_indicators(w_data)
                    f_w = fetch_fundamentals(clean_ticker)
                    scr_w, _, _, s_pts_w, _ = calculate_master_score(w_data, f_w)
                    
                    price_str = f"₹{w_data['Close'].iloc[-1]:,.2f}"
                    s1_val = f"₹{w_data['Support_1'].iloc[-1]:,.2f}"
                    
                    # Safety Status
                    if s_pts_w == 2: safety_txt, safety_clr = "Safe", "#00D4AA"
                    elif s_pts_w == 1: safety_txt, safety_clr = "Fair", "#FFD700"
                    else: safety_txt, safety_clr = "Overextended", "#FF4B4B"
                    
                    wr_col = st.columns([1.5, 1.2, 1.2, 1.2, 1.2, 1, 1])
                    wr_col[0].write(clean_ticker)
                    wr_col[1].write(price_str)
                    wr_col[2].write(f"{scr_w}/8")
                    wr_col[3].markdown(f"<span style='color:{safety_clr};'>{safety_txt}</span>", unsafe_allow_html=True)
                    wr_col[4].write(s1_val)
                    if wr_col[5].button("Analyze", key=f"w_an_{clean_ticker}_{idx}"):
                        st.session_state["search_input"] = str(clean_ticker)
                        st.rerun()
                    if wr_col[6].button("🗑️", key=f"w_del_{clean_ticker}_{idx}"):
                        w_df = w_df.drop(idx)
                        save_sheet_data("Watchlist", w_df, ["Ticker"])
                        st.rerun()
                else:
                    wr_col = st.columns([1.5, 1.2, 1.2, 1.2, 1.2, 1, 1])
                    wr_col[0].write(f"⚠️ {clean_ticker}")
                    wr_col[1].write("N/A")
                    wr_col[2].write("N/A")
                    wr_col[3].write("N/A")
                    wr_col[4].write("N/A")
                    wr_col[5].write("")
                    if wr_col[6].button("🗑️", key=f"w_del_err_{clean_ticker}_{idx}"):
                        w_df = w_df.drop(idx)
                        save_sheet_data("Watchlist", w_df, ["Ticker"])
                        st.rerun()
            except Exception:
                st.error(f"Error processing {clean_ticker}")
    else:
        st.info("Watchlist is empty. Search and pin stocks or add manually.")

# ===================================================================
# BATCH ENGINE — Persistent Bottom Layer
# ===================================================================
st.markdown("---")
render_control_center()

if "batch_results" in st.session_state and st.session_state["batch_results"] is not None:
    st.markdown("---")
    st.subheader("🔥 Watchlist Batch Results")
    
    # Custom display for Batch Results to include 'Analyze' button
    b_results = st.session_state["batch_results"]
    if not b_results.empty:
        # Header
        bh_col = st.columns([1, 2, 2, 2, 2, 2, 3])
        bh_col[1].markdown("**Ticker**")
        bh_col[2].markdown("**Price**")
        bh_col[3].markdown("**Support**")
        bh_col[4].markdown("**Safety**")
        bh_col[5].markdown("**Rating**")
        bh_col[6].markdown("**Action**")
        
        for idx, row in b_results.iterrows():
            rb_col = st.columns([1, 2, 2, 2, 2, 2, 3])
            # We keep the Select column as a checkbox if needed, but here we just show buttons
            rb_col[1].write(row["Ticker"])
            rb_col[2].write(f"₹{row['Price']}")
            rb_col[3].write(f"₹{row['Support1']}")
            rb_col[4].write(row["Safety Score"])
            rb_col[5].write(row["Master Rating"])
            if rb_col[6].button("Analyze", key=f"b_an_{row['Ticker']}_{idx}"):
                st.session_state["search_input"] = str(sanitize_ticker(row["Ticker"]))
                st.rerun()
    
    # Still keep the data editor for selecting rows (Batch Export)
    st.markdown("##### 📝 Batch Trade Plan Exporter")
    edited_df = st.data_editor(
        st.session_state["batch_results"],
        hide_index=True,
        use_container_width=True,
        key="batch_editor"
    )
    st.session_state["batch_results"] = edited_df
    
    selected_rows = edited_df[edited_df["Select"] == True]
    if not selected_rows.empty:
        cap = st.session_state.get("capital_ext", 300000.0)
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

# ===================================================================
# Footer
# ===================================================================
st.divider()
st.subheader("🤖 AI Settings")

api_key = None
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    st.success("Gemini key loaded from secrets.")
except (Exception):
    api_key = st.text_input(
        "Gemini API Key",
        type="password",
        value=st.session_state.get("gemini_key", ""),
        help="Get a free key at aistudio.google.com",
    )
st.session_state["gemini_key"] = api_key

st.divider()
st.caption("Data sourced from Yahoo Finance. News via Google News. AI by Google Gemini. Built with Streamlit.")
st.caption("⚠️ This tool is for educational purposes only. Not financial advice.")
