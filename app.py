"""
Stock Market Analysis Dashboard
A free, full-featured stock analysis tool for Indian markets (NSE/BSE).
Tech: Streamlit · yfinance · pandas_ta · Plotly · GNews · Gemini Free Tier.
"""

import io
import math
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
import gspread
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from datetime import datetime
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
# BROWSER WARP & SCROLL ANCHOR (Hard-Reload Strategy)
# ---------------------------------------------------------------------------
# Hidden Anchor at the very top
st.markdown("<div id='top'></div>", unsafe_allow_html=True)

if st.session_state.get('force_top_reload'):
    # The JavaScript 'Hammer' - Definitively force parent scroll/reload
    components.html('''
        <script>
            try {
                window.parent.location.hash = "top";
                window.parent.scrollTo(0, 0);
            } catch(e) {
                console.log("Cross-origin scroll blocked, trying hash warp...");
                window.parent.location.hash = "top";
            }
        </script>
    ''', height=0)
    st.session_state['force_top_reload'] = False

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
if "force_top_reload" not in st.session_state:
    st.session_state["force_top_reload"] = False

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
# ORCHESTRATION & STATE HELPERS
# ===================================================================

if "search_input" not in st.session_state:
    st.session_state["search_input"] = ""
if "last_search_query" not in st.session_state:
    st.session_state["last_search_query"] = ""

def set_search_ticker(ticker: str):
    """Callback triggered by any 'Analyze' button to sync the search bar."""
    st.session_state["search_input"] = str(ticker)
    st.session_state["last_search_query"] = None # Force detection on all platforms (mobile inclusive)
    st.session_state["force_top_reload"] = True # Set flag for top-level warp
    # Trigger hash jump
    components.html('<script>try { window.parent.location.hash = "top"; } catch(e) {}</script>', height=0)


# ===================================================================
# DATA CONNECTION (Google Sheets) — Non-Blocking & Robust
# ===================================================================

def ensure_worksheets_exist(conn):
    """Verify existence of Watchlist, Portfolio, and Metadata tabs, create if missing."""
    try:
        # 1. Watchlist
        try:
            conn.read(worksheet="Watchlist", ttl=0)
        except Exception:
            conn.create(worksheet="Watchlist", data=pd.DataFrame(columns=["Ticker", "Signal"]))
        
        # 2. Portfolio
        try:
            conn.read(worksheet="Portfolio", ttl=0)
        except Exception:
            conn.create(worksheet="Portfolio", data=pd.DataFrame(columns=["Ticker", "Buy_Price", "Quantity", "Signal"]))

        # 3. Metadata (Tracking Scans)
        try:
            conn.read(worksheet="Metadata", ttl=0)
        except Exception:
            conn.create(worksheet="Metadata", data=pd.DataFrame([
                {"Key": "last_scan_time", "Value": "None"},
                {"Key": "last_sync_actual", "Value": "N/A"}
            ]))

        # 4. ScanHistory (Logging)
        try:
            conn.read(worksheet="ScanHistory", ttl=0)
        except Exception:
            conn.create(worksheet="ScanHistory", data=pd.DataFrame(columns=["Window", "Timestamp", "SignalCount"]))
            
    except Exception:
        # Flag error but do not stop the app
        st.session_state["sheets_error"] = True


# ── Persistent connection factory (survives reruns via cache_resource) ──────
@st.cache_resource(ttl=3600)
def get_persistent_conn():
    """Create the GSheets connection exactly once per hour.

    TTL=3600 ensures Streamlit automatically rebuilds stale OAuth tokens
    without needing a manual cache-clear.
    """
    return st.connection("gsheets", type=GSheetsConnection)


# 1. Robust Secrets Check (no global conn variable — cache manages the object)
if "connections" not in st.secrets or "gsheets" not in st.secrets["connections"]:
    st.session_state["sheets_error"] = True
    st.session_state["sheets_error_msg"] = "Missing [connections.gsheets] section in secrets.toml."
else:
    # 2. Key Sanitization — applied immediately on read to avoid \\n artifacts
    try:
        raw_key = st.secrets["connections"]["gsheets"]["private_key"]
        sanitized_key = raw_key.replace('\\n', '\n').strip()  # noqa: F841
    except Exception as _key_err:
        st.session_state["sheets_error"] = True
        st.session_state["sheets_error_msg"] = f"Private key read error: {_key_err}"

    # 3. Warm-up — call once at startup so the first rerun is instant
    if not st.session_state.get("sheets_error"):
        try:
            _startup_conn = get_persistent_conn()
            ensure_worksheets_exist(_startup_conn)
        except Exception as _conn_err:
            st.session_state["sheets_error"] = True
            st.session_state["sheets_error_msg"] = str(_conn_err)


def get_conn():
    """Self-healing connection accessor.

    Always tries to get a live connection from the cache.  If it
    succeeds it clears any stale error flags so the UI recovers
    automatically.  If it fails it sets the error flags for the UI
    to display the Retry button.
    """
    try:
        c = get_persistent_conn()
        # Successful — heal any previous error state
        st.session_state["sheets_error"] = False
        st.session_state.pop("sheets_error_msg", None)
        return c
    except Exception as e:
        st.cache_resource.clear()
        st.session_state["sheets_error"] = True
        st.session_state["sheets_error_msg"] = str(e)
        return None


