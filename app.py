"""
Stock Market Analysis Dashboard
A free, full-featured stock analysis tool for Indian markets (NSE/BSE).
Tech: Streamlit · yfinance · pandas_ta · Plotly · GNews · Gemini Free Tier.
"""

import io
import os
import math
import time
import pytz
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

# Project root — anchors all file I/O to the directory containing app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Global Timezone — all timestamps forced to IST
IST = pytz.timezone('Asia/Kolkata')

# ---------------------------------------------------------------------------
# Page configuration — MUST be the very first Streamlit command
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Stock Market Analysis Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
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
if "alert_history" not in st.session_state:
    st.session_state["alert_history"] = []
if "seen_alerts" not in st.session_state:
    st.session_state["seen_alerts"] = set()
if "show_journal" not in st.session_state:
    st.session_state["show_journal"] = False

def log_alert(msg, icon="🔔"):
    """Logs alert to persistent history and triggers transient toast, with anti-spam."""
    # Automatically strip duplicate icons from the message string
    clean_msg = msg.replace(icon, "").strip()

    # ANTI-SPAM: Only trigger if we haven't seen this exact message in this session
    if clean_msg not in st.session_state["seen_alerts"]:
        now_str = datetime.now(IST).strftime("%d %b %Y, %I:%M %p")

        st.session_state["alert_history"].insert(0, {"time": now_str, "msg": clean_msg, "icon": icon})
        st.session_state["alert_history"] = st.session_state["alert_history"][:50]  # Keep last 50

        # Add to memory cache so it doesn't fire again on the next UI rerun
        st.session_state["seen_alerts"].add(clean_msg)

        st.toast(clean_msg, icon=icon)



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

def format_indian(n, is_price=False):
    """Formats a number into the Indian numbering system (Lakhs/Crores)."""
    if pd.isna(n) or n == 0: return "0.00" if is_price else "0"
    
    sign = "-" if n < 0 else ""
    n = abs(n)
    
    s = str(int(n))
    if len(s) <= 3: 
        res = s
    else:
        last_three = s[-3:]
        remaining = s[:-3]
        
        parts = []
        while len(remaining) > 0:
            parts.append(remaining[-2:])
            remaining = remaining[:-2]
            
        parts.reverse()
        res = ",".join(parts) + "," + last_three
        
    if is_price:
        decimal_part = f"{n:.2f}".split('.')[1]
        return f"{sign}{res}.{decimal_part}"
    return f"{sign}{res}"

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
            conn.create(worksheet="Watchlist", data=pd.DataFrame(columns=["Ticker", "Price", "Rating", "Entry Context", "Trend Strength", "Stop Loss", "Vol Footprint"]))
        
        # 2. Portfolio
        try:
            conn.read(worksheet="Portfolio", ttl=0)
        except Exception:
            conn.create(worksheet="Portfolio", data=pd.DataFrame(columns=["Ticker", "Buy_Price", "Initial_Stop", "Highest_Trail", "Quantity", "Date_Added", "CMP", "RSI_HTML", "T1_HTML", "PCT_HTML", "Vol_Foot", "Verdict_HTML", "_verdict_rank", "_vol_rank"]))

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
            
        # 5. ClosedTrades (Trade Journal)
        try:
            conn.read(worksheet="ClosedTrades", ttl=0)
        except Exception:
            conn.create(worksheet="ClosedTrades", data=pd.DataFrame(columns=["Ticker", "Buy_Date", "Sell_Date", "Buy_Price", "Sell_Price", "Quantity", "PnL_Value", "PnL_Pct", "Exit_State", "Days_Held"]))
            
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
    """Hybrid read: Google Sheets primary, local CSV fallback.

    On every successful Sheets read the data is mirrored to a local CSV so
    the app can keep working even when the Google API is unreachable.
    """
    local_filename = os.path.join(BASE_DIR, f"db_backup_{worksheet}.csv")

    # ── 1. Attempt Primary Read from Google Sheets ──────────────────
    try:
        active_conn = get_conn()
        if active_conn is not None:
            df = active_conn.read(worksheet=worksheet, ttl="10m")
            if df is None or df.empty:
                df = pd.DataFrame(columns=columns)
            else:
                df = df.dropna(how="all")
                for col in columns:
                    if col not in df.columns:
                        df[col] = None
                df = df[columns]

            # ── 2. Save a fresh local mirror copy ──────────────────
            try:
                df.to_csv(local_filename, index=False)
            except Exception:
                pass  # Never let a disk write block the app

            return df
    except Exception as e:
        # ── 3. Fallback: Google is down / quota exceeded ────────────
        try:
            if os.path.exists(local_filename):
                st.warning(
                    f"⚠️ Offline Mode: Using local backup for {worksheet}"
                )
                df = pd.read_csv(local_filename)
                # Ensure all requested columns exist
                for col in columns:
                    if col not in df.columns:
                        df[col] = None
                return df[columns]
        except Exception:
            pass

        # Soft 429 toast so the UI doesn't lock
        if "429" in str(e) or "RATE_LIMIT" in str(e):
            st.toast("⚠️ Google API busy. Using cached data.")
        else:
            st.cache_resource.clear()
            st.session_state["sheets_error"] = True

    # ── 4. Total Failure: return empty shell with correct columns ───
    return pd.DataFrame(columns=columns)


