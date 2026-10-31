import math
from datetime import datetime

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Smart RR & Position Sizer", page_icon="📐")
st.title("📐 Smart RR & Position Sizer")

# มูลค่าต่อ 1.0 ของราคา ต่อ 1 ล็อต (ค่าทั่วไป ต้องปรับตามโบรกเกอร์)
ASSETS = {
    "Gold (XAUUSD)": {"ticker": "GC=F", "value": 100.0},
    "NAS100": {"ticker": "NQ=F", "value": 1.0},
    "EURUSD": {"ticker": "EURUSD=X", "value": 100000.0},
    "Custom": {"ticker": "", "value": 1.0},
}

st.session_state.setdefault("entry", 100.0)
st.session_state.setdefault("atr", 1.0)
st.session_state.setdefault("journal", [])


@st.cache_data(ttl=600)
def fetch_atr(ticker, length=14, interval="1h"):
    import yfinance as yf

    df = yf.download(ticker, period="1mo", interval=interval,
                     progress=False, auto_adjust=False)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    prev = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - prev).abs(),
                    (df["Low"] - prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / length, adjust=False).mean()  # Wilder smoothing
    return float(atr.iloc[-1]), float(df["Close"].iloc[-1])


# ------------------------------ Sidebar ------------------------------
with st.sidebar:
    st.header("1) Account & Risk")
    balance = st.number_input("Account Balance", min_value=1.0, value=1000.0)
    preset = st.radio("Risk Preset", ["0.5%", "1%", "2%", "Custom"], index=1, horizontal=True)
    custom = st.number_input("Custom Risk %", min_value=0.01, max_value=100.0, value=1.0)
    risk_pct = {"0.5%": 0.5, "1%": 1.0, "2%": 2.0}.get(preset, custom)
    loss_used = st.number_input("Loss used today (%)", min_value=0.0, value=0.0, step=0.1)
    max_loss = st.number_input("Max daily loss (%)", min_value=0.1, value=3.0, step=0.1)

    st.header("2) Asset Spec")
    asset_name = st.selectbox("Asset", list(ASSETS))
    asset = ASSETS[asset_name]
    value_per_unit = st.number_input(
        "Value per 1.0 price move per 1 lot", min_value=0.0001,
        value=asset["value"], key=f"val_{asset_name}",
        help="ตรวจ Contract Size กับโบรกเกอร์ของคุณ เช่น ทอง 100 oz/lot = 100")
    lot_step = st.number_input("Lot step", min_value=0.0001, value=0.01, format="%.4f")
    min_lot = st.number_input("Minimum lot", min_value=0.0001, value=0.01, format="%.4f")

# ------------------------------ Trade setup --------------------------
st.subheader("Trade Setup")
if asset["ticker"] and st.button("ดึงราคา + ATR(14, 1H) อัตโนมัติ"):
    try:
        res = fetch_atr(asset["ticker"])
        if res:
            st.session_state["atr"], st.session_state["entry"] = res
        else:
            st.warning("ไม่พบข้อมูล ลองกรอกเอง")
    except Exception as e:
        st.warning(f"ดึงข้อมูลไม่สำเร็จ: {e}")

direction = st.radio("Direction", ["Long", "Short"], horizontal=True)
is_long = direction == "Long"

c1, c2 = st.columns(2)
entry = c1.number_input("Entry", min_value=0.0, key="entry", format="%.4f")
atr = c2.number_input("ATR", min_value=0.0, key="atr", format="%.4f")
atr_mult = c1.number_input("ATR multiplier (SL)", min_value=0.1, value=1.5, step=0.1)
rr_target = c2.number_input("Target R:R", min_value=0.1, value=2.0, step=0.1)
sl_manual = c1.number_input("Manual SL (0 = use ATR)", min_value=0.0, value=0.0, format="%.4f")
tp_manual = c2.number_input("Manual TP (0 = use R:R)", min_value=0.0, value=0.0, format="%.4f")
min_rr = st.number_input("Minimum R:R allowed", min_value=0.1, value=2.0, step=0.1)

# ------------------------------ Calculation --------------------------
sl = sl_manual if sl_manual > 0 else (entry - atr_mult * atr if is_long else entry + atr_mult * atr)
sl_dist = abs(entry - sl)
tp = tp_manual if tp_manual > 0 else (entry + sl_dist * rr_target if is_long else entry - sl_dist * rr_target)

valid = (sl_dist > 0
         and (sl < entry if is_long else sl > entry)
         and (tp > entry if is_long else tp < entry))

risk_amt = balance * risk_pct / 100
lots = rr = real_risk = 0.0
if valid:
    raw = risk_amt / (sl_dist * value_per_unit)
    lots = round(math.floor(raw / lot_step + 1e-9) * lot_step, 4)
    real_risk = lots * sl_dist * value_per_unit
    rr = abs(tp - entry) / sl_dist

rr_ok = valid and rr >= min_rr
dd_ok = loss_used < max_loss
lot_ok = valid and lots >= min_lot
can_trade = valid and rr_ok and dd_ok and lot_ok

# ------------------------------ Output -------------------------------
st.subheader("Result")
if not valid:
    st.error("SL/TP ไม่สมเหตุสมผลกับทิศทาง (เช็กราคา Entry, SL, TP)")
else:
    m1, m2, m3 = st.columns(3)
    m1.metric("Stop Loss", f"{sl:.4f}")
    m2.metric("Take Profit", f"{tp:.4f}")
    m3.metric("R:R", f"1 : {rr:.2f}")
    m4, m5 = st.columns(2)
    m4.metric("Lot size", f"{lots:.4f}" if can_trade else "LOCKED")
    m5.metric("Real risk", f"{real_risk:.2f} ({real_risk / balance * 100:.2f}%)")

st.subheader("Pre-Trade Checklist")
for ok, text in [(rr_ok, f"R:R >= {min_rr}"),
                 (dd_ok, f"Daily loss < {max_loss}%"),
                 (lot_ok, "Lot >= minimum")]:
    (st.success if ok else st.error)(("PASS: " if ok else "FAIL: ") + text)

if can_trade:
    st.success("✅ READY")
else:
    st.error("⛔ BLOCKED")

# ------------------------------ Journal ------------------------------
st.subheader("Trade Journal")
if st.button("บันทึกลงสมุดเทรด", disabled=not can_trade):
    st.session_state["journal"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "asset": asset_name, "dir": direction,
        "entry": entry, "sl": sl, "tp": tp,
        "rr": round(rr, 2), "lots": lots, "risk": round(real_risk, 2),
    })

if st.session_state["journal"]:
    jdf = pd.DataFrame(st.session_state["journal"])
    st.dataframe(jdf, use_container_width=True)
    st.caption(f"จำนวนไม้: {len(jdf)} | R:R เฉลี่ย: {jdf['rr'].mean():.2f}")
    st.download_button("ดาวน์โหลด CSV", jdf.to_csv(index=False).encode("utf-8"),
                       "journal.csv", "text/csv")
else:
    st.caption("ยังไม่มีรายการ")