def load_sheet_data(worksheet: str, columns: list) -> pd.DataFrame:
    """Read a worksheet with 3-attempt retry loop and 15s cache backoff."""
    active_conn = get_conn()
    if active_conn is None:
        return pd.DataFrame(columns=columns)
    
    for attempt in range(3):
        try:
            # Use 15s cache to prevent 429 Quota Exhaustion on reruns
            df = active_conn.read(worksheet=worksheet, ttl=15)
            if df is None or df.empty:
                return pd.DataFrame(columns=columns)
            # Ensure all columns exist
            df = df.dropna(how="all")
            for col in columns:
                if col not in df.columns:
                    df[col] = None
            return df[columns]
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                st.cache_resource.clear()
                st.session_state["sheets_error"] = True
                return pd.DataFrame(columns=columns)
    return pd.DataFrame(columns=columns)


def save_sheet_data(worksheet: str, df: pd.DataFrame, columns: list):
    """Update a worksheet with 3-attempt retry loop and fallback create."""
    active_conn = get_conn()
    if st.session_state.get("sheets_error") or active_conn is None:
        st.error("⚠️ Cannot save: Google Sheets Connection is currently offline.")
        return
    if df.empty:
        df = pd.DataFrame(columns=columns)
    
    for attempt in range(3):
        try:
            # Try to update first, fallback to create if worksheet missing or error
            try:
                active_conn.update(worksheet=worksheet, data=df)
            except Exception:
                active_conn.create(worksheet=worksheet, data=df)
            time.sleep(2)
            # Clear local cache so UI reads the new data immediately
            st.cache_data.clear()
            return
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                st.cache_resource.clear()
                if "429" in str(e) or "RATE_LIMIT" in str(e):
                    st.warning(f"⚠️ Google API Quota Exceeded for {worksheet}. The app will try again later.")
                else:
                    st.error(f"⚠️ Failed to save to {worksheet}. Please check permissions.")
                break


# ===================================================================
# AUTOMATED SCHEDULER & BATCH SCAN ENGINE
# ===================================================================

SCAN_WINDOWS = ["09:30", "11:30", "13:30", "14:30", "15:15"]

def background_batch_scan():
    """Background scanner to update Sheet technicals and signals.

    Uses get_conn() so it always has a live connection handle even when
    called from the Force-Scan button after a rerun cycle.
    """
    active_conn = get_conn()   # recover connection if global handle was lost
    if st.session_state.get("sheets_error") or active_conn is None:
        return

    with st.spinner("🚀 Running Automated Market Scan..."):
        # 1. Portfolio Scan
        p_df = load_sheet_data("Portfolio", ["Ticker", "Buy_Price", "Quantity", "Signal"])
        if not p_df.empty:
            for idx, row in p_df.iterrows():
                try:
                    ticker = sanitize_ticker(row["Ticker"])
                    df = fetch_ohlcv(ticker)
                    if not df.empty:
                        df = compute_indicators(df)
                        current_price = df["Close"].iloc[-1]
                        s1 = df["Support_1"].iloc[-1]
                        if current_price < s1:
                            p_df.at[idx, "Signal"] = "🚨 URGENT SELL"
                        else:
                            p_df.at[idx, "Signal"] = "✅ HOLD"
                except: pass
            save_sheet_data("Portfolio", p_df, ["Ticker", "Buy_Price", "Quantity", "Signal"])

        # 2. Watchlist Scan
        w_df = load_sheet_data("Watchlist", ["Ticker", "Signal"])
        if not w_df.empty:
            for idx, row in w_df.iterrows():
                try:
                    ticker = sanitize_ticker(row["Ticker"])
                    df = fetch_ohlcv(ticker)
                    if not df.empty:
                        df = compute_indicators(df)
                        label, color, _ = get_market_condition(df)
                        if "SAFE" in label:
                            w_df.at[idx, "Signal"] = "🔥 BUY NOW"
                            st.toast(f"🚨 Alert: {ticker} is in the Buy Zone!")
                        else:
                            w_df.at[idx, "Signal"] = "Neutral"
                except: pass
            save_sheet_data("Watchlist", w_df, ["Ticker", "Signal"])

        # 3. Log to ScanHistory — only when connection is confirmed active
        if get_conn() is not None:
            try:
                sig_count = (
                    len(p_df[p_df["Signal"] == "🚨 URGENT SELL"])
                    + len(w_df[w_df["Signal"] == "🔥 BUY NOW"])
                )
                now_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                h_df = load_sheet_data("ScanHistory", ["Window", "Timestamp", "SignalCount"])
                new_log = pd.DataFrame([{"Window": "Auto/Manual", "Timestamp": now_ts, "SignalCount": sig_count}])
                h_df = pd.concat([h_df, new_log], ignore_index=True)
                save_sheet_data("ScanHistory", h_df, ["Window", "Timestamp", "SignalCount"])
            except Exception:
                pass