def save_sheet_data(worksheet: str, df: pd.DataFrame, columns: list):
    """Update a worksheet with 3-attempt retry loop, fallback create, and
    automatic local CSV mirroring after every successful write.
    """
    local_filename = os.path.join(BASE_DIR, f"db_backup_{worksheet}.csv")
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

            # ── Auto-Mirror: keep local CSV in sync with Sheets ────
            try:
                df.to_csv(local_filename, index=False)
            except Exception:
                pass  # Never let a disk write block the app

            return
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                if "429" in str(e) or "RATE_LIMIT" in str(e):
                    # Soft Error: Don't LOCK the UI, don't clear the conn cache
                    st.toast(f"⚠️ Sync delayed for {worksheet} due to API limits.")
                else:
                    # Hard Error: LOCK the UI and clear conn cache
                    st.cache_resource.clear()
                    st.session_state["sheets_error"] = True
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
        p_schema = ["Ticker", "Buy_Price", "Initial_Stop", "Highest_Trail", "Quantity", "Date_Added", "CMP", "RSI_HTML", "T1_HTML", "PCT_HTML", "Vol_Foot", "Verdict_HTML", "_verdict_rank", "_vol_rank"]
        p_df = load_sheet_data("Portfolio", p_schema)
        if not p_df.empty:
            for idx, row in p_df.iterrows():
                try:
                    ticker = sanitize_ticker(row["Ticker"])
                    df = fetch_ohlcv(ticker)
                    if not df.empty:
                        df = compute_indicators(df)
                        funda = fetch_fundamentals(ticker)
                        score, t_pts, v_pts, s_pts, f_pts, str_pts, sma_pts, def_pts = calculate_master_score(df, funda)
                        
                        s1 = df["Active_Support"].iloc[-1]
                        cmp_val = df["Close"].iloc[-1]
                        buy_price = float(row.get("Buy_Price", 0))
                        init_stop = float(row.get("Initial_Stop", buy_price * 0.9))
                        high_trail = float(row.get("Highest_Trail", init_stop))
                        
                        # ── Ratchet Logic ────────────
                        if not pd.isna(s1) and s1 > high_trail:
                            log_alert(f"🛡️ PROFIT SECURED: Trailing Stop for {ticker} ratcheted UP to ₹{format_indian(s1, is_price=True)}!", icon="🛡️")
                            high_trail = float(s1)
                            p_df.at[idx, "Highest_Trail"] = high_trail

                        # ── UI Data Generation ────────────
                        # 1. Price
                        p_df.at[idx, "CMP"] = round(float(cmp_val), 2)
                        
                        # 2. RSI HTML
                        rsi_vals = ta.rsi(df['Close'], length=14)
                        rsi = rsi_vals.iloc[-1] if not rsi_vals.empty and not pd.isna(rsi_vals.iloc[-1]) else 50
                        rsi_str = f"{rsi:.1f}"
                        if rsi >= 70: rsi_html = f"<span style='color:#FF4B4B; font-weight:bold;'>{rsi_str} (OB)</span>"
                        elif rsi <= 30: rsi_html = f"<span style='color:#00D4AA; font-weight:bold;'>{rsi_str} (OS)</span>"
                        else: rsi_html = f"<span style='color:#AAAAAA;'>{rsi_str}</span>"
                        p_df.at[idx, "RSI_HTML"] = rsi_html
                        
                        # 3. Vol Footprint
                        vol_today = df["Volume"].iloc[-1]
                        vol_20sma = df["Vol_20SMA"].iloc[-1] if not pd.isna(df["Vol_20SMA"].iloc[-1]) and df["Vol_20SMA"].iloc[-1] > 0 else 1
                        v_ratio = vol_today / vol_20sma
                        is_green = cmp_val >= df["Open"].iloc[-1]
                        if v_ratio >= 1.5 and is_green: vol_foot, vol_rank = "🟢 Accumulation", 2
                        elif v_ratio >= 1.5 and not is_green: vol_foot, vol_rank = "🔴 DISTRIBUTION", 0
                        else: vol_foot, vol_rank = "⚪ Normal", 1
                        p_df.at[idx, "Vol_Foot"] = vol_foot
                        p_df.at[idx, "_vol_rank"] = vol_rank
                        
                        # 4. T1 Target
                        p_risk = buy_price - init_stop
                        if p_risk > 0:
                            p_t1 = buy_price + (p_risk * 3)
                            t1_color = "#00D4AA" if cmp_val >= p_t1 else "#AAAAAA"
                            t1_html = f"<span style='color:{t1_color}; font-weight:bold;'>₹{format_indian(p_t1, is_price=True)}</span>"
                        else: t1_html = "N/A"
                        p_df.at[idx, "T1_HTML"] = t1_html
                        
                        # 5. % to Stop
                        pct_to_stop = ((cmp_val - high_trail) / cmp_val) * 100 if cmp_val > 0 else 0
                        pct_color = "#FF4B4B" if pct_to_stop < 2.0 else "#FFD700" if pct_to_stop < 5.0 else "#00D4AA"
                        p_df.at[idx, "PCT_HTML"] = f"<span style='color:{pct_color}; font-weight:bold;'>{pct_to_stop:.1f}%</span>"
                        
                        # 6. Verdict
                        stop_zone = high_trail * 0.99
                        if cmp_val < stop_zone and v_ratio > 0.8: verdict, v_color, v_rank = "🔴 SELL (Breakdown)", "#FF4B4B", 0
                        elif cmp_val < stop_zone and v_ratio <= 0.8: verdict, v_color, v_rank = "🟡 WATCH (Low Vol Test)", "#FFD700", 3
                        elif v_ratio >= 1.5 and not is_green and rsi > 65: verdict, v_color, v_rank = "🔴 SELL (Exhaustion)", "#FF4B4B", 1
                        elif score < 4: verdict, v_color, v_rank = "🟡 TRIM (Weakening)", "#FFD700", 2
                        else: verdict, v_color, v_rank = "🟢 HOLD", "#00D4AA", 4
                        p_df.at[idx, "Verdict_HTML"] = f"<span style='color:{v_color}; font-weight:bold;'>{verdict}</span>"
                        p_df.at[idx, "_verdict_rank"] = v_rank
                        
                        if "🔴 SELL" in verdict or "🟡 TRIM" in verdict:
                            log_alert(f"⚠️ PORTFOLIO ALERT: {verdict} on {ticker}", icon="🚨")

                except: pass

            save_sheet_data("Portfolio", p_df, p_schema)

        # 2. Watchlist Scan
        w_schema = ["Ticker", "Price", "Rating", "Entry Context", "Trend Strength", "Stop Loss", "Vol Footprint"]
        w_df = load_sheet_data("Watchlist", w_schema)
        if not w_df.empty:
            for idx, row in w_df.iterrows():
                try:
                    ticker = sanitize_ticker(row["Ticker"])
                    df = fetch_ohlcv(ticker)
                    if not df.empty:
                        df = compute_indicators(df)
                        funda = fetch_fundamentals(ticker)
                        score, t_pts, v_pts, s_pts, f_pts, str_pts, sma_pts, def_pts = calculate_master_score(df, funda)
                        label, _, _ = get_market_condition(df)
                        latest = df.iloc[-1]
                        support_val = latest.get("Active_Support", latest["Close"])

                        # Price
                        w_df.at[idx, "Price"] = round(float(latest["Close"]), 2)

                        # Rating
                        if score >= 7: w_rating = "STRONG BUY"
                        elif score >= 5: w_rating = "MODERATE BUY"
                        elif score >= 3: w_rating = "WATCHLIST / HOLD"
                        else: w_rating = "AVOID"
                        w_df.at[idx, "Rating"] = w_rating

                        # Vol Footprint
                        v_rat = latest["Volume"] / (latest["Vol_20SMA"] if latest["Vol_20SMA"] > 0 else 1)
                        is_gr = latest["Close"] >= latest["Open"]
                        foot = "🟢 Accumulation" if v_rat >= 1.5 and is_gr else "🔴 DISTRIBUTION" if v_rat >= 1.5 else "⚪ Normal"
                        w_df.at[idx, "Vol Footprint"] = foot

                        if w_rating == "STRONG BUY" or "🟢 Accumulation" in foot:
                            log_alert(f"🔥 Watchlist Alert: Strong setup on {ticker}", icon="🔥")

                        # Entry Context
                        context_str = str(label).strip()
                        for prefix in ["🔵 ", "🟣 ", "🟢 ", "🔴 ", "🟡 ", "🚀 "]:
                            context_str = context_str.replace(prefix, "")
                        w_df.at[idx, "Entry Context"] = context_str

                        # Trend Strength
                        w_df.at[idx, "Trend Strength"] = f"{t_pts}/2"

                        # Stop Loss
                        w_df.at[idx, "Stop Loss"] = round(support_val * 0.98, 2)
                except: pass

            w_df["Rating"] = w_df["Rating"].astype(str).replace(
                {"nan": "AVOID", "NaN": "AVOID", "None": "AVOID", "": "AVOID"}
            )
            save_sheet_data("Watchlist", w_df, w_schema)

        # 3. Log to ScanHistory — only when connection is confirmed active
        if get_conn() is not None:
            try:
                sig_count = (
                    len(p_df[p_df["Signal"] == "🚨 URGENT SELL"])
                    + len(w_df[w_df["Signal"] == "🔥 BUY NOW"])
                )
                now_ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
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

    now = datetime.now(IST)
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
        
        # Save Metadata BEFORE scan to prevent re-triggering loop
        if get_conn() is not None:
            sync_now = datetime.now(IST).strftime("%I:%M %p IST")
            new_meta = pd.DataFrame([
                {"Key": "last_scan_time", "Value": f"{current_date_str}_INIT"},
                {"Key": "last_sync_actual", "Value": sync_now},
            ])
            save_sheet_data("Metadata", new_meta, ["Key", "Value"])
        
        background_batch_scan()
        return

    # 2. Daily Schedule Loop
    for window in reversed(SCAN_WINDOWS):
        if current_time_str >= window:
            window_scan_key = f"{current_date_str}_{window}"
            if last_scan_val != window_scan_key:
                if st.session_state.get(f"lock_{window_scan_key}"): continue
                st.session_state[f"lock_{window_scan_key}"] = True

                # Save Metadata BEFORE scan to prevent re-triggering loop
                if get_conn() is not None:
                    sync_now = datetime.now(IST).strftime("%I:%M %p IST")
                    new_meta = pd.DataFrame([
                        {"Key": "last_scan_time", "Value": window_scan_key},
                        {"Key": "last_sync_actual", "Value": sync_now},
                    ])
                    save_sheet_data("Metadata", new_meta, ["Key", "Value"])

                background_batch_scan()
                break


