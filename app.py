import streamlit as st
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from data.loader import load_referrals, _csv_mtime
from data.chase_list import load_chase_list
from data.transforms import compute_metrics, compute_velocity, generate_summary
from data.session_log import log_event
from tabs import by_account, by_ppm, by_geo, conversion_deep_dive, visit_prep, raw_data, faq, quota

# ── Region config ──────────────────────────────────────────────────────────────
REGION_CONFIG = {
    "Northeast": {"title": "Northeast Mindshare Control Tower", "short": "NE"},
    "West":      {"title": "West Mindshare Control Tower",      "short": "West"},
    "Central":   {"title": "Central Mindshare Control Tower",   "short": "Central"},
}

# ── Session state defaults ─────────────────────────────────────────────────────
if "region" not in st.session_state:
    st.session_state["region"] = "Northeast"
if "user_name" not in st.session_state:
    st.session_state["user_name"] = ""

region     = st.session_state["region"]
region_cfg = REGION_CONFIG[region]

st.set_page_config(page_title=region_cfg["title"], layout="wide")

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
/* Region pill buttons on login */
div[data-testid="stHorizontalBlock"] .region-pill button {
    border-radius: 20px !important;
}
/* Sidebar region switcher buttons — never wrap */
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] button p {
    font-size: clamp(9px, 1.8vw, 13px) !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}