def run_scheduled_scan():
    """Check if current time matches a Decision Window and trigger scan.

    Metadata reads/writes are gated behind an active-connection check so
    a mid-session auth drop never corrupts the Metadata sheet.
    """
    active_conn = get_conn()
    if st.session_state.get("sheets_error") or active_conn is None:
        return

    now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    current_date_str = now.strftime("%Y-%m-%d")

    # Metadata read — only proceed if connection is confirmed active
    meta_df = load_sheet_data("Metadata", ["Key", "Value"])
    last_scan_val = "None"
    if not meta_df.empty and "last_scan_time" in meta_df["Key"].values:
        last_scan_val = str(meta_df.loc[meta_df["Key"] == "last_scan_time", "Value"].values[0])

    # 1. First-Load / Empty History Fail-Safe
    if last_scan_val == "None":
        if st.session_state.get("lock_init"): return
        st.session_state["lock_init"] = True
        background_batch_scan()
        # Re-check connection after scan (quota sleep may have elapsed)
        if get_conn() is not None:
            sync_now = datetime.now().strftime("%I:%M %p")
            new_meta = pd.DataFrame([
                {"Key": "last_scan_time", "Value": f"{current_date_str}_INIT"},
                {"Key": "last_sync_actual", "Value": sync_now},
            ])
            save_sheet_data("Metadata", new_meta, ["Key", "Value"])
        return

    # 2. Daily Schedule Loop
    for window in reversed(SCAN_WINDOWS):
        if current_time_str >= window:
            window_scan_key = f"{current_date_str}_{window}"
            if last_scan_val != window_scan_key:
                if st.session_state.get(f"lock_{window_scan_key}"): continue
                st.session_state[f"lock_{window_scan_key}"] = True
                background_batch_scan()
                # Re-check connection before writing Metadata
                if get_conn() is not None:
                    sync_now = datetime.now().strftime("%I:%M %p")
                    new_meta = pd.DataFrame([
                        {"Key": "last_scan_time", "Value": window_scan_key},
                        {"Key": "last_sync_actual", "Value": sync_now},
                    ])
                    save_sheet_data("Metadata", new_meta, ["Key", "Value"])
                break


