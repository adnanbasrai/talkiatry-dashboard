import streamlit as st
import pandas as pd
from data.transforms import compute_retention


def render_retention_table(df, partner_filter=None):
    """Render the provider retention cohort grid."""
    ret = compute_retention(df, partner_filter)
    if ret.empty:
        st.info("Not enough data for retention analysis.")
        return

    st.subheader("Provider Retention by Cohort")
    st.caption("M0 = first referral month (100%), M1 = 1 month later, etc. Using REFERRING_PHYSICIAN as identity.")

    # Style: color cells by retention %
    display = ret.copy()
    m_cols = [c for c in display.columns if c.startswith("M")]

    def color_cell(val):
        if pd.isna(val) or val == "":
            return ""
        try:
            v = float(val)
        except (ValueError, TypeError):
            return ""
        if v >= 60:
            return "background-color: #d4edda"
        elif v >= 40:
            return "background-color: #fff3cd"
        elif v > 0:
            return "background-color: #f8d7da"
        return ""

    styled = display.style.applymap(color_cell, subset=m_cols)
    st.dataframe(styled, use_container_width=True, hide_index=True)
