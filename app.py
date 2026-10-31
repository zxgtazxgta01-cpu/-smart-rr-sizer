import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Smart RR & Position Sizer", page_icon="📐")
st.title("📐 Smart RR & Position Sizer")

TZ = ZoneInfo("Asia/Bangkok")
JCOLS = ["time", "asset", "dir", "entry", "sl", "tp", "rr", "lots", "risk", "result"]
RESULTS = ["Open", "Win", "Loss", "BE"]

# value = มูลค่าต่อ 1.0 ของราคา ต่อ 1 ล็อต (ค่าทั่วไป ปรับตามโบรกเกอร์)
ASSETS = {
    "Gold (XAUUSD)": {"ticker": "GC=F", "value": 100.0, "dec": 2},
    "NAS100": {"ticker": "NQ=F", "value": 1.0, "dec": 2},
    "EURUSD": {"ticker": "EURUSD=X", "value": 100000.0, "dec": 5},
    "Custom": {"ticker": "", "value": 1.0, "dec": 4},
}
TF = {"15m": ("15m", "5d"), "1h": ("1h", "1mo"), "1d": ("1d", "6mo")}

ss = st.session_state
ss.setdefault("entry", 100.0)
ss.setdefault("atr", 1.0)
if "journal" not in ss:
    ss["journal"] = pd.DataFrame(columns=JCOLS)