def render_status_hub():
    """📡 Display high-visibility Scan Status Hub UI."""
    if st.session_state.get("sheets_error") or get_conn() is None:
        # Show verbose offline reason so user can diagnose the connection failure
        err_msg = st.session_state.get("sheets_error_msg", "Unknown connection error")
        st.markdown(
            "<div style='color: #888; font-size: 0.85rem; padding-bottom: 4px;'>"
            "⚠️ <strong>System in Offline Mode</strong> — Direct Analysis Only"
            "</div>",
            unsafe_allow_html=True,
        )
        st.error(f"Google Sheets Connection Error: {err_msg}")

        # ── Retry Connection button ───────────────────────────────────
        if st.button("🔁 Retry Connection", key="retry_conn_btn"):
            # Clear the cached resource so the next call rebuilds the handshake
            st.cache_resource.clear()
            st.session_state["sheets_error"] = False
            st.session_state.pop("sheets_error_msg", None)
            st.rerun()
        return

    # Load All Data required for summary
    meta_df = load_sheet_data("Metadata", ["Key", "Value"])
    p_df = load_sheet_data("Portfolio", ["Ticker", "Signal"])
    w_df = load_sheet_data("Watchlist", ["Ticker", "Signal"])
    nifty_price, nifty_pct = fetch_nifty_baseline()

    # Defaults
    now = datetime.now()
    is_weekend = now.weekday() in [5, 6]
    window_label = (
        "📡 Initializing System..."
        if not meta_df.empty
        and meta_df.loc[meta_df["Key"] == "last_scan_time", "Value"].values[0] == "None"
        else "No Scans Today"
    )
    sync_time = "N/A"
    weekend_tag = ""

    # Weekend Auto-Fill Logic
    if is_weekend:
        window_label = "15:15 Final Scan (Friday Close)"
        weekend_tag = (
            "<div style='font-size: 0.75rem; color: #FFD700; margin-top: 2px;'>"
            "🗓️ Weekend Mode: Showing Friday Close</div>"
        )

    # Parse Metadata
    if not meta_df.empty:
        l_window = meta_df.loc[meta_df["Key"] == "last_scan_time", "Value"]
        if not l_window.empty and pd.notna(l_window.iloc[0]) and "_" in str(l_window.iloc[0]):
            w_time = str(l_window.iloc[0]).split("_")[-1]
            window_label = f"{w_time} Decision Zone"

        l_sync = meta_df.loc[meta_df["Key"] == "last_sync_actual", "Value"]
        if not l_sync.empty and pd.notna(l_sync.iloc[0]):
            sync_time = str(l_sync.iloc[0])

    # Clean Data ─ Filter out phantom rows (blanks/NaNs)
    if not p_df.empty:
        p_df = p_df[p_df["Ticker"].astype(str).str.strip() != ""]
        p_df = p_df[p_df["Ticker"].astype(str).str.lower() != "nan"]

    if not w_df.empty:
        w_df = w_df[w_df["Ticker"].astype(str).str.strip() != ""]
        w_df = w_df[w_df["Ticker"].astype(str).str.lower() != "nan"]

    # Count Signals
    sell_alerts = len(p_df[p_df["Signal"] == "🚨 URGENT SELL"]) if not p_df.empty else 0
    buy_alerts = len(w_df[w_df["Signal"] == "🔥 BUY NOW"]) if not w_df.empty else 0

    # ── CSS (injected once) ──────────────────────────────────────────
    st.markdown(
        """
        <style>
        .status-hub {
            background-color: #1E1E1E;
            border: 1px solid #333;
            border-left: 4px solid #00D4AA;
            padding: 1rem;
            border-radius: 0.5rem;
            margin-bottom: 1rem;
        }
        .status-header { font-size: 0.85rem; color: #888; text-transform: uppercase; letter-spacing: 1px; }
        .status-val    { font-weight: bold; font-size: 1.1rem; color: #00D4AA; }
        .signal-indicator { font-size: 1.2rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Hub Panel ────────────────────────────────────────────────────
    # Build the variable sub-blocks first so the f-string stays clean
    sync_block = (
        f"<div class='status-header'>⏱️ Sync Time</div>"
        f"<div class='status-val'>Triggered at {sync_time}</div>"
    )
    
    nifty_color = "#00D4AA" if nifty_pct >= 0 else "#FF4B4B"
    macro_block = (
        f"<div class='status-header'>📈 NIFTY 50</div>"
        f"<div class='status-val'>{nifty_price:,.2f} <span style='color: {nifty_color}; font-size: 0.85rem;'>({nifty_pct:+.2f}%)</span></div>"
    )

    signals_block = (
        f"<div class='status-header'>🔥 Live Signals</div>"
        f"<div class='status-val'>"
        f"<span class='signal-indicator'>🟢</span> {buy_alerts} Buy Alert&nbsp;|&nbsp;"
        f"<span class='signal-indicator'>🚨</span> {sell_alerts} Sell Alerts"
        f"</div>"
    )

    hub_html = f"""
    <div class="status-hub">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <div class="status-header">📡 Last Scan Window</div>
                <div class="status-val">{window_label}</div>{weekend_tag}
            </div>
            <div>{macro_block}</div>
            <div>{sync_block}</div>
            <div style="text-align:right;">{signals_block}</div>
        </div>
    </div>
    """
    st.markdown(hub_html.replace('\n', ' '), unsafe_allow_html=True)

    # ── Force Scan Button (unique key prevents duplicate-widget error) ──
    if st.button(
        "🔄 Force System Scan",
        key="force_scan_hub_btn",
        use_container_width=True,
    ):
        try:
            with st.spinner("🚀 Stabilizing Connection..."):
                time.sleep(1)          # Safety delay — lets prior writes settle
            background_batch_scan()
            sync_now = datetime.now().strftime("%I:%M %p")
            new_meta = pd.DataFrame([
                {"Key": "last_scan_time", "Value": f"{now.strftime('%Y-%m-%d')}_MANUAL"},
                {"Key": "last_sync_actual", "Value": sync_now},
            ])
            save_sheet_data("Metadata", new_meta, ["Key", "Value"])
            st.toast("✅ Manual System Scan Successful!")
            st.rerun()
        except Exception as e:
            st.error(f"❌ Force Scan Failed: {e}")


@st.cache_data(ttl=300)
def fetch_nifty_baseline() -> tuple[float, float]:
    """Fetch recent Nifty 50 (^NSEI) data and return (last_close, pct_change)."""
    try:
        nifty = yf.download("^NSEI", period="5d", interval="1d", progress=False, auto_adjust=True)
        if nifty.empty: return 0.0, 0.0
        latest_close = float(nifty["Close"].iloc[-1])
        prev_close = float(nifty["Close"].iloc[-2]) if len(nifty) > 1 else latest_close
        pct_change = ((latest_close - prev_close) / prev_close) * 100
        return round(latest_close, 2), round(pct_change, 2)
    except Exception:
        return 0.0, 0.0


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
def summarize_with_gemini(data_dict: dict, company: str, api_key: str) -> str:
    """Send quantitative data to Gemini and return a 2-bullet technical summary."""
    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        prompt = (
            f"Act as a quantitative trading assistant. Analyze this data for {company}:\n"
            f"{data_dict}\n"
            "Provide a 2-bullet-point technical summary. "
            "Bullet 1: Assess the entry risk and momentum. "
            "Bullet 2: Highlight any fundamental or volume red/green flags. "
            "Keep it extremely concise, objective, and strictly based on these numbers."
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
    
    # 3. Vol (Volume Surge) — direction-aware
    # High volume only counts BULLISH if the candle closes green.
    # High volume on a red candle = Institutional Distribution = 0 points.
    v_points = 0
    vol_today = latest.get("Volume", 1)
    vol_20sma = latest.get("Vol_20SMA", 1)
    if pd.isna(vol_20sma) or vol_20sma == 0: vol_20sma = 1
    v_ratio = vol_today / vol_20sma
    is_green = latest.get("Close", 0) >= latest.get("Open", 0)  # Green candle = accumulation
    if v_ratio >= 1.5 and is_green: v_points = 2
    elif v_ratio >= 1.0 and is_green: v_points = 1
    # Red candle with high volume: v_points stays 0 (Distribution)

    # 4. Funda
    f_points = 0
    if fundamentals["roce"] > 15: f_points += 1
    if fundamentals["debt_to_equity"] < 0.5: f_points += 1
    
    total_score = s_points + t_points + v_points + f_points
    return total_score, t_points, v_points, s_points, f_points


def get_market_condition(df):
    """MASTER Logic: Unified RSI (Momentum) + Entry Risk (Structure) scoring."""
    if df.empty or len(df) < 14:
        return "⚪ N/A", "gray", 50
    
    # 1. RSI(14) - Momentum
    rsi_vals = ta.rsi(df['Close'], length=14)
    rsi = rsi_vals.iloc[-1] if not pd.isna(rsi_vals.iloc[-1]) else 50
    
    # 2. Risk - Structure
    close = df['Close'].iloc[-1]
    s1 = df['Support_1'].iloc[-1]
    r1 = df['Resistance_1'].iloc[-1]
    
    # Calc Risk Percentage
    if r1 > s1:
        risk_pct = ((close - s1) / (r1 - s1)) * 100
    else:
        risk_pct = 50
    
    # Logic Hierarchy
    if rsi < 30: return "🔵 OVERSOLD", "blue", risk_pct
    if rsi > 70: return "🟣 OVERBOUGHT", "purple", risk_pct
    if risk_pct < 35: return "🟢 SAFE", "#00D4AA", risk_pct
    if risk_pct > 75: return "🔴 OVEREXTENDED", "#FF4B4B", risk_pct
    return "🟡 FAIR", "#FFD700", risk_pct


def render_control_center():
    # --- Batch Processor (Full Width) ---
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
                                raw_s = ((b_close - b_sup1) / (b_res1 - b_sup1)) * 100
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
                            # Direction-aware: only award points on a green (accumulation) candle
                            is_b_green = b_df["Close"].iloc[-1] >= b_df["Open"].iloc[-1]
                            if v_ratio >= 1.5 and is_b_green: m_score += 2
                            elif v_ratio >= 1.0 and is_b_green: m_score += 1
                            # Red candle + high volume = Distribution → 0 points

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
    st.markdown("<br><br>", unsafe_allow_html=True)

    # --- Batch Results (Full Width) ---
    if "batch_results" in st.session_state and st.session_state["batch_results"] is not None:
        st.subheader("🔥 Watchlist Batch Results")
        b_results = st.session_state["batch_results"]
        if not b_results.empty:
            # Header — wider ratios for full-screen display
            bh_col = st.columns([3, 1.5, 1.5, 1.5, 2.5, 2])
            bh_col[0].markdown("**Ticker**")
            bh_col[1].markdown("**Price**")
            bh_col[2].markdown("**Support**")
            bh_col[3].markdown("**Safety**")
            bh_col[4].markdown("**Rating**")
            bh_col[5].markdown("**Action**")

            for idx, row in b_results.iterrows():
                rb_col = st.columns([3, 1.5, 1.5, 1.5, 2.5, 2])
                rb_col[0].write(row["Ticker"])
                rb_col[1].write(f"₹{row['Price']}")
                rb_col[2].write(f"₹{row['Support1']}")
                rb_col[3].write(row["Safety Score"])
                rb_col[4].write(row["Master Rating"])
                if rb_col[5].button("Analyze", key=f"b_an_{row['Ticker']}_{idx}", on_click=set_search_ticker, args=(row["Ticker"],)):
                    pass
        else:
            st.info("❌ No stocks passed the scan.")
    else:
        st.markdown("<p style='color: gray; padding-top: 10px;'>Results will appear here after scanning.</p>", unsafe_allow_html=True)


# ===================================================================
# INITIALIZE SESSION STATE
# ===================================================================
# INITIALIZE SESSION STATE (Moved to top level file)

st.markdown("<h1><span class='icon-3d'>📈</span> Stock Market Analysis Dashboard</h1>", unsafe_allow_html=True)

col_sym, col_tick = st.columns([7, 3])
with col_sym:
    # Warp Search Bar Sync - Streamlit binds this widget to st.session_state['search_input']
    search_query = st.text_input(
        "Search Company Name or Ticker",
        placeholder="e.g., Narmada, RELIANCE, TCS",
        key="search_input",
    )

# --- 📡 SCAN STATUS HUB — Control Center (above Portfolio/Watchlist, below Search Bar) ---
try:
    render_status_hub()
except Exception as e:
    st.error(f"⚠️ Status Hub Sync Error: {e}")


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
            # Candle direction determines Accumulation vs Distribution label
            is_green = latest.get("Close", 0) >= latest.get("Open", 0)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### 🏥 Fundamental & Volume Health")
            h1, h2, h3, h4, h5 = st.columns(5)
            h1.metric("ROCE (Efficiency)", f"{roce:.2f}%")
            h2.metric("Debt-to-Equity", f"{debt_to_equity:.2f}")
            h3.metric("Current Volume", f"{int(vol_today_raw):,}")
            h4.metric("20-Day Avg Vol", f"{int(vol_20sma_raw):,}")
            if v_ratio_raw >= 1.5 and is_green:
                surge_label = "🔥 Inst. Accumulation"
                surge_color = "normal"       # renders green ↑
            elif v_ratio_raw >= 1.5 and not is_green:
                surge_label = "🩸 Inst. Distribution"
                surge_color = "inverse"      # renders red ↓
            else:
                surge_label = "Normal Volume"
                surge_color = "off"          # neutral grey
            h5.metric("Volume Surge", f"{v_ratio_raw:.2f}x", delta=surge_label, delta_color=surge_color)

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
                clean_p = sanitize_ticker(full_ticker)
                w_df = load_sheet_data("Watchlist", ["Ticker"])
                
                if not w_df.empty and clean_p in w_df["Ticker"].values:
                    st.button("✅ In Watchlist", disabled=True, use_container_width=True)
                else:
                    if st.button("➕ Add to Watchlist", use_container_width=True):
                        # Reload to ensure we have latest if added via other means
                        w_df = load_sheet_data("Watchlist", ["Ticker"])
                        if clean_p not in w_df["Ticker"].values:
                            new_row = pd.DataFrame([{"Ticker": clean_p}])
                            w_df = pd.concat([w_df, new_row], ignore_index=True)
                            save_sheet_data("Watchlist", w_df, ["Ticker"])
                            st.success(f"Added {clean_p} to Watchlist!")
                            st.rerun()

            # --- Visual Indicators (Gauge) ---
            c_gauge, c_mom = st.columns(2)
            with c_gauge:
                cond_label, cond_color, cond_val = get_market_condition(df)
                g_fig = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=cond_val,
                    number={'font': {'color': cond_color}},
                    title={'text': f"Entry Context: {cond_label}", 'font': {'size': 20, 'color': "white"}},
                    gauge={
                        'axis': {'range': [None, 100]},
                        'bar': {'color': cond_color},
                        'steps': [
                            {'range': [0, 35], 'color': 'rgba(0, 212, 170, 0.3)'},
                            {'range': [35, 75], 'color': 'rgba(255, 215, 0, 0.3)'},
                            {'range': [75, 100], 'color': 'rgba(255, 75, 75, 0.3)'}
                        ]
                    }
                ))
                g_fig.update_layout(height=260, margin=dict(l=20, r=20, t=50, b=20), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={'color': "white"})
                st.plotly_chart(g_fig, use_container_width=True)
                st.markdown(f"<p style='text-align: center; color: gray;'><span style='color: blue;'>Oversold</span> | <span style='color: #00D4AA;'>Safe</span> | <span style='color: #FFD700;'>Fair</span> | <span style='color: #FF4B4B;'>Overextended</span> | <span style='color: purple;'>Overbought</span></p>", unsafe_allow_html=True)
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

            # --- AI Quantitative Summary Section ---
            st.subheader("📊 AI Quantitative Summary")
            saved_key = st.session_state.get("gemini_key")
            if saved_key:
                summary_key = f"ai_summary_{full_ticker}"
                # Force refresh if ticker changed or summary missing
                if summary_key not in st.session_state or st.session_state[summary_key] is None:
                    if st.button("Generate AI Quantitative Summary"):
                        with st.spinner("Generating..."):
                            data_dict = {
                                "Price": latest['Close'],
                                "Support": support_val,
                                "Master Score": f"{total_score}/8",
                                "Condition": cond_label,
                                "Volume Surge": f"{v_ratio_raw:.2f}x",
                                "ROCE": f"{roce:.2f}%"
                            }
                            summary = summarize_with_gemini(data_dict, company_name, saved_key)
                            st.session_state[summary_key] = summary
                            st.rerun()
                else:
                    st.markdown(f'<div class="story-section">{st.session_state[summary_key]}</div>', unsafe_allow_html=True)
            else:
                st.info("Please enter a Gemini API Key in the settings below to enable AI summaries.")

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
                        # Row 1: Max Risk & Risk Per Share
                        r1_c1, r1_c2 = st.columns(2)
                        r1_c1.metric("Max Risk (1%)", f"₹{max_risk:,.2f}")
                        r1_c2.metric("Risk Per Share", f"₹{risk_per_share:,.2f}")
                        
                        st.markdown("<div style='height: 5px;'></div>", unsafe_allow_html=True)
                        
                        # Row 2: Shares & Capital Deployed
                        r2_c1, r2_c2 = st.columns(2)
                        r2_c1.metric("Shares to Buy", f"{shares_to_buy:,}")
                        r2_c2.metric("Capital Deployed", f"₹{total_deployed:,.2f}")
                        
                        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                        
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

# ── Live Portfolio (Full Width) ───────────────────────────────────
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
                    new_row = pd.DataFrame([{"Ticker": clean_t, "Buy_Price": m_price, "Quantity": m_qty, "Signal": "✅ HOLD"}])
                    p_df = pd.concat([p_df, new_row], ignore_index=True)
                    st.success(f"Added {clean_t} to Portfolio!")

                save_sheet_data("Portfolio", p_df, ["Ticker", "Buy_Price", "Quantity"])
                st.rerun()

p_df = load_sheet_data("Portfolio", ["Ticker", "Buy_Price", "Quantity"])
if not p_df.empty:
    # 9-column header ─ Ticker | P&L | Status | Master | T1 Scale-Out | Trail Stop | Signal | Action | Del
    h_col = st.columns([2.5, 1, 1.2, 1, 1.5, 1.5, 1.2, 1.2, 0.5])
    h_col[0].markdown("**Ticker**")
    h_col[1].markdown("**P&L %**")
    h_col[2].markdown("**Status**")
    h_col[3].markdown("**Master**")
    h_col[4].markdown("**🎯 T1 (Book 50%)**")
    h_col[5].markdown("**🛡️ Trail Stop**")
    h_col[6].markdown("**Signal**")
    h_col[7].markdown("**Action**")
    h_col[8].markdown("**Del**")

    for idx, row in p_df.iterrows():
        ticker = row["Ticker"]
        if not ticker or pd.isna(ticker) or str(ticker).strip() == '': continue
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

                # ── Exit Status (Trailing Stop = dynamic S1) ──────────────────
                if cmp < s1:
                    status, color = "🚨 SELL — Below Trail Stop", "#FF4B4B"
                elif score < 4:
                    status, color = "⚠️ WEAK (Watch)", "#FFD700"
                else:
                    status, color = "✅ HOLD — Trend Active", "#00D4AA"

                # ── T1: 1:3 R:R Scale-Out Target ───────────────────────────
                # Risk = entry − initial stop (S1 at time of buy = current S1 proxy).
                # We use current S1 as the trailing stop, so T1 is still a useful
                # forward reference even as the stock moves.
                p_risk = buy_price - s1
                if p_risk > 0:
                    p_t1 = buy_price + (p_risk * 3)
                    t1_str = f"₹{p_t1:,.2f}"
                    # Colour T1 green if already hit, grey otherwise
                    t1_color = "#00D4AA" if cmp >= p_t1 else "#AAAAAA"
                else:
                    t1_str, t1_color = "N/A", "#AAAAAA"

                # ── Trailing Stop = live dynamic S1 ────────────────────────
                trail_str = f"₹{s1:,.2f}"

                r_col = st.columns([2.5, 1, 1.2, 1, 1.5, 1.5, 1.2, 1.2, 0.5])
                r_col[0].write(clean_ticker)
                r_col[1].write(f"{pnl:+.2f}%")
                r_col[2].markdown(f"<span style='color:{color}; font-weight:bold;'>{status}</span>", unsafe_allow_html=True)
                r_col[3].write(f"{score}/8")
                r_col[4].markdown(f"<span style='color:{t1_color}; font-weight:bold;'>{t1_str}</span>", unsafe_allow_html=True)
                r_col[5].write(trail_str)
                r_col[6].write(str(row.get("Signal", "✅ HOLD")))
                if r_col[7].button("Analyze", key=f"p_an_{clean_ticker}_{idx}", on_click=set_search_ticker, args=(clean_ticker,)):
                    pass
                if r_col[8].button("🗑️", key=f"p_del_{clean_ticker}_{idx}"):
                    p_df = p_df.drop(idx)
                    save_sheet_data("Portfolio", p_df, ["Ticker", "Buy_Price", "Quantity", "Signal"])
                    st.rerun()
            else:
                r_col = st.columns([2.5, 1, 1.5, 1, 1.5, 1.5, 1.2, 1.2, 0.5])
                r_col[0].write(f"⚠️ {clean_ticker}")
                for i in range(1, 7): r_col[i].write("N/A")
                r_col[7].write("")
                if r_col[8].button("🗑️", key=f"p_del_err_{clean_ticker}_{idx}"):
                    p_df = p_df.drop(idx)
                    save_sheet_data("Portfolio", p_df, ["Ticker", "Buy_Price", "Quantity"])
                    st.rerun()
        except Exception:
            st.error(f"Error processing {clean_ticker}")
else:
    st.info("Portfolio is empty. Add trades manually or from the calculator.")

st.markdown("<br><br>", unsafe_allow_html=True)

# ── Watchlist (Full Width) ───────────────────────────────────────
w_input = ""  # Defined here to prevent NameError
st.subheader("⭐ Watchlist")
if st.session_state.get("sheets_error"):
    st.error("⚠️ Google Sheets Connection Error: Watchlist management is temporarily unavailable.")
else:
    w_input = st.text_input("Add Ticker to Watchlist", placeholder="e.g. TCS (Press Enter)", key="w_ticker_input")

w_df = load_sheet_data("Watchlist", ["Ticker", "Signal"])
if w_input:
    clean_w = sanitize_ticker(w_input)
    if clean_w not in w_df["Ticker"].values:
        new_row = pd.DataFrame([{"Ticker": clean_w, "Signal": "Neutral"}])
        w_df = pd.concat([w_df, new_row], ignore_index=True)
        save_sheet_data("Watchlist", w_df, ["Ticker", "Signal"])
        st.success(f"Added {clean_w} to Watchlist!")
    else:
        st.info(f"{clean_w} is already in Watchlist.")

    # Reset via rerun
    st.rerun()

if not w_df.empty:
    # 9-column header ─ Ticker | Price | Rating | Condition | Signal | S1 Stop | T1 Target | Analyze | Del
    wh_col = st.columns([2.5, 1, 0.8, 1.5, 1.2, 1.2, 1.5, 1, 0.5])
    wh_col[0].markdown("**Ticker**")
    wh_col[1].markdown("**Price**")
    wh_col[2].markdown("**Rating**")
    wh_col[3].markdown("**Condition**")
    wh_col[4].markdown("**Signal**")
    wh_col[5].markdown("**🛡️ S1 (Runner)**")
    wh_col[6].markdown("**🎯 T1 (Book 50%)**")
    wh_col[7].markdown("**Analyze**")
    wh_col[8].markdown("**🗑️**")

    # Wrapped Container with Throttle to prevent errors
    with st.container():
        for idx, row in w_df.iterrows():
            time.sleep(0.05) # Minor throttle for yfinance
            ticker = row["Ticker"]
            if not ticker or pd.isna(ticker) or str(ticker).strip() == '': continue
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

                    w_cmp = w_data['Close'].iloc[-1]
                    w_s1 = w_data['Support_1'].iloc[-1]

                    price_str = f"₹{w_cmp:,.2f}"
                    s1_str = f"₹{w_s1:,.2f}"

                    # Unified Marker Logic
                    w_label, w_color, _ = get_market_condition(w_data)

                    # ── T1: 1:3 R:R prospective entry target ─────────────────────
                    # "If I buy NOW at CMP, with S1 as my stop, where is 1:3?"
                    w_risk = w_cmp - w_s1
                    if w_risk > 0:
                        w_t1 = w_cmp + (w_risk * 3)
                        w_t1_str = f"🎯 ₹{w_t1:,.2f}"
                        w_t1_color = "#00D4AA"
                    else:
                        w_t1_str, w_t1_color = "N/A", "#AAAAAA"

                    wr_col = st.columns([2.5, 1, 0.8, 1.5, 1.2, 1.2, 1.5, 1, 0.5])
                    wr_col[0].write(clean_ticker)
                    wr_col[1].write(price_str)
                    wr_col[2].write(f"{scr_w}/8")
                    wr_col[3].markdown(f"<span style='color:{w_color};'>{w_label}</span>", unsafe_allow_html=True)
                    wr_col[4].write(str(row.get("Signal", "Neutral")))
                    wr_col[5].write(s1_str)
                    wr_col[6].markdown(f"<span style='color:{w_t1_color}; font-weight:bold;'>{w_t1_str}</span>", unsafe_allow_html=True)
                    if wr_col[7].button("Analyze", key=f"w_an_{clean_ticker}_{idx}", on_click=set_search_ticker, args=(clean_ticker,)):
                        pass
                    if wr_col[8].button("🗑️", key=f"w_del_{clean_ticker}_{idx}"):
                        w_df = w_df.drop(idx)
                        save_sheet_data("Watchlist", w_df, ["Ticker", "Signal"])
                        st.rerun()
                else:
                    wr_col = st.columns([2.5, 1, 0.8, 1.5, 1.2, 1.2, 1.5, 1, 0.5])
                    wr_col[0].write(f"⚠️ {clean_ticker}")
                    for i in range(1, 8): wr_col[i].write("N/A")
                    if wr_col[8].button("🗑️", key=f"w_del_err_{clean_ticker}_{idx}"):
                        w_df = w_df.drop(idx)
                        save_sheet_data("Watchlist", w_df, ["Ticker"])
                        st.rerun()
            except Exception:
                st.error(f"Error processing {clean_ticker}")
else:
    st.info("Watchlist is empty. Search and pin stocks or add manually.")

# ===================================================================
# BATCH ENGINE — Persistent Bottom Layer (Optimized Side-by-Side Split)
# ===================================================================
st.markdown("---")
render_control_center()

# 📝 Batch Trade Plan Exporter
if "batch_results" in st.session_state and st.session_state["batch_results"] is not None:
    st.markdown("---")
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

# --- 🚀 SCHEDULED SCAN (deferred so entire UI renders first) ---
# Placed here so the Search Bar, Status Hub, Portfolio and Watchlist
# are all painted before any heavy background fetching begins.
try:
    run_scheduled_scan()
except Exception as _scan_err:
    pass  # Non-blocking: scan failure must never kill the page

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