def render_status_hub(placeholder=None, ui_buy_alerts=0, ui_sell_alerts=0):
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
    nifty_price, nifty_pct, n_sma20, n_sma50 = fetch_nifty_baseline()

    # Defaults
    now = datetime.now(IST)
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
    sell_alerts = ui_sell_alerts
    buy_alerts = ui_buy_alerts

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
    
    if nifty_price > n_sma20:
        mkt_state, mkt_color = "🟢 BULLISH", "#00D4AA"
    elif nifty_price > n_sma50:
        mkt_state, mkt_color = "🟡 CAUTION", "#FFD700"
    else:
        mkt_state, mkt_color = "🔴 BEARISH", "#FF4B4B"

    nifty_color = "#00D4AA" if nifty_pct >= 0 else "#FF4B4B"
    macro_block = (
        f"<div class='status-header'>📈 NIFTY 50 • <span style='color:{mkt_color}; font-weight:bold;'>{mkt_state}</span></div>"
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
    if placeholder:
        with placeholder.container():
            st.markdown(hub_html.replace('\n', ' '), unsafe_allow_html=True)
            if st.button("🔄 Force System Scan", key="force_scan_hub_btn", use_container_width=True):
                try:
                    with st.spinner("🚀 Stabilizing Connection..."):
                        time.sleep(1)
                    background_batch_scan()
                    sync_now = datetime.now(IST).strftime("%I:%M %p IST")
                    new_meta = pd.DataFrame([
                        {"Key": "last_scan_time", "Value": f"{now.strftime('%Y-%m-%d')}_MANUAL"},
                        {"Key": "last_sync_actual", "Value": sync_now},
                    ])
                    save_sheet_data("Metadata", new_meta, ["Key", "Value"])
                    st.toast("✅ Manual System Scan Successful!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Force Scan Failed: {e}")
    else:
        st.markdown(hub_html.replace('\n', ' '), unsafe_allow_html=True)
        if st.button("🔄 Force System Scan", key="force_scan_hub_btn", use_container_width=True):
            try:
                with st.spinner("🚀 Stabilizing Connection..."):
                    time.sleep(1)
                background_batch_scan()
                sync_now = datetime.now(IST).strftime("%I:%M %p IST")
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
def fetch_nifty_baseline() -> tuple[float, float, float, float]:
    """Fetch recent Nifty 50 (^NSEI) data and return (last_close, pct_change, sma20, sma50)."""
    try:
        nifty = yf.download("^NSEI", period="3mo", interval="1d", progress=False, auto_adjust=True, multi_level_index=False)
        if nifty.empty: return 0.0, 0.0, 0.0, 0.0
        
        if isinstance(nifty.columns, pd.MultiIndex):
            nifty.columns = nifty.columns.get_level_values(0)
            
        latest_close = float(nifty["Close"].iloc[-1])
        prev_close = float(nifty["Close"].iloc[-2]) if len(nifty) > 1 else latest_close
        pct_change = ((latest_close - prev_close) / prev_close) * 100
        
        sma20 = nifty["Close"].rolling(window=20).mean().iloc[-1]
        sma50 = nifty["Close"].rolling(window=50).mean().iloc[-1]
        
        return round(latest_close, 2), round(pct_change, 2), float(sma20) if not pd.isna(sma20) else 0.0, float(sma50) if not pd.isna(sma50) else 0.0
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


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
        time.sleep(0.2)
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
    # 20-day window for macro context
    win_20 = df.iloc[-21:-1]
    # 5-day window for recent momentum
    win_5 = df.iloc[-6:-1]

    if not win_20.empty and not win_5.empty:
        # Weighted High/Low (2x weight to last 5 days)
        w_high = (win_20["HIGH"].max() + win_5["HIGH"].max()) / 2
        w_low = (win_20["LOW"].min() + win_5["LOW"].min()) / 2
        w_close = win_20["CLOSE"].iloc[-1]

        pivot = (w_high + w_low + w_close) / 3
        # Establishing the S1/R1 lines
        df["PIVOT"] = pivot
        df["SUPPORT_1"] = (2 * pivot) - w_high
        df["RESISTANCE_1"] = (2 * pivot) - w_low
        
        # S2/R2
        df["SUPPORT_2"] = pivot - (w_high - w_low)
        df["RESISTANCE_2"] = pivot + (w_high - w_low)

        # Polarity Engine
        df["ACTIVE_SUPPORT"] = df["SUPPORT_1"]
        df["ACTIVE_RESISTANCE"] = df["RESISTANCE_1"]
        df["POLARITY_STATE"] = "RANGE"

        df.loc[df["CLOSE"] > df["RESISTANCE_1"], "ACTIVE_SUPPORT"] = df["RESISTANCE_1"]
        df.loc[df["CLOSE"] > df["RESISTANCE_1"], "ACTIVE_RESISTANCE"] = df["RESISTANCE_2"]
        df.loc[df["CLOSE"] > df["RESISTANCE_1"], "POLARITY_STATE"] = "BREAKOUT"

        df.loc[df["CLOSE"] < df["SUPPORT_1"], "ACTIVE_RESISTANCE"] = df["SUPPORT_1"]
        df.loc[df["CLOSE"] < df["SUPPORT_1"], "ACTIVE_SUPPORT"] = df["SUPPORT_2"]
        df.loc[df["CLOSE"] < df["SUPPORT_1"], "POLARITY_STATE"] = "BREAKDOWN"
        
        s_level = df["SUPPORT_1"].iloc[-1]
        # Count how many times price came within 1% of S1 in the last 20 days
        touches = ((df["LOW"].iloc[-21:-1] >= s_level * 0.99) & 
                   (df["LOW"].iloc[-21:-1] <= s_level * 1.01)).sum()
        df["S1_STRENGTH"] = touches
        
        r_level = df["RESISTANCE_1"].iloc[-1]
        # Count how many times High price touched the 1% Resistance zone in last 20 days
        r_touches = ((df["HIGH"].iloc[-21:-1] >= r_level * 0.99) & 
                     (df["HIGH"].iloc[-21:-1] <= r_level * 1.01)).sum()
        df["R1_STRENGTH"] = r_touches
    else:
        # Fallback if window is too small
        last_close = df["CLOSE"].iloc[-1]
        df["PIVOT"] = last_close
        df["SUPPORT_1"] = last_close
        df["RESISTANCE_1"] = last_close
        df["SUPPORT_2"] = last_close
        df["RESISTANCE_2"] = last_close
        df["ACTIVE_SUPPORT"] = last_close
        df["ACTIVE_RESISTANCE"] = last_close
        df["POLARITY_STATE"] = "RANGE"
        df["S1_STRENGTH"] = 0
        df["R1_STRENGTH"] = 0
        
    if "VOL_20SMA" not in df.columns:
        df["VOL_20SMA"] = 1

    # Map back to standard names for compatibility with the rest of the app
    df = df.rename(columns={
        'CLOSE': 'Close', 'HIGH': 'High', 'LOW': 'Low', 'OPEN': 'Open', 'VOLUME': 'Volume',
        'PIVOT': 'Pivot', 'SUPPORT_1': 'Support_1', 'RESISTANCE_1': 'Resistance_1',
        'SUPPORT_2': 'Support_2', 'RESISTANCE_2': 'Resistance_2',
        'ACTIVE_SUPPORT': 'Active_Support', 'ACTIVE_RESISTANCE': 'Active_Resistance',
        'POLARITY_STATE': 'Polarity_State',
        'VOL_20SMA': 'Vol_20SMA', 'S1_STRENGTH': 'S1_Strength', 'R1_STRENGTH': 'R1_Strength'
    })
    
    # Calculate RSI
    df['RSI_14'] = ta.rsi(df['Close'], length=14)
    if 'RSI_14' not in df.columns:
        df['RSI_14'] = 50

    # Bear Trap Detection: Lower Wick length vs Body length
    body_size = abs(df['Close'] - df['Open'])
    lower_wick = df['Open'].where(df['Close'] > df['Open'], df['Close']) - df['Low']
    df['Wick_Ratio'] = lower_wick / body_size.replace(0, 0.01)

    # Bullish RSI Divergence (Simple): Is RSI higher than 3 days ago while price is lower?
    df['RSI_Rising'] = df['RSI_14'] > df['RSI_14'].shift(3)

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
    support_val = df["Active_Support"].iloc[-1]
    resistance_val = df["Active_Resistance"].iloc[-1]
    pivot_val = df["Pivot"].iloc[-1]
    s2_val = df["Support_2"].iloc[-1]
    r2_val = df["Resistance_2"].iloc[-1]

    fig.add_hline(
        y=s2_val,
        line_dash="dot",
        line_color="rgba(139,0,0,0.5)",
        annotation_text=f"S2 ₹{s2_val:,.2f}",
        row=1, col=1,
    )
    fig.add_hline(
        y=r2_val,
        line_dash="dot",
        line_color="rgba(0,128,128,0.5)",
        annotation_text=f"R2 ₹{r2_val:,.2f}",
        row=1, col=1,
    )
    fig.add_hline(
        y=support_val,
        line_dash="dot",
        line_color="#FF6B6B",
        annotation_text=f"Active Support ₹{support_val:,.2f}",
        row=1,
        col=1,
    )
    fig.add_hline(
        y=resistance_val,
        line_dash="dot",
        line_color="#4ECDC4",
        annotation_text=f"Active Resistance ₹{resistance_val:,.2f}",
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
def generate_swing_report(price, support, resistance, vol_surge, is_green, high_52w, master_rating, s1_strength=0, r_strength=0, sma_pts=0, wick_ratio=0, low_price=0, polarity_state="RANGE"):
    bullets = []
    
    if polarity_state == "BREAKOUT":
        bullets.append({"type": "success", "msg": "🔄 **Polarity Shift (Breakout):** Price has broken prior resistance. Old resistance is now your new Active Support floor."})

    if sma_pts == 1:
        bullets.append({"type": "success", "msg": "🚀 **Launchpad Position:** Stock is trading within 10% of its 50-DMA with positive momentum. This is a high-probability 'Ignition Zone' for early swing trades."})

    if wick_ratio > 1.5 and low_price < support:
        bullets.append({"type": "success", "msg": "🛡️ **Bear Trap Detected:** Price dipped below support but buyers aggressively drove it back up (Long lower wick). This is a high-conviction sign of institutional defense."})


    # 1. Risk/Reward (The Swing Trader's Holy Grail)
    risk = price - support
    reward = resistance - price
    
    if risk > 0 and reward > 0:
        rr_ratio = reward / risk
        if rr_ratio >= 2.0:
            bullets.append({"type": "success", "msg": f"⚖️ **Risk/Reward Profile:** EXCELLENT. Downside risk to S1 is ₹{risk:.2f}, while upside potential to R1 is ₹{reward:.2f}. This offers a highly asymmetric **1:{rr_ratio:.1f} Reward-to-Risk ratio**."})
        elif rr_ratio >= 1.0:
            bullets.append({"type": "warning", "msg": f"⚖️ **Risk/Reward Profile:** NEUTRAL. Upside potential (₹{reward:.2f}) roughly matches downside risk (₹{risk:.2f}). Ratio is **1:{rr_ratio:.1f}**."})
        else:
            bullets.append({"type": "error", "msg": f"⚠️ **Risk/Reward Profile:** POOR. Downside risk to support (₹{risk:.2f}) currently outweighs upside potential to resistance (₹{reward:.2f}). Chasing here is statistically dangerous."})
    elif price <= support:
        bullets.append({"type": "error", "msg": f"🚨 **Risk/Reward Profile:** AT OR BELOW SUPPORT. Immediate breakdown risk. Watch for strong rejection or further flush."})
    else:
        bullets.append({"type": "success", "msg": f"🚀 **Risk/Reward Profile:** BLUE SKY. Price has broken above known resistance (₹{resistance:.2f}). Trailing stops are mandatory here as upside is unmapped."})

    # 2. Volume & Momentum Confirmation
    if vol_surge >= 1.5 and is_green:
        bullets.append({"type": "success", "msg": f"🌊 **Momentum Confirmation:** STRONG ACCUMULATION. Trading at **{vol_surge:.1f}x** average volume on a positive close. The upward price action is mathematically validated by institutional money."})
    elif vol_surge >= 1.5 and not is_green:
        bullets.append({"type": "error", "msg": f"🩸 **Momentum Confirmation:** HEAVY DISTRIBUTION. High volume (**{vol_surge:.1f}x**) on a negative close indicates institutional selling. Expect severe downside pressure."})
    elif vol_surge < 0.8:
        bullets.append({"type": "warning", "msg": f"🏜️ **Momentum Confirmation:** LOW PARTICIPATION. Trading at only **{vol_surge:.1f}x** normal volume. Any price movement today lacks strong conviction and is prone to reversal."})
    else:
        bullets.append({"type": "info", "msg": f"📊 **Momentum Confirmation:** AVERAGE. Volume is normal (**{vol_surge:.1f}x**). No extreme institutional footprints detected today."})

    # 3. Macro Structure (Context)
    if price >= (high_52w * 0.95):
        bullets.append({"type": "success", "msg": f"🏔️ **Macro Structure:** BREAKOUT WATCH. Trading within 5% of its 52-Week High (₹{high_52w:.2f}). Watch closely for momentum continuation or a violent double-top rejection."})
    elif risk > 0 and (risk / price) < 0.04: 
        bullets.append({"type": "success", "msg": f"📉 **Macro Structure:** BASELINE REVERSION. Trading within 4% of structural support. This is a classic 'make or break' pivot level for a swing entry."})
    else:
        bullets.append({"type": "info", "msg": f"🧭 **Macro Structure:** MID-RANGE. Trading comfortably between major macro pivot levels. No immediate structural breakouts or breakdowns detected."})

    if s1_strength >= 3:
        bullets.append({"type": "success", "msg": f"🏰 **Structural Strength:** HIGH. Price has respected this support zone {int(s1_strength)} times recently. This is a high-probability floor."})

    if r_strength >= 3:
        bullets.append({
            "type": "error", 
            "msg": f"🧱 **Structural Resistance:** HIGH. Price has been rejected by this ceiling {int(r_strength)} times in the last 20 days. This is a 'Brick Wall' supply zone; expect a struggle unless volume surge is massive."
        })
    elif r_strength >= 1:
        bullets.append({
            "type": "info", 
            "msg": f"🏗️ **Structural Resistance:** MODERATE. This level has been tested {int(r_strength)} times. A clean break here signals a high-conviction momentum move."
        })

    # 4. Final Verdict
    v_type = "info"
    if "BUY" in master_rating: v_type = "success"
    elif "HOLD" in master_rating: v_type = "warning"
    elif "AVOID" in master_rating or "SELL" in master_rating: v_type = "error"
    
    bullets.append({"type": v_type, "msg": f"🎯 **Actionable Verdict:** The system's master algorithm categorizes this setup as a **{master_rating}**. Execute according to your predefined trade plan."})
    
    return bullets


def get_company_name(ticker: str) -> str:
    """Retrieve the company long/short name from yfinance, fallback to ticker."""
    try:
        info = yf.Ticker(ticker).info
        return info.get("longName") or info.get("shortName") or ticker
    except Exception:
        return ticker




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


@st.cache_data(ttl=3600)
def fetch_market_cap(ticker: str) -> str:
    """Return market cap formatted in Indian Crores/Lakhs Crores."""
    try:
        mcap_raw = yf.Ticker(ticker).info.get("marketCap", 0)
        if not mcap_raw or mcap_raw <= 0:
            return "N/A"
        mcap_cr = mcap_raw / 1e7  # 1 Cr = 10M
        if mcap_cr >= 1_00_000:
            return f"₹{mcap_cr / 1_00_000:.2f}L Cr"
        elif mcap_cr >= 1_000:
            return f"₹{mcap_cr:,.0f} Cr"
        return f"₹{mcap_cr:.1f} Cr"
    except Exception:
        return "N/A"


def calculate_master_score(df: pd.DataFrame, fundamentals: dict):
    """Calculate the 11-point Master Rating score."""
    if df.empty: return 0, 0, 0, 0, 0, 0, 0, 0
    latest = df.iloc[-1]
    support_val = df["Active_Support"].iloc[-1]
    resistance_val = df["Active_Resistance"].iloc[-1]
    
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
    
    # New Layer 3: Confluence
    strength_pts = 1 if df.get("S1_Strength", pd.Series([0], index=[-1])).iloc[-1] >= 3 else 0
    
    # 5. SMA 50 Proximity (Screener Alignment)
    sma_pts = 0
    if 'SMA_50' in df.columns:
        sma_val = df['SMA_50'].iloc[-1]
        close_val = df['Close'].iloc[-1]
        if pd.notna(sma_val) and sma_val > 0:
            if close_val > sma_val and close_val < (sma_val * 1.1):
                sma_pts = 1

    # 6. Support Defense (Bear Trap / Divergence)
    defense_pts = 0
    s1_calc = latest['Active_Support'] if 'Active_Support' in df.columns else latest['Close']
    if latest['Close'] < s1_calc * 1.05:
        if latest.get('RSI_Rising', False) or latest.get('Wick_Ratio', 0) > 1.5:
            defense_pts = 1

    total_score = s_points + t_points + v_points + f_points + strength_pts + sma_pts + defense_pts

    return total_score, t_points, v_points, s_points, f_points, strength_pts, sma_pts, defense_pts


def get_market_condition(df):
    """MASTER Logic: Unified RSI (Momentum) + Entry Risk (Structure) scoring."""
    if df.empty or len(df) < 14:
        return "⚪ N/A", "gray", 50
    
    # 1. RSI(14) - Momentum
    rsi_vals = ta.rsi(df['Close'], length=14)
    rsi = rsi_vals.iloc[-1] if not pd.isna(rsi_vals.iloc[-1]) else 50
    
    # 2. Risk - Structure
    close = df['Close'].iloc[-1]
    s1 = df['Active_Support'].iloc[-1]
    r1 = df['Active_Resistance'].iloc[-1]
    
    # Calc Risk Percentage
    if r1 > s1:
        risk_pct = ((close - s1) / (r1 - s1)) * 100
    else:
        risk_pct = 50
    
    # Logic Hierarchy
    # If Volume Surge > 1.5 and Price is at the top of the range, it's a breakout, not a risk.
    latest_vol_surge = df['Volume'].iloc[-1] / (df['Vol_20SMA'].iloc[-1] if 'Vol_20SMA' in df.columns and df['Vol_20SMA'].iloc[-1] > 0 else 1)
    is_green = df['Close'].iloc[-1] >= df['Open'].iloc[-1]

    if latest_vol_surge >= 1.5 and risk_pct > 80 and is_green:
        return "🚀 BREAKOUT", "#00D4AA", risk_pct

    if rsi < 30: return "🔵 OVERSOLD", "blue", risk_pct
    if rsi > 70: return "🟣 OVERBOUGHT", "purple", risk_pct
    if risk_pct < 45: return "🟢 SAFE", "#00D4AA", risk_pct
    if risk_pct > 85: return "🔴 OVEREXTENDED", "#FF4B4B", risk_pct
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
                    
                    # Pre-load watchlist
                    w_cols_batch = ["Ticker"]
                    w_df_batch = load_sheet_data("Watchlist", w_cols_batch)
                    
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
                            b_sup1 = b_df["Active_Support"].iloc[-1]
                            b_res1 = b_df["Active_Resistance"].iloc[-1]
                            
                             # 1. Get Context (Centralized Logic)
                            b_label, _, _ = get_market_condition(b_df)
                            ctx_clean = str(b_label).strip()
                            for pfx in ["🔵 ", "🟣 ", "🟢 ", "🔴 ", "🟡 ", "🚀 "]:
                                ctx_clean = ctx_clean.replace(pfx, "")

                            # 2. Get Fundamentals & Master Score
                            b_funda = fetch_fundamentals(t_sym)
                            m_score, t_pts, _, _, _, _, _, _ = calculate_master_score(b_df, b_funda)

                            # 3. Determine Standard Rating
                            if m_score >= 7: m_rating = "STRONG BUY"
                            elif m_score >= 5: m_rating = "MODERATE BUY"
                            elif m_score >= 3: m_rating = "WATCHLIST / HOLD"
                            else: m_rating = "AVOID"

                            # 4. Vol Footprint
                            b_vol = b_df["Volume"].iloc[-1]
                            b_vol20 = b_df["Vol_20SMA"].iloc[-1] if not pd.isna(b_df["Vol_20SMA"].iloc[-1]) and b_df["Vol_20SMA"].iloc[-1] > 0 else 1
                            b_v_ratio = b_vol / b_vol20
                            b_is_green = b_close >= b_df["Open"].iloc[-1]
                            if b_v_ratio >= 1.5 and b_is_green: b_vol_foot = "🟢 Accumulation"
                            elif b_v_ratio >= 1.5 and not b_is_green: b_vol_foot = "🔴 DISTRIBUTION"
                            else: b_vol_foot = "⚪ Normal"

                            display_ticker_b = t_sym

                            results.append({
                                "Ticker": display_ticker_b,
                                "RawTicker": t_sym,
                                "Price": format_indian(round(b_close, 2), is_price=True),
                                "Entry Context": ctx_clean,
                                "Trend": f"{t_pts}/2",
                                "Rating": m_rating,
                                "Vol Footprint": b_vol_foot,
                                "_rating_rank": m_score,
                                "_raw_price": float(b_close),
                                "_raw_stop": float(b_sup1 * 0.98)
                            })
                        except:
                            continue
                    
                    progress_text.empty()
                    if results:
                        st.session_state["batch_results"] = pd.DataFrame(results).sort_values(by="_rating_rank", ascending=False)
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
            # Header
            B_COL_RATIOS = [1.5, 1, 1.5, 1, 1.5, 1.5, 1.2]
            bh_col = st.columns(B_COL_RATIOS)
            bh_col[0].markdown("**Ticker**")
            bh_col[1].markdown("**Price**")
            bh_col[2].markdown("**Entry Context**")
            bh_col[3].markdown("**Trend**")
            bh_col[4].markdown("**Rating**")
            bh_col[5].markdown("**Vol Footprint**")
            bh_col[6].markdown("**Actions**")

            WATCHLIST_COLS = ["Ticker", "Price", "Rating", "Entry Context", "Trend Strength", "Stop Loss", "Vol Footprint"]
            w_df_pre = load_sheet_data("Watchlist", WATCHLIST_COLS)
            existing_watch = set(w_df_pre["Ticker"].values) if not w_df_pre.empty else set()

            # --- BULK ADD MODULE ---
            untracked_results = b_results[~b_results["RawTicker"].apply(sanitize_ticker).isin(existing_watch)]
            if not untracked_results.empty:
                with st.expander("🛠️ Bulk Actions (Add Multiple)"):
                    c_bulk1, c_bulk2 = st.columns([4, 1])
                    with c_bulk1:
                        bulk_selected = st.multiselect("Select stocks to add:", options=untracked_results["RawTicker"].tolist(), default=[], help="Only untracked stocks are shown here.")
                    with c_bulk2:
                        st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
                        if st.button("⭐ Add Selected", type="primary", use_container_width=True, disabled=len(bulk_selected) == 0):
                            with st.spinner(f"Batch syncing {len(bulk_selected)} stocks to database..."):
                                new_rows = []
                                for t in bulk_selected:
                                    row_data = untracked_results[untracked_results["RawTicker"] == t].iloc[0]
                                    new_rows.append({
                                        "Ticker": sanitize_ticker(t),
                                        "Price": round(row_data.get("_raw_price", 0.0), 2),
                                        "Rating": row_data["Rating"],
                                        "Entry Context": row_data["Entry Context"],
                                        "Trend Strength": row_data["Trend"],
                                        "Stop Loss": round(row_data.get("_raw_stop", 0.0), 2),
                                        "Vol Footprint": row_data["Vol Footprint"]
                                    })
                                fresh_w_df = pd.concat([w_df_pre, pd.DataFrame(new_rows)], ignore_index=True)
                                save_sheet_data("Watchlist", fresh_w_df, WATCHLIST_COLS)
                                st.toast(f"✅ Successfully added {len(bulk_selected)} stocks to Watchlist!")
                                time.sleep(0.5) # Give toast time to render
                                st.rerun()
            st.markdown("<br>", unsafe_allow_html=True)
            # --- END BULK ADD MODULE ---

            for idx, row in b_results.iterrows():
                # ── Color Logic (Unified with Watchlist) ──
                # 1. Rating
                r_str = str(row["Rating"]).upper()
                r_color = "#00d26a" if "BUY" in r_str else "#fbd63f" if ("HOLD" in r_str or "WATCHLIST" in r_str) else "#f7556a"
                r_html = f"<span style='color:{r_color}; font-weight:bold;'>{row['Rating']}</span>"
                
                # 2. Context
                c_str = str(row["Entry Context"]).upper()
                c_color = "#00d26a" if "SAFE" in c_str else "#fbd63f" if "FAIR" in c_str else "#f7556a"
                c_html = f"<span style='color:{c_color}; font-weight:bold;'>{c_str}</span>"
                
                # 3. Trend
                t_str = str(row["Trend"]).upper()
                t_color = "#00d26a" if ("2/2" in t_str or "BULL" in t_str) else "#fbd63f" if "1/2" in t_str else "#f7556a"
                t_html = f"<span style='color:{t_color}; font-weight:bold;'>{t_str}</span>"

                rb_col = st.columns(B_COL_RATIOS)
                rb_col[0].write(row["Ticker"])
                rb_col[1].write(f"₹{row['Price']}")
                rb_col[2].markdown(c_html, unsafe_allow_html=True)
                rb_col[3].markdown(t_html, unsafe_allow_html=True)
                rb_col[4].markdown(r_html, unsafe_allow_html=True)
                rb_col[5].write(row["Vol Footprint"])
                clean_p = sanitize_ticker(row["RawTicker"])
                is_tracked = clean_p in existing_watch
                
                btn_c1, btn_c2 = rb_col[6].columns(2)
                
                if btn_c1.button("🔎", key=f"b_an_{row['RawTicker']}_{idx}", help="Analyze Setup", use_container_width=True, on_click=set_search_ticker, args=(row["RawTicker"],)):
                    pass
                
                if btn_c2.button("⭐", key=f"b_w_{row['RawTicker']}_{idx}", disabled=is_tracked, help="Already in Watchlist" if is_tracked else "Add to Watchlist", use_container_width=True):
                    fresh_w_df = load_sheet_data("Watchlist", WATCHLIST_COLS)
                    if clean_p not in fresh_w_df["Ticker"].values:
                        new_row = pd.DataFrame([{
                            "Ticker": clean_p,
                            "Price": round(row.get("_raw_price", 0.0), 2),
                            "Rating": row["Rating"],
                            "Entry Context": row["Entry Context"],
                            "Trend Strength": row["Trend"],
                            "Stop Loss": round(row.get("_raw_stop", 0.0), 2),
                            "Vol Footprint": row["Vol Footprint"]
                        }])
                        fresh_w_df = pd.concat([fresh_w_df, new_row], ignore_index=True)
                        save_sheet_data("Watchlist", fresh_w_df, WATCHLIST_COLS)
                        st.toast(f"✅ Added {clean_p} to Watchlist!")
                        st.rerun() # Refresh immediately to disable the button
                    else:
                        st.toast(f"⚠️ {clean_p} is already in your Watchlist.")
        else:
            st.info("❌ No stocks passed the scan.")
    else:
        st.markdown("<p style='color: gray; padding-top: 10px;'>Results will appear here after scanning.</p>", unsafe_allow_html=True)


# ===================================================================
# INITIALIZE SESSION STATE
# ===================================================================
# INITIALIZE SESSION STATE (Moved to top level file)

st.title("📈 Stock Analyzer Terminal")

col_sym, col_tick, col_bell = st.columns([6, 3, 1])
with col_sym:
    # Warp Search Bar Sync - Streamlit binds this widget to st.session_state['search_input']
    search_query = st.text_input(
        "Search Company Name or Ticker",
        placeholder="e.g., Narmada, RELIANCE, TCS",
        key="search_input",
    )

with col_bell:
    st.markdown("<div style='padding-top: 28px;'></div>", unsafe_allow_html=True)
    alert_count = len(st.session_state["alert_history"])
    btn_label = f"🔔 {alert_count}" if alert_count > 0 else "🔔"
    with st.popover(btn_label, use_container_width=True):
        st.markdown("**Notification History**")
        if st.button("Clear All", key="clear_all_alerts", use_container_width=True):
            st.session_state["alert_history"] = []
            st.rerun()
        st.divider()
        if not st.session_state["alert_history"]:
            st.info("No new notifications.")
        else:
            # Enforce a scrollable view area
            with st.container(height=350, border=False):
                for i, alert in enumerate(st.session_state["alert_history"]):
                    # Create a padded, bordered card for each alert
                    with st.container(border=True):
                        # Align the text and the clear button vertically
                        c_text, c_del = st.columns([0.85, 0.15], vertical_alignment="center")

                        with c_text:
                            # Date/Time on top (no icon), Message on bottom
                            st.markdown(
                                f"<div style='line-height: 1.4;'>"
                                f"<span style='color:gray; font-size:0.75rem;'>{alert['time']}</span><br>"
                                f"<span style='font-size:0.9rem;'>{alert['icon']} {alert['msg']}</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )

                        with c_del:
                            # Individual clear button
                            if st.button("✖", key=f"del_al_{i}", help="Dismiss"):
                                st.session_state["alert_history"].pop(i)
                                st.rerun()

# --- 📡 SCAN STATUS HUB — Control Center (above Portfolio/Watchlist, below Search Bar) ---
hub_placeholder = st.empty()
total_buy_alerts = 0
total_sell_alerts = 0


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
    ui_cmp = 0.0
    ui_stop = 0.0
    ui_rating = "PENDING"
    ui_ctx = "PENDING"
    ui_trend = "0/2"

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

        st.markdown(f"<h3>{company_name}</h3>", unsafe_allow_html=True)

        try:
            latest = df.iloc[-1]
            prev_close = df["Close"].iloc[-2] if len(df) >= 2 else latest["Close"]
            day_change = latest["Close"] - prev_close
            day_change_pct = (day_change / prev_close) * 100
            support_val = df["Active_Support"].iloc[-1]
            resistance_val = df["Active_Resistance"].iloc[-1]
            s2_val = df["Support_2"].iloc[-1]
            r2_val = df["Resistance_2"].iloc[-1]
            week52_high = df["High"].max()
            week52_low = df["Low"].min()
            ideal_entry = support_val * 1.012  # 1.2% above S1 to confirm the bounce
            ideal_stop = support_val * 0.98    # 2.0% below S1 to survive stop hunts

            st.divider()
            

            # --- Metrics Row ---
            is_indian = full_ticker.endswith(".NS") or full_ticker.endswith(".BO")
            
            def fmt_price(val):
                return f"₹{format_indian(val, is_price=True)}" if is_indian else f"₹{val:,.2f}"

            def fmt_delta(val):
                if not is_indian: return f"{val:+,.2f}"
                return f"+{format_indian(val, is_price=True)}" if val >= 0 else format_indian(val, is_price=True)

            polarity_state = df["Polarity_State"].iloc[-1] if "Polarity_State" in df.columns else "RANGE"
            
            if polarity_state == "BREAKOUT":
                s_label, s_delta = "Support (Old R1)", f"S2: {fmt_price(s2_val)}"
                r_label, r_delta = "Resist. (R2 Target)", "Blue Sky Breakout"
            elif polarity_state == "BREAKDOWN":
                s_label, s_delta = "Support (S2 Level)", "Freefall Watch"
                r_label, r_delta = "Resist. (Old S1)", f"R2: {fmt_price(r2_val)}"
            else:
                s_label, s_delta = "Support (S1)", f"S2: {fmt_price(s2_val)}"
                r_label, r_delta = "Resist. (R1)", f"R2: {fmt_price(r2_val)}"

            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
            c1.metric("Current Price", fmt_price(latest['Close']))
            c2.metric("Day Change %", f"{day_change_pct:,.2f}%", delta=fmt_delta(day_change))
            c3.metric("Ideal Entry (Bounce)", fmt_price(ideal_entry))
            c4.metric(s_label, fmt_price(support_val), delta=s_delta, delta_color="normal")
            c5.metric("Auto Stop (Zone)", fmt_price(ideal_stop))
            c6.metric(r_label, fmt_price(resistance_val), delta=r_delta, delta_color="normal")
            c7.metric("52W High", fmt_price(week52_high))
            c8.metric("52W Low", fmt_price(week52_low))

            # --- Fundamental health ---
            vol_today_raw = latest.get("Volume", 1)
            vol_20sma_raw = latest.get("Vol_20SMA", 1)
            if pd.isna(vol_20sma_raw) or vol_20sma_raw == 0: vol_20sma_raw = 1
            v_ratio_raw = vol_today_raw / vol_20sma_raw
            vol_diff = vol_today_raw - vol_20sma_raw
            # Candle direction determines Accumulation vs Distribution label
            is_green = latest.get("Close", 0) >= latest.get("Open", 0)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### 🏥 Fundamental & Volume Health")
            mcap_str = fetch_market_cap(full_ticker)
            h1, h2, h3, h4, h5, h6 = st.columns(6)
            h1.metric("Market Cap", mcap_str)
            h2.metric("ROCE (Efficiency)", f"{roce:.2f}%")
            h3.metric("Debt-to-Equity", f"{debt_to_equity:.2f}")
            h4.metric("Current Volume", format_indian(vol_today_raw), delta=f"{format_indian(vol_diff)} vs Avg")
            h5.metric("20-Day Avg Vol", format_indian(vol_20sma_raw))
            if v_ratio_raw >= 1.5 and is_green:
                surge_label = "🔥 Inst. Accumulation"
                surge_color = "normal"       # renders green ↑
            elif v_ratio_raw >= 1.5 and not is_green:
                surge_label = "🩸 Inst. Distribution"
                surge_color = "inverse"      # renders red ↓
            else:
                surge_label = "Normal Volume"
                surge_color = "off"          # neutral grey
            h6.metric("Volume Surge", f"{v_ratio_raw:.2f}x", delta=surge_label, delta_color=surge_color)

            # --- Master Rating ---
            total_score, t_points, v_points, s_points, f_points, strength_pts, sma_pts, def_pts = calculate_master_score(df, {"roce": roce, "debt_to_equity": debt_to_equity})
            s_score = (s_points / 2) * 100
            adx_v = float(df["ADX"].iloc[-1])

            if total_score >= 7: master_rating, rating_color_hex = "STRONG BUY", "#00FF00"
            elif total_score >= 5: master_rating, rating_color_hex = "MODERATE BUY", "#00D4AA"
            elif total_score >= 3: master_rating, rating_color_hex = "WATCHLIST / HOLD", "#FFD700"
            else: master_rating, rating_color_hex = "AVOID", "#FF4B4B"

            r_str = int(df["R1_Strength"].iloc[-1]) if "R1_Strength" in df.columns else 0

            rating_html = f'''
            <div style="text-align: center; padding: 10px; margin: 15px 0; border-radius: 8px; border: 2px solid {rating_color_hex}; background: {rating_color_hex}1A;">
                <div style="font-size: 1.8em; font-weight: bold; margin: 0; color: {rating_color_hex};">MASTER ALGORITHMIC RATING: {master_rating}</div>
                <div style="font-size: 0.9em; color: gray; margin-top: 5px;">
                    Trend: {t_points}/2 | Vol: {v_points}/2 | Safety: {s_points}/2 | Funda: {f_points}/2 | Str: {strength_pts}/1 | SMA: {sma_pts}/1 | Def: {def_pts}/1 | R-Touches: {r_str}
                </div>
            </div>
            '''
            st.markdown(rating_html, unsafe_allow_html=True)
            ui_cmp = float(latest["Close"])
            ui_stop = float(support_val)
            ui_rating = master_rating
            cond_label_val, _, _ = get_market_condition(df)
            ui_ctx = str(cond_label_val).strip().replace("🔵 ", "").replace("🟣 ", "").replace("🟢 ", "").replace("🔴 ", "").replace("🟡 ", "").replace("🚀 ", "")
            ui_trend = f"{t_points}/2"

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

            # --- System Quantitative Report Section ---
            st.subheader("📊 System Quantitative Report")
            alerts = generate_swing_report(
                price=latest['Close'], 
                support=support_val, 
                resistance=resistance_val, 
                vol_surge=v_ratio_raw, 
                is_green=is_green, 
                high_52w=week52_high,
                master_rating=master_rating,
                s1_strength=df["S1_Strength"].iloc[-1] if "S1_Strength" in df.columns else 0,
                r_strength=df["R1_Strength"].iloc[-1] if "R1_Strength" in df.columns else 0,
                sma_pts=sma_pts,
                wick_ratio=df['Wick_Ratio'].iloc[-1] if 'Wick_Ratio' in df.columns else 0,
                low_price=latest['Low'],
                polarity_state=df["Polarity_State"].iloc[-1] if "Polarity_State" in df.columns else "RANGE"
            )
            
            for alert in alerts:
                if alert["type"] == "success":
                    st.success(alert["msg"])
                elif alert["type"] == "warning":
                    st.warning(alert["msg"])
                elif alert["type"] == "error":
                    st.error(alert["msg"])
                else:
                    st.info(alert["msg"])

            st.divider()

        except (IndexError, KeyError) as e:
            st.info(f"Market structure algorithms currently unavailable for **{full_ticker}**.")




    # --- 1% Risk Calculator (Decoupled & Synced) ---
    st.subheader("📐 1% Risk Calculator")
    st.markdown("_Direct analysis for **" + full_ticker + "** (Auto-synced)._")
    
    if st.session_state["sync_ticker"] != full_ticker:
        st.session_state["sync_ticker"] = full_ticker
        st.session_state["entry_price_key"] = ui_cmp
        st.session_state["stop_loss_key"] = ui_stop

    c_calc, c_gap, c_pos = st.columns([4.5, 1, 4.5])
    with c_calc:
        capital = st.number_input("Total Account Capital (₹)", min_value=0.0, step=10000.0, key="capital_key")
        st.session_state["capital_ext"] = capital
        entry_price = st.number_input("Entry Price (₹)", min_value=0.01, step=0.5, key="entry_price_key")
        stop_loss = st.number_input("Stop-Loss Price (₹)", min_value=0.01, step=0.5, key="stop_loss_key")
        manual_qty_input = st.number_input("Manual Quantity (Optional)", min_value=0, value=0, step=1, key="manual_qty_input")

    with c_pos:
        if entry_price > stop_loss:
            max_risk = capital * 0.01
            risk_per_share = entry_price - stop_loss
            
            # 1. How many shares can we buy based on 1% risk limit?
            max_shares_by_risk = math.floor(max_risk / risk_per_share) if risk_per_share > 0 else 0
            
            # 2. How many shares can we actually afford with our cash balance?
            max_shares_by_capital = math.floor(capital / entry_price) if entry_price > 0 else 0
            
            # 3. The auto-suggestion must be the smaller of the two
            auto_shares = min(max_shares_by_risk, max_shares_by_capital)
            
            # Determine which quantity to show and use
            # Use manual entry if user typed something, otherwise use auto
            final_qty = manual_qty_input if manual_qty_input > 0 else auto_shares

            if final_qty > 0:
                actual_risk = final_qty * risk_per_share
                
                # UI Display (Back to standard metrics)
                st.subheader("📊 Position Size")
                r1_c1, r1_c2 = st.columns(2)
                
                if manual_qty_input > 0:
                    risk_diff = actual_risk - max_risk
                    delta_str = f"{'+' if risk_diff > 0 else ''}{format_indian(risk_diff, is_price=True)} vs 1% Limit"
                    # delta_color='inverse' makes positive numbers (extra risk) red, which is what we want for risk.
                    r1_c1.metric("Actual Risk (Override)", f"₹{format_indian(actual_risk, is_price=True)}", delta=delta_str, delta_color="inverse")
                else:
                    r1_c1.metric("Max Risk (1%)", f"₹{format_indian(max_risk, is_price=True)}")

                r1_c2.metric("Risk Per Share", f"₹{format_indian(risk_per_share, is_price=True)}")
                
                r2_c1, r2_c2 = st.columns(2)
                r2_c1.metric("Shares to Buy", f"{final_qty:,}")
                actual_deployed = final_qty * entry_price
                r2_c2.metric("Capital Deployed", f"₹{format_indian(actual_deployed, is_price=True)}")
                
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
                
                clean_p = sanitize_ticker(full_ticker)
                p_df_check = load_sheet_data("Portfolio", ["Ticker"])
                
                if not p_df_check.empty and clean_p in p_df_check["Ticker"].values:
                    st.button("💼 Active in Portfolio", disabled=True, use_container_width=True)
                    st.caption("⚠️ To adjust this position, delete it from the Live Portfolio table first.")
                else:
                    if st.button("💼 Add to Portfolio", use_container_width=True):
                        with st.spinner("Syncing to Cloud Database..."):
                            p_schema = ["Ticker", "Buy_Price", "Initial_Stop", "Highest_Trail", "Quantity", "Date_Added", "CMP", "RSI_HTML", "T1_HTML", "PCT_HTML", "Vol_Foot", "Verdict_HTML", "_verdict_rank", "_vol_rank"]
                            p_df = load_sheet_data("Portfolio", p_schema)
                            new_trade = pd.DataFrame([{
                                "Ticker": clean_p,
                                "Buy_Price": entry_price,
                                "Initial_Stop": stop_loss,
                                "Highest_Trail": stop_loss,
                                "Quantity": final_qty,
                                "Date_Added": datetime.now(IST).strftime("%Y-%m-%d"),
                                "CMP": entry_price,
                                "RSI_HTML": "...",
                                "T1_HTML": "...",
                                "PCT_HTML": "...",
                                "Vol_Foot": "...",
                                "Verdict_HTML": "<span style='color:gray;'>Pending Scan...</span>",
                                "_verdict_rank": -1,
                                "_vol_rank": -1
                            }])
                            p_df = pd.concat([p_df, new_trade], ignore_index=True)
                            save_sheet_data("Portfolio", p_df, p_schema)
                            st.success(f"Added {clean_p} to Portfolio!")
                            st.rerun()
                    
                if actual_deployed > capital: st.warning("⚠️ Position exceeds your total capital!")
        else: st.error("Entry Price must be greater than Stop-Loss Price.")

        # --- Smart Action Buttons (Watchlist) ---
        clean_p_watchlist = sanitize_ticker(full_ticker)
        WATCHLIST_COLS = ["Ticker", "Price", "Rating", "Entry Context", "Trend Strength", "Stop Loss", "Vol Footprint"]
        w_df_check = load_sheet_data("Watchlist", WATCHLIST_COLS)
        
        if not w_df_check.empty and clean_p_watchlist in w_df_check["Ticker"].values:
            st.button("✅ Already in Watchlist", disabled=True, use_container_width=True, key="btn_w_dis")
        else:
            if st.button("➕ Add to Watchlist", use_container_width=True, key="btn_w_add"):
                with st.spinner("Syncing to Cloud Database..."):
                    w_df_check = load_sheet_data("Watchlist", WATCHLIST_COLS)
                    if clean_p_watchlist not in w_df_check["Ticker"].values:
                        new_row = pd.DataFrame([{
                            "Ticker": clean_p_watchlist,
                            "Price": round(ui_cmp, 2),
                            "Rating": ui_rating,
                            "Entry Context": ui_ctx,
                            "Trend Strength": ui_trend,
                            "Stop Loss": round(ui_stop * 0.98, 2) if ui_stop > 0 else 0.0,
                            "Vol Footprint": "Pending Scan..."
                        }])
                        w_df_check = pd.concat([w_df_check, new_row], ignore_index=True)
                        save_sheet_data("Watchlist", w_df_check, WATCHLIST_COLS)
                        st.success(f"Added {clean_p_watchlist} to Watchlist!")
                        st.rerun()

    st.divider()

# ===================================================================
# LIVE PORTFOLIO & WATCHLIST — Middle Layer
# ===================================================================
st.markdown("---")

# ── Live Portfolio (Full Width) ───────────────────────────────────
st.subheader("💼 Live Portfolio")
if st.session_state["sheets_error"]:
    st.error("⚠️ Google Sheets Connection Error: Portfolio management is temporarily unavailable.")

p_schema = ["Ticker", "Buy_Price", "Initial_Stop", "Highest_Trail", "Quantity", "Date_Added", "CMP", "RSI_HTML", "T1_HTML", "PCT_HTML", "Vol_Foot", "Verdict_HTML", "_verdict_rank", "_vol_rank"]
p_df = load_sheet_data("Portfolio", p_schema)
if not p_df.empty:
    port_display_rows = []

    for idx, row in p_df.iterrows():
        ticker = row["Ticker"]
        if not ticker or pd.isna(ticker) or str(ticker).strip() == '': continue
        
        # Read pre-calculated fields
        def safe_float(val, default=0.0):
            if val is None or pd.isna(val) or str(val).strip() == "": return default
            try: return float(val)
            except: return default

        buy_price = safe_float(row.get("Buy_Price", 0))
        cmp = safe_float(row.get("CMP", 0))
        init_stop = safe_float(row.get("Initial_Stop", 0))
        current_trail = safe_float(row.get("Highest_Trail", 0))
        
        # Check if we have processed data or if it's "Pending"
        v_html = row.get("Verdict_HTML")
        if not v_html or pd.isna(v_html) or str(v_html).strip().lower() in ["nan", "none", ""]:
            v_html = "<span style='color:gray;'>Pending Scan...</span>"
            rsi_h, t1_h, pct_h, v_foot = "...", "...", "...", "..."
            v_rank, vol_rank = -1, -1
        else:
            rsi_h = row.get("RSI_HTML", "...")
            t1_h = row.get("T1_HTML", "...")
            pct_h = row.get("PCT_HTML", "...")
            v_foot = row.get("Vol_Foot", "...")
            v_rank = row.get("_verdict_rank", -1)
            vol_rank = row.get("_vol_rank", -1)

        # Count alerts for the Status Hub (Live counts)
        if "SELL" in str(v_html):
            total_sell_alerts += 1

        port_display_rows.append({
            "_idx": idx,
            "_ticker": ticker,
            "_verdict_rank": v_rank,
            "_vol_rank": vol_rank,
            "_raw_buy_price": buy_price,
            "_raw_cmp": cmp,
            "_raw_qty": row.get("Quantity", 1),
            "_raw_date": row.get("Date_Added", ""),
            "Ticker": ticker,
            "Buy_Price": f"₹{format_indian(buy_price, is_price=True)}",
            "CMP": f"₹{format_indian(cmp, is_price=True)}",
            "Init_Stop": f"₹{format_indian(init_stop, is_price=True)}",
            "Trail_Stop": f"₹{format_indian(current_trail, is_price=True)}",
            "RSI_HTML": rsi_h,
            "T1_HTML": t1_h,
            "PCT_HTML": pct_h,
            "Vol_Foot": v_foot,
            "Verdict_HTML": v_html
        })

    if port_display_rows:
        p_sort = st.selectbox("Sort Portfolio By:", ["Verdict (Action Needed)", "Default (Date Added)", "Volume Footprint"], index=0)
        if "Verdict" in p_sort: port_display_rows.sort(key=lambda x: x.get("_verdict_rank", -1))
        elif "Volume" in p_sort: port_display_rows.sort(key=lambda x: x.get("_vol_rank", -1), reverse=True)

        # 12-column header
        P_COL_LAYOUT = [1.5, 1.1, 1.1, 1.1, 1.2, 1.0, 1.5, 1.2, 1.8, 1.8, 0.9, 0.9]
        HEADERS = ["Ticker", "Buy Price", "CMP", "Init Stop", "Trail Stop", "RSI", "T1 (Book 50%)", "% to Stop", "Vol Foot", "Verdict", "Analyze", "Close"]
        h_col = st.columns(P_COL_LAYOUT)
        for col, header in zip(h_col, HEADERS):
            col.markdown(f"**{header}**")
        st.markdown("---")

        for pr in port_display_rows:
            r_col = st.columns(P_COL_LAYOUT)
            r_col[0].write(pr["Ticker"])
            r_col[1].write(pr["Buy_Price"])
            r_col[2].write(pr["CMP"])
            r_col[3].write(pr["Init_Stop"])
            r_col[4].write(pr["Trail_Stop"])
            r_col[5].markdown(pr["RSI_HTML"], unsafe_allow_html=True)
            r_col[6].markdown(pr["T1_HTML"], unsafe_allow_html=True)
            r_col[7].markdown(pr["PCT_HTML"], unsafe_allow_html=True)
            r_col[8].write(pr["Vol_Foot"])
            r_col[9].markdown(pr["Verdict_HTML"], unsafe_allow_html=True)
            if r_col[10].button("Analyze", key=f"p_an_{pr['_ticker']}_{pr['_idx']}", on_click=set_search_ticker, args=(pr["_ticker"],)): pass
            if r_col[11].button("Log & Close", key=f"p_close_{pr['_ticker']}_{pr['_idx']}"):
                with st.spinner("Archiving trade..."):
                    # 1. Load Journal
                    c_schema = ["Ticker", "Buy_Date", "Sell_Date", "Buy_Price", "Sell_Price", "Quantity", "PnL_Value", "PnL_Pct", "Exit_State", "Days_Held"]
                    c_df = load_sheet_data("ClosedTrades", c_schema)
                    
                    # 2. Calculate Final Metrics
                    raw_buy = float(pr["_raw_buy_price"])
                    raw_sell = float(pr["_raw_cmp"])
                    raw_qty = float(pr["_raw_qty"])
                    
                    buy_date = pd.to_datetime(pr["_raw_date"]).date()
                    sell_date = datetime.now(IST).date()
                    days_held = max(0, (sell_date - buy_date).days)
                    
                    pnl_val = (raw_sell - raw_buy) * raw_qty
                    pnl_pct = ((raw_sell - raw_buy) / raw_buy) * 100 if raw_buy > 0 else 0
                    
                    # 3. Create Archive Row
                    new_log = pd.DataFrame([{
                        "Ticker": pr["Ticker"],
                        "Buy_Date": buy_date.strftime("%Y-%m-%d"),
                        "Sell_Date": sell_date.strftime("%Y-%m-%d"),
                        "Buy_Price": round(raw_buy, 2),
                        "Sell_Price": round(raw_sell, 2),
                        "Quantity": raw_qty,
                        "PnL_Value": round(pnl_val, 2),
                        "PnL_Pct": round(pnl_pct, 2),
                        "Exit_State": pr["Vol_Foot"],
                        "Days_Held": days_held
                    }])
                    
                    # 4. Save to Journal & Remove from Live
                    c_df = pd.concat([c_df, new_log], ignore_index=True)
                    save_sheet_data("ClosedTrades", c_df, c_schema)
                    
                    p_df = p_df.drop(pr["_idx"])
                    save_sheet_data("Portfolio", p_df, p_schema)
                    
                    # 5. Success Notification
                    pnl_icon = "🟢" if pnl_pct >= 0 else "🔴"
                    log_alert(f"✅ Trade Closed! Final PnL: {pnl_icon} {pnl_pct:.2f}% logged to journal.", icon="✅")
                    time.sleep(1)
                    st.rerun()
else:
    st.info("🔍 Portfolio is empty. Search for a ticker above, then click '➕ Add to Portfolio'.")

st.markdown("<br><br>", unsafe_allow_html=True)

# ── Watchlist (Full Width) ───────────────────────────────────
st.subheader("⭐ Watchlist")
if st.session_state.get("sheets_error"):
    st.error("⚠️ Google Sheets Connection Error: Watchlist management is temporarily unavailable.")



WATCHLIST_COLS = ["Ticker", "Price", "Rating", "Entry Context", "Trend Strength", "Stop Loss", "Vol Footprint"]
w_df = load_sheet_data("Watchlist", WATCHLIST_COLS)

if not w_df.empty:
    display_rows = []
    for idx, row in w_df.iterrows():
        ticker = row["Ticker"]
        if not ticker or pd.isna(ticker) or str(ticker).strip() == '' or str(ticker).lower() == 'nan':
            continue

        # Read pre-calculated fields
        w_cmp = row.get("Price", 0)
        w_rating = str(row.get("Rating", "AVOID"))
        ctx_live = str(row.get("Entry Context", "N/A"))
        t_pts_w = str(row.get("Trend Strength", "0/2"))
        w_vol_foot = str(row.get("Vol Footprint", "⚪ Normal"))
        if w_vol_foot.strip().lower() in ["nan", "none", ""]:
            w_vol_foot = "Pending Scan..."
        
        # Rankings for sorting (Fallback to logical mappings if not present)
        # Rating Rank
        if "STRONG" in w_rating: score_w = 7
        elif "MODERATE" in w_rating: score_w = 5
        elif "WATCHLIST" in w_rating: score_w = 3
        else: score_w = 0
        
        # Context Rank
        c_risk = 0 if "SAFE" in ctx_live else 1 if "FAIR" in ctx_live else 2
        
        # Trend Rank
        trend_val = 2 if "2/2" in t_pts_w else 1 if "1/2" in t_pts_w else 0
        
        # Vol Rank
        v_rank = 2 if "Accumulation" in w_vol_foot else 0 if "DISTRIBUTION" in w_vol_foot else 1

        if "STRONG BUY" in w_rating or "🟢 Accumulation" in w_vol_foot:
            total_buy_alerts += 1

        display_rows.append({
            "_idx": idx,
            "_ticker": ticker,
            "_rating_rank": score_w,
            "_trend_rank": trend_val,
            "_ctx_risk": c_risk,
            "_vol_rank": v_rank,
            "Ticker": ticker,
            "Price": f"₹{format_indian(w_cmp, is_price=True)}",
            "Rating": w_rating,
            "Entry Context": ctx_live,
            "Trend": t_pts_w,
            "Vol Footprint": w_vol_foot,
        })

    if display_rows:
        w_sort = st.selectbox("Sort Watchlist By:", ["Rating (Strongest First)", "Default (None)", "Entry Context (Lowest Risk)", "Trend Strength", "Volume Footprint"], index=0)
        if "Rating" in w_sort: display_rows.sort(key=lambda x: x.get("_rating_rank", -1), reverse=True)
        elif "Context" in w_sort: display_rows.sort(key=lambda x: x.get("_ctx_risk", 99))
        elif "Trend" in w_sort: display_rows.sort(key=lambda x: x.get("_trend_rank", -1), reverse=True)
        elif "Volume" in w_sort: display_rows.sort(key=lambda x: x.get("_vol_rank", -1), reverse=True)
        
        COL_LAYOUT = [1.5, 1.2, 1.5, 1.0, 1.5, 1.8, 1, 1]
        HEADERS = ["Ticker", "Price", "Entry Context", "Trend", "Rating", "Vol Footprint", "Analyze", "Del"]

        # Header row
        h_cols = st.columns(COL_LAYOUT)
        for col, header in zip(h_cols, HEADERS):
            col.markdown(f"**{header}**")
        st.markdown("---")

        # Data rows — all key columns HTML color-coded, buttons inline
        for dr in display_rows:
            # Rating color
            rating_str = str(dr.get("Rating", "")).upper()
            if "BUY" in rating_str:
                r_color = "#00d26a"
            elif "HOLD" in rating_str or "WATCHLIST" in rating_str:
                r_color = "#fbd63f"
            else:
                r_color = "#f7556a"
            rating_html = f"<span style='color:{r_color}; font-weight:bold;'>{dr['Rating']}</span>"

            # Entry Context color
            ctx_str = str(dr.get("Entry Context", "")).upper()
            if "SAFE" in ctx_str:
                ctx_color = "#00d26a"
            elif "FAIR" in ctx_str:
                ctx_color = "#fbd63f"
            else:
                ctx_color = "#f7556a"  # OVEREXTENDED / OVERBOUGHT / N/A
            ctx_html = f"<span style='color:{ctx_color}; font-weight:bold;'>{ctx_str}</span>"

            # Trend Strength color
            trend_str = str(dr.get("Trend", dr.get("Trend Strength", ""))).upper()
            if "2/2" in trend_str or "BULL" in trend_str:
                trend_color = "#00d26a"
            elif "1/2" in trend_str:
                trend_color = "#fbd63f"
            else:
                trend_color = "#f7556a"  # 0/2 or Bearish
            trend_html = f"<span style='color:{trend_color}; font-weight:bold;'>{trend_str}</span>"

            r_cols = st.columns(COL_LAYOUT)
            r_cols[0].write(dr["Ticker"])
            r_cols[1].write(dr["Price"])
            r_cols[2].markdown(ctx_html, unsafe_allow_html=True)
            r_cols[3].markdown(trend_html, unsafe_allow_html=True)
            r_cols[4].markdown(rating_html, unsafe_allow_html=True)
            r_cols[5].write(dr["Vol Footprint"])
            if r_cols[6].button("Analyze", key=f"an_{dr['_ticker']}_{dr['_idx']}", use_container_width=True, on_click=set_search_ticker, args=(dr["_ticker"],)):
                pass
            if r_cols[7].button("🗑️", key=f"del_{dr['_ticker']}_{dr['_idx']}"):
                w_df = w_df.drop(dr["_idx"])
                w_df["Rating"] = w_df["Rating"].astype(str).replace(
                    {"nan": "AVOID", "NaN": "AVOID", "None": "AVOID", "": "AVOID"}
                )
                save_sheet_data("Watchlist", w_df, WATCHLIST_COLS)
                st.rerun()
else:
    st.info("🔍 Watchlist is empty. Search for a ticker above, then click '➕ Add to Watchlist'.")

# ===================================================================
# BATCH ENGINE — Persistent Bottom Layer (Optimized Side-by-Side Split)
# ===================================================================
st.markdown("---")
render_control_center()

# ── Trade Journal & Analytics (Toggleable) ─────────────────────────────────────────────
st.markdown("---")
j_col1, j_col2 = st.columns([0.8, 0.2])
with j_col1:
    st.subheader("📊 Trade Journal & Analytics")
with j_col2:
    st.markdown("<div style='padding-top: 12px;'></div>", unsafe_allow_html=True)
    j_label = "Close Journal" if st.session_state["show_journal"] else "Open Journal"
    if st.button(j_label, use_container_width=True, key="journal_toggle_btn"):
        st.session_state["show_journal"] = not st.session_state["show_journal"]
        st.rerun()

# Only execute data loading and rendering if the journal is toggled ON
if st.session_state["show_journal"]:
    if st.session_state.get("sheets_error"):
        st.error("⚠️ Google Sheets Connection Error: Trade Journal is temporarily unavailable.")
    else:
        c_schema = ["Ticker", "Buy_Date", "Sell_Date", "Buy_Price", "Sell_Price", "Quantity", "PnL_Value", "PnL_Pct", "Exit_State", "Days_Held"]
        c_df = load_sheet_data("ClosedTrades", c_schema)

        # ── Explicit journal backup anchored to project root ────────
        try:
            backup_path = os.path.join(BASE_DIR, "db_backup_Journal_HighRes.csv")
            c_df.to_csv(backup_path, index=False)
        except Exception:
            pass  # Never let a disk write block the UI

        if not c_df.empty:
            # 1. Clean Data for Math
            c_df["PnL_Value"] = pd.to_numeric(c_df["PnL_Value"], errors='coerce').fillna(0)
            c_df["PnL_Pct"] = pd.to_numeric(c_df["PnL_Pct"], errors='coerce').fillna(0)

            # 2. Calculate Key Performance Indicators (KPIs)
            total_trades = len(c_df)
            winning_trades = len(c_df[c_df["PnL_Pct"] > 0])
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0

            net_pnl = c_df["PnL_Value"].sum()
            avg_return = c_df["PnL_Pct"].mean()
            best_trade = c_df["PnL_Pct"].max()
            avg_days = pd.to_numeric(c_df["Days_Held"], errors='coerce').mean()

            # 3. Render Top-Level Metrics
            st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
            a1, a2, a3, a4, a5 = st.columns(5)

            a1.metric("Total Trades", total_trades)
            a2.metric("Win Rate", f"{win_rate:.1f}%")

            pnl_color = "normal" if net_pnl >= 0 else "inverse"
            pnl_label = "Profitable" if net_pnl >= 0 else "Drawdown"
            a3.metric("Net P&L", f"₹{format_indian(net_pnl, is_price=True)}", delta=pnl_label, delta_color=pnl_color)

            a4.metric("Avg Return", f"{avg_return:.2f}%", delta=f"{avg_days:.1f} Days Held", delta_color="off")
            a5.metric("Best Trade", f"{best_trade:.2f}%")

            st.markdown("<br>", unsafe_allow_html=True)

            # 4. Render Historical Ledger
            st.markdown("##### 📜 Historical Ledger")

            display_c_df = c_df.copy()
            display_c_df["PnL_Value"] = display_c_df["PnL_Value"].apply(lambda x: f"₹{format_indian(x, is_price=True)}")
            display_c_df["PnL_Pct"] = display_c_df["PnL_Pct"].apply(lambda x: f"{x:+.2f}%")
            display_c_df["Buy_Price"] = display_c_df["Buy_Price"].apply(lambda x: f"₹{format_indian(float(x), is_price=True)}")
            display_c_df["Sell_Price"] = display_c_df["Sell_Price"].apply(lambda x: f"₹{format_indian(float(x), is_price=True)}")

            display_c_df = display_c_df.sort_values(by="Sell_Date", ascending=False).reset_index(drop=True)
            st.dataframe(display_c_df, use_container_width=True, hide_index=True)

        else:
            st.info("📉 Trade Journal is empty. Close a trade in your Live Portfolio to generate analytics.")
else:
    st.info("📂 Click **Open Journal** to load historical analytics and trade history.")

st.markdown("<br><br>", unsafe_allow_html=True)


# ===================================================================
# Footer
# ===================================================================


st.divider()
st.caption("Data sourced from Yahoo Finance. News via Google News. System Generated Technical Report. Built with Streamlit.")
st.caption("⚠️ This tool is for educational purposes only. Not financial advice.")

try:
    render_status_hub(hub_placeholder, total_buy_alerts, total_sell_alerts)
except Exception as e:
    st.error(f"⚠️ Status Hub Sync Error: {e}")
