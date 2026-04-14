import streamlit as st
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from data.loader import load_referrals
from data.transforms import compute_metrics, compute_velocity, generate_summary
from data.session_log import log_event
from tabs import by_account, by_ppm, by_geo, conversion_deep_dive, visit_prep, raw_data, faq, quota

st.set_page_config(page_title="Northeast Beast's Control Tower", layout="wide")

st.markdown("""
<style>
div[data-testid="stPopoverBody"] { min-width: 700px; max-width: 800px; }
div[data-testid="stPopover"] button[kind="secondary"] {
    font-size: 10px !important;
    padding: 2px 8px !important;
    min-height: 0 !important;
    height: auto !important;
    line-height: 1.2 !important;
}
div[data-testid="stPopover"] button[kind="secondary"] p {
    font-size: 10px !important;
}
</style>
""", unsafe_allow_html=True)

# --- Login gate ---
if "user_name" not in st.session_state:
    st.session_state["user_name"] = ""

if not st.session_state["user_name"]:
    st.markdown("")
    col_l, col_m, col_r = st.columns([1, 1, 1])
    with col_m:
        st.image("assets/logo.webp", width=100)
        st.markdown("### Northeast Beast's Control Tower")
        name = st.text_input("Enter your name to continue", placeholder="e.g., Ashley Alexander", key="login_name")
        if st.button("Enter", key="login_btn", use_container_width=True):
            if name and name.strip():
                st.session_state["user_name"] = name.strip()
                log_event(name.strip(), "login")
                st.rerun()
            else:
                st.warning("Please enter your name.")
    st.stop()

# --- Logged in ---
user = st.session_state["user_name"]

logo_col, title_col = st.columns([0.07, 0.93])
with logo_col:
    st.image("assets/logo.webp", width=60)
with title_col:
    st.title("Northeast Beast's Control Tower")

# --- Load data (all regions) ---
df_all = load_referrals()

# --- Sidebar ---
with st.sidebar:
    st.markdown(f"Logged in as **{user}**")
    st.header("Filters")

    ne_data = df_all[df_all["AREA"] == "Northeast"]
    min_date = ne_data["REFERRAL_DATE"].min().date()
    max_date = ne_data["REFERRAL_DATE"].max().date()
    default_start = (pd.Timestamp.now() - pd.DateOffset(months=3)).replace(day=1).date()
    if default_start < min_date:
        default_start = min_date

    date_range = st.date_input(
        "Date range", value=(default_start, max_date),
        min_value=min_date, max_value=max_date, key="date_range",
    )
    if len(date_range) == 2:
        start, end = date_range
        df_all = df_all[(df_all["REFERRAL_DATE"].dt.date >= start) & (df_all["REFERRAL_DATE"].dt.date <= end)]

    df = df_all[df_all["AREA"] == "Northeast"]

    st.divider()
    granularity = st.radio("Time granularity", ["Month", "Week"], horizontal=True, key="granularity")
    period_col = "month_of" if granularity == "Month" else "week_of"

    st.divider()
    st.caption(f"{len(df):,} NE referrals loaded")
    st.caption(f"Data as of {df['REFERRAL_DATE'].max().strftime('%b %d, %Y')}")

    # Full Excel export
    from components.excel_export import generate_full_export
    excel_bytes = generate_full_export(df, period_col)
    if excel_bytes:
        st.download_button(
            "Export Full Dashboard to Excel",
            excel_bytes,
            file_name="NE_Control_Tower_Export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="full_excel_export",
        )

    # Usage log viewer (admin only)
    with st.expander("Usage Log"):
        from data.session_log import get_log
        log_data = get_log()
        if log_data:
            log_df = pd.DataFrame(log_data)
            log_df["timestamp"] = pd.to_datetime(log_df["timestamp"]).dt.strftime("%b %d %I:%M %p")
            st.dataframe(log_df.tail(50).iloc[::-1], use_container_width=True, hide_index=True)
        else:
            st.caption("No sessions recorded yet.")

# --- Banner ---
summary = generate_summary(df, period_col)
velocity = compute_velocity(df, period_col)
banner_parts = []
if summary:
    banner_parts.append(summary)
if velocity:
    direction = "ahead of" if velocity["pct_vs_prior"] > 0 else "behind"
    banner_parts.append(
        f"Pacing: {velocity['label']} has {velocity['current']:,} so far, "
        f"on track for <b>{velocity['projected']:,}</b> ({direction} {abs(velocity['pct_vs_prior']):.0%} vs prior)."
    )
if banner_parts:
    st.markdown(
        '<div style="background: linear-gradient(90deg, #e8f4fd 0%, #f5f7fa 100%); '
        'padding: 10px 16px; border-radius: 8px; border-left: 4px solid #4A90D9; margin-bottom: 12px; font-size: 14px;">'
        + " ".join(banner_parts) + "</div>",
        unsafe_allow_html=True,
    )

# --- Tabs with tracking ---
tab1, tab2, tab3, tab5, tab_quota, tab6, tab7, tab_wip = st.tabs([
    "Market Health", "My Team", "Map",
    "Visit Prep", "Quota", "Raw Data", "How We Calculate",
    "Work in Progress",
])

# Track which tab was viewed (log on first render per session per tab)
if "tabs_viewed" not in st.session_state:
    st.session_state["tabs_viewed"] = set()

def _track_tab(tab_name):
    if tab_name not in st.session_state["tabs_viewed"]:
        st.session_state["tabs_viewed"].add(tab_name)
        log_event(user, "tab_view", tab_name)

with tab1:
    _track_tab("Market Health")
    by_account.render(df, period_col, df_all=df_all)

with tab2:
    _track_tab("My Team")
    by_ppm.render(df, period_col)

with tab3:
    _track_tab("Map")
    by_geo.render(df, period_col)

with tab5:
    _track_tab("Visit Prep")
    visit_prep.render(df, period_col)

with tab_quota:
    _track_tab("Quota")
    quota.render(df)

with tab6:
    _track_tab("Raw Data")
    raw_data.render(df, period_col)

with tab7:
    _track_tab("How We Calculate")
    faq.render()

with tab_wip:
    _track_tab("Work in Progress")
    st.subheader("Work in Progress")
    st.caption("Features under development. Data and methodology may change.")

    st.markdown(
        '<div style="background-color: #fff3cd; padding: 8px 14px; border-radius: 6px; font-size: 13px; border-left: 4px solid #ffc107;">'
        'Conversion funnel root cause analysis — under active development.</div>',
        unsafe_allow_html=True,
    )
    conversion_deep_dive.render(df, period_col)