@st.cache_data(ttl=600, show_spinner="กำลังดึงราคา...")
def fetch_atr(ticker, interval, period, length=14):
    import yfinance as yf

    df = yf.download(ticker, period=period, interval=interval,
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


tab_calc, tab_j = st.tabs(["🧮 Calculator", "📒 Journal"])

# =============================== CALCULATOR ===============================
with tab_calc:
    c1, c2, c3 = st.columns(3)
    asset_name = c1.selectbox("Asset", list(ASSETS))
    direction = c2.radio("Direction", ["Long", "Short"], horizontal=True)
    tf = c3.selectbox("ATR timeframe", list(TF), index=1)
    asset = ASSETS[asset_name]
    dec = asset["dec"]
    is_long = direction == "Long"

    refresh = st.button("🔄 Refresh price & ATR", disabled=not asset["ticker"])
    sig = (asset_name, tf)
    note = ""
    if asset["ticker"] and (ss.get("sig") != sig or refresh):
        try:
            if refresh:
                fetch_atr.clear()
            res = fetch_atr(asset["ticker"], *TF[tf])
            if res:
                ss["atr"], ss["entry"] = res
            else:
                note = "ไม่พบข้อมูลราคา กรุณากรอก Entry และ ATR เอง"
        except Exception as e:
            note = f"ดึงข้อมูลไม่สำเร็จ ({e}) กรุณากรอกเอง"
    ss["sig"] = sig
    if note:
        st.warning(note)

    e1, e2 = st.columns(2)
    entry = e1.number_input("Entry", min_value=0.0, key="entry", format=f"%.{dec}f")
    atr = e2.number_input("ATR (14)", min_value=0.0, key="atr", format=f"%.{dec}f")

    with st.expander("💰 Account & Risk", expanded=True):
        a1, a2 = st.columns(2)
        balance = a1.number_input("Balance ($)", min_value=1.0, value=1000.0, step=100.0)
        preset = a2.radio("Risk per trade", ["0.5%", "1%", "2%", "Custom"],
                          index=1, horizontal=True)
        if preset == "Custom":
            risk_pct = st.number_input("Custom Risk %", min_value=0.01,
                                       max_value=100.0, value=1.0, step=0.1)
        else:
            risk_pct = {"0.5%": 0.5, "1%": 1.0, "2%": 2.0}[preset]
        m1, m2 = st.columns(2)
        max_loss = m1.number_input("Max daily loss (%)", min_value=0.1, value=3.0, step=0.1)
        extra_loss = m2.number_input("Other losses today (%)", min_value=0.0, value=0.0,
                                     step=0.1, help="ขาดทุนที่ไม่ได้บันทึกใน Journal")

    with st.expander("⚙️ Asset spec (Contract size)"):
        value_per_unit = st.number_input(
            "Value per 1.0 price move per 1 lot", min_value=0.0001,
            value=asset["value"], key=f"val_{asset_name}",
            help="ตรวจกับโบรกเกอร์ เช่น ทอง 100 oz/lot = 100, EURUSD = 100000")
        l1, l2 = st.columns(2)
        lot_step = l1.number_input("Lot step", min_value=0.0001, value=0.01, format="%.4f")
        min_lot = l2.number_input("Minimum lot", min_value=0.0001, value=0.01, format="%.4f")

    with st.expander("🎯 Trade settings"):
        t1, t2 = st.columns(2)
        atr_mult = t1.number_input("ATR multiplier (SL)", min_value=0.1, value=1.5, step=0.1)
        rr_target = t2.number_input("Target R:R", min_value=0.1, value=2.0, step=0.1)
        min_rr = t1.number_input("Minimum R:R allowed", min_value=0.1, value=2.0, step=0.1)
        sl_manual = t2.number_input("Manual SL (0 = use ATR)", min_value=0.0,
                                    value=0.0, format=f"%.{dec}f")
        tp_manual = t1.number_input("Manual TP (0 = use R:R)", min_value=0.0,
                                    value=0.0, format=f"%.{dec}f")

    # ---------- Daily loss (auto จาก Journal) ----------
    j = ss["journal"]
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    auto_loss = 0.0
    if len(j):
        mask = j["time"].astype(str).str.startswith(today) & (j["result"] == "Loss")
        auto_loss = float(pd.to_numeric(j.loc[mask, "risk"], errors="coerce").sum())
    loss_used = auto_loss / balance * 100 + extra_loss

    # ---------- Calculation ----------
    sl = sl_manual if sl_manual > 0 else (
        entry - atr_mult * atr if is_long else entry + atr_mult * atr)
    sl_dist = abs(entry - sl)
    tp = tp_manual if tp_manual > 0 else (
        entry + sl_dist * rr_target if is_long else entry - sl_dist * rr_target)

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

    # ---------- Result ----------
    st.subheader("Result")
    with st.container(border=True):
        if not valid:
            st.error("SL/TP ไม่สมเหตุสมผลกับทิศทาง ตรวจ Entry, SL, TP")
        else:
            if can_trade:
                st.success(f"✅ READY · Lot {lots:g}")
            else:
                st.error("⛔ BLOCKED")
            k1, k2, k3 = st.columns(3)
            k1.metric("Stop Loss", f"{sl:.{dec}f}")
            k2.metric("Take Profit", f"{tp:.{dec}f}")
            k3.metric("R:R", f"1 : {rr:.2f}")
            k4, k5 = st.columns(2)
            k4.metric("Lot size", f"{lots:g}" if lot_ok else "-")
            k5.metric("Real risk", f"${real_risk:,.2f} ({real_risk / balance * 100:.2f}%)")

            if not rr_ok:
                st.warning(f"R:R {rr:.2f} ต่ำกว่าขั้นต่ำ {min_rr} ปรับ TP หรือ Target R:R")
            if not dd_ok:
                st.warning(f"ขาดทุนวันนี้ {loss_used:.2f}% ถึงเพดาน {max_loss}% แล้ว หยุดเทรดวันนี้")
            if not lot_ok:
                min_risk = min_lot * sl_dist * value_per_unit
                need_bal = min_risk / (risk_pct / 100)
                max_sl = risk_amt / (min_lot * value_per_unit)
                st.warning(
                    f"Lot ต่ำกว่าขั้นต่ำ: ที่ {min_lot:g} lot จะเสี่ยง ${min_risk:,.2f} "
                    f"({min_risk / balance * 100:.2f}%) เกิน {risk_pct}% ที่ตั้งไว้\n\n"
                    f"ทางแก้: Balance ≥ ${need_bal:,.0f} หรือ SL ไม่เกิน {max_sl:.{dec}f} "
                    f"หรือเพิ่ม Risk %")

    if st.button("💾 Save to journal", disabled=not can_trade):
        row = {"time": datetime.now(TZ).strftime("%Y-%m-%d %H:%M"),
               "asset": asset_name, "dir": direction,
               "entry": round(entry, dec), "sl": round(sl, dec), "tp": round(tp, dec),
               "rr": round(rr, 2), "lots": lots, "risk": round(real_risk, 2),
               "result": "Open"}
        new = pd.DataFrame([row])
        ss["journal"] = new if ss["journal"].empty else pd.concat(
            [ss["journal"], new], ignore_index=True)
        st.toast("บันทึกแล้ว ✅")

# ================================ JOURNAL =================================
with tab_j:
    up = st.file_uploader("โหลดสมุดเทรดจาก CSV (ที่เคยดาวน์โหลดไว้)", type="csv")
    if up is not None and ss.get("loaded_name") != up.name:
        try:
            loaded = pd.read_csv(up)
            for col in JCOLS:
                if col not in loaded.columns:
                    loaded[col] = "Open" if col == "result" else None
            ss["journal"] = loaded[JCOLS]
            ss["loaded_name"] = up.name
            st.rerun()
        except Exception as e:
            st.error(f"อ่านไฟล์ไม่ได้: {e}")

    jr = ss["journal"]
    if jr.empty:
        st.info("ยังไม่มีรายการ กด Save to journal ในแท็บ Calculator")
    else:
        st.caption("แตะช่อง result เพื่อบันทึกผล: Win / Loss / BE")
        edited = st.data_editor(
            jr, use_container_width=True, hide_index=True, key="jed",
            disabled=[c for c in JCOLS if c != "result"],
            column_config={"result": st.column_config.SelectboxColumn(
                "result", options=RESULTS, required=True)})
        ss["journal"] = edited

        d = edited.copy()
        d["rr"] = pd.to_numeric(d["rr"], errors="coerce")
        closed = d[d["result"].isin(["Win", "Loss", "BE"])].copy()
        r_map = {"Win": closed["rr"], "Loss": -1.0, "BE": 0.0}
        closed["R"] = closed.apply(
            lambda r: r["rr"] if r["result"] == "Win"
            else (-1.0 if r["result"] == "Loss" else 0.0), axis=1)
        wins = int((closed["result"] == "Win").sum())
        losses = int((closed["result"] == "Loss").sum())

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Trades", len(d))
        s2.metric("Avg planned R:R", f"{d['rr'].mean():.2f}")
        s3.metric("Win rate", f"{wins / (wins + losses) * 100:.0f}%" if wins + losses else "-")
        s4.metric("Total R", f"{closed['R'].sum():+.2f}" if len(closed) else "-")

        st.download_button("⬇️ ดาวน์โหลด CSV", edited.to_csv(index=False).encode("utf-8"),
                           "journal.csv", "text/csv")
        if st.button("🗑️ ล้างสมุดเทรด"):
            ss["journal"] = pd.DataFrame(columns=JCOLS)
            ss.pop("loaded_name", None)
            st.rerun()

st.caption("เครื่องมือช่วยจัดการความเสี่ยงเพื่อการเรียนรู้ ไม่ใช่คำแนะนำการลงทุน "
           "ตรวจ Contract size กับโบรกเกอร์ทุกครั้ง")

