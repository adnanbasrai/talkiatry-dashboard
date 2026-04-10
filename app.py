import streamlit as st
import pandas as pd
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from data.loader import load_referrals
from tabs import by_account, by_ppm, by_geo, conversion_deep_dive, faq

st.set_page_config(page_title="Talkiatry NE Market Assessment", layout="wide")

# Widen popover panels (the dialog that opens, not the trigger buttons)
st.markdown("""
<style>
div[data-testid="stPopoverBody"] {
    min-width: 700px;
    max-width: 800px;
}
</style>
""", unsafe_allow_html=True)

st.title("Talkiatry NE Market Assessment")

# --- Load data ---
df = load_referrals()

# --- Sidebar: global filters ---
with st.sidebar:
    st.header("Filters")

    # Date range
    min_date = df["REFERRAL_DATE"].min().date()
    max_date = df["REFERRAL_DATE"].max().date()
    # Default: last 3 full months
    default_start = (pd.Timestamp.now() - pd.DateOffset(months=3)).replace(day=1).date()
    if default_start < min_date:
        default_start = min_date

    date_range = st.date_input(
        "Date range",
        value=(default_start, max_date),
        min_value=min_date,
        max_value=max_date,
        key="date_range",
    )
    if len(date_range) == 2:
        start, end = date_range
        df = df[(df["REFERRAL_DATE"].dt.date >= start) & (df["REFERRAL_DATE"].dt.date <= end)]

    st.divider()

    # Time granularity
    granularity = st.radio("Time granularity", ["Month", "Week"], horizontal=True, key="granularity")
    period_col = "month_of" if granularity == "Month" else "week_of"

    # Entity focus
    entity_focus = st.radio("Entity focus", ["Clinics", "Providers"], horizontal=True, key="entity_focus")
    if entity_focus == "Clinics":
        entity_col = "REFERRING_CLINIC"
        entity_label = "Clinic"
    else:
        entity_col = "REFERRING_PHYSICIAN"
        entity_label = "Provider"

    st.divider()
    st.caption(f"{len(df):,} referrals loaded")
    st.caption(f"{df['REFERRAL_DATE'].min().strftime('%Y-%m-%d')} to {df['REFERRAL_DATE'].max().strftime('%Y-%m-%d')}")

# --- Tabs ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["By Account", "By PPM", "By Geography", "Conversion Deep Dive", "FAQs & Methodology"])

with tab1:
    by_account.render(df, period_col, entity_col, entity_label)

with tab2:
    by_ppm.render(df, period_col, entity_col, entity_label)

with tab3:
    by_geo.render(df, period_col, entity_col, entity_label)

with tab4:
    conversion_deep_dive.render(df, period_col, entity_col, entity_label)

with tab5:
    faq.render()