section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] button {
    padding-left: 4px !important;
    padding-right: 4px !important;
}
</style>
""", unsafe_allow_html=True)

# ── Login gate ─────────────────────────────────────────────────────────────────
if not st.session_state["user_name"]:
    st.markdown("")
    col_l, col_m, col_r = st.columns([1, 1.2, 1])
    with col_m:
        st.image(os.path.join(os.path.dirname(__file__), "assets", "t_logo.png"), width=80)

        # ── Region selector ──────────────────────────────────────
        st.markdown(
            '<p style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;'
            'color:#888;margin-bottom:4px;margin-top:4px">Select your region</p>',
            unsafe_allow_html=True,
        )
        r1, r2, r3 = st.columns(3)
        for col, (reg, cfg) in zip([r1, r2, r3], REGION_CONFIG.items()):
            with col:
                is_active = st.session_state["region"] == reg
                btn_style = "primary" if is_active else "secondary"
                if st.button(reg, key=f"region_btn_{reg}",
                             use_container_width=True, type=btn_style):
                    st.session_state["region"] = reg
                    st.rerun()

        # Re-read after any region change
        region     = st.session_state["region"]
        region_cfg = REGION_CONFIG[region]

        st.markdown(f"### {region_cfg['title']}")

        name = st.text_input(
            "Enter your name to continue",
            placeholder="e.g., Ashley Alexander",
            key="login_name",
        )
        if st.button("Enter", key="login_btn", use_container_width=True):
            if name and name.strip():
                st.session_state["user_name"] = name.strip()
                log_event(name.strip(), "login", region)
                st.rerun()
            else:
                st.warning("Please enter your name.")
    st.stop()

# ── Logged in ──────────────────────────────────────────────────────────────────
user = st.session_state["user_name"]

logo_col, title_col = st.columns([0.07, 0.93])
with logo_col:
    st.image(os.path.join(os.path.dirname(__file__), "assets", "t_logo.png"), width=60)
with title_col:
    st.title(region_cfg["title"])

# ── Load data (all regions) ────────────────────────────────────────────────────
df_all   = load_referrals(_mtime=_csv_mtime())
chase_df = load_chase_list()   # NE chase list (empty DataFrame if file missing)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"Logged in as **{user}**")

    # Region switcher in sidebar (so users can switch after login too)
    st.markdown(
        '<p style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;'
        'color:#888;margin-bottom:2px">Region</p>',
        unsafe_allow_html=True,
    )
    sw1, sw2, sw3 = st.columns(3)
    for col, (reg, cfg) in zip([sw1, sw2, sw3], REGION_CONFIG.items()):
        with col:
            is_active = st.session_state["region"] == reg
            if st.button(
                cfg["short"], key=f"sw_region_{reg}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state["region"] = reg
                # Reset date range so it recalculates for the new region
                for k in ["date_range", "tabs_viewed"]:
                    st.session_state.pop(k, None)
                st.rerun()

    region     = st.session_state["region"]
    region_cfg = REGION_CONFIG[region]

    st.header("Filters")

    region_data = df_all[df_all["AREA"] == region]
    if region_data.empty:
        st.error(f"No data found for {region}.")
        st.stop()

    min_date = region_data["REFERRAL_DATE"].min().date()
    max_date = region_data["REFERRAL_DATE"].max().date()

    today = pd.Timestamp.now().normalize().date()
    jan_start  = max(today.replace(month=1, day=1), min_date)
    q_month    = ((today.month - 1) // 3) * 3 + 1   # first month of current quarter
    qtd_start  = max(today.replace(month=q_month, day=1), min_date)

    # Default to Jan-to-date on first load (or after region switch clears the key)
    if "date_range" not in st.session_state:
        st.session_state["date_range"] = (jan_start, max_date)
    else:
        # If new data arrived with a later max_date, advance the stored end date automatically
        stored = st.session_state["date_range"]
        if len(stored) == 2 and stored[1] < max_date:
            st.session_state["date_range"] = (stored[0], max_date)

    # ── Quick preset buttons ──────────────────────────────────────────────────
    p1, p2 = st.columns(2)
    with p1:
        if st.button("2026 to Date", use_container_width=True, key="preset_jan"):
            st.session_state["date_range"] = (jan_start, max_date)
            st.rerun()
    with p2:
        if st.button("Quarter to Date", use_container_width=True, key="preset_qtd"):
            st.session_state["date_range"] = (qtd_start, max_date)
            st.rerun()

    # ── Date picker ──────────────────────────────────────────────────────────
    st.markdown(
        '<p style="font-size:13px;font-weight:500;margin:6px 0 2px;">or choose a date range</p>',
        unsafe_allow_html=True,
    )

    date_range = st.date_input(
        "date_range_hidden",
        min_value=min_date, max_value=max_date,
        key="date_range",
        label_visibility="collapsed",
    )

    # Keep full region data for retention (before date filter)
    df_region_full = df_all[df_all["AREA"] == region]

    if len(date_range) == 2:
        start, end = date_range
        df_all_filtered = df_all[
            (df_all["REFERRAL_DATE"].dt.date >= start) &
            (df_all["REFERRAL_DATE"].dt.date <= end)
        ]
    else:
        df_all_filtered = df_all

    df = df_all_filtered[df_all_filtered["AREA"] == region]

    st.divider()
    granularity = st.radio("Time granularity", ["Month", "Week"], horizontal=True, key="granularity")
    period_col = "month_of" if granularity == "Month" else "week_of"

    st.divider()
    st.caption(f"{len(df):,} {region_cfg['short']} referrals loaded")
    st.caption(f"Data as of {df['REFERRAL_DATE'].max().strftime('%b %d, %Y')}")

    # Full Excel export
    from components.excel_export import generate_full_export
    excel_bytes = generate_full_export(df, period_col)
    if excel_bytes:
        st.download_button(
            "Export Full Dashboard to Excel",
            excel_bytes,
            file_name=f"{region_cfg['short']}_Control_Tower_Export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="full_excel_export",
        )

    # Usage log viewer
    with st.expander("Usage Log"):
        from data.session_log import get_log
        log_data = get_log()
        if log_data:
            log_df = pd.DataFrame(log_data)
            log_df["timestamp"] = pd.to_datetime(log_df["timestamp"]).dt.strftime("%b %d %I:%M %p")
            st.dataframe(log_df.tail(50).iloc[::-1], use_container_width=True, hide_index=True)
        else:
            st.caption("No sessions recorded yet.")

# ── Banner ─────────────────────────────────────────────────────────────────────
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

# ── Tabs with tracking ─────────────────────────────────────────────────────────
tab1, tab2, tab5, tab_quota, tab6, tab7, tab_wip = st.tabs([
    "Market Health", "My Team",
    "Visit Prep", "Quota", "Raw Data", "How We Calculate",
    "Work in Progress",
])

if "tabs_viewed" not in st.session_state:
    st.session_state["tabs_viewed"] = set()

def _track_tab(tab_name):
    if tab_name not in st.session_state["tabs_viewed"]:
        st.session_state["tabs_viewed"].add(tab_name)
        log_event(user, "tab_view", f"{region}/{tab_name}")

with tab1:
    _track_tab("Market Health")
    by_account.render(df, period_col, df_all=df_all_filtered, df_ne_full=df_region_full, region=region)

with tab2:
    _track_tab("My Team")
    # Chase list only applies to NE region for now
    ppm_chase = chase_df if region == "Northeast" else None
    by_ppm.render(df, period_col, df_ne_full=df_region_full, chase_df=ppm_chase)

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
