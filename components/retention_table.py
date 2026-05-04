import streamlit as st
import pandas as pd
from data.transforms import compute_retention


def render_retention_table(df_full, df_filtered=None, partner_filter=None):
    """Render the provider retention cohort grid.
    df_full: full history (for accurate first-referral calculation).
    df_filtered: date-filtered data (optional, for toggle to dashboard range).
    """
    st.subheader("Provider Retention by Cohort")

    # Toggle between full history and dashboard date range
    use_full = True
    if df_filtered is not None and len(df_filtered) != len(df_full):
        mode = st.radio(
            "Retention data range",
            ["Full history (recommended)", "Dashboard date range only"],
            horizontal=True,
            key=f"ret_mode_{partner_filter}",
        )
        use_full = mode == "Full history (recommended)"

    source = df_full if use_full else (df_filtered if df_filtered is not None else df_full)
    ret = compute_retention(source, partner_filter)

    if ret.empty:
        st.info("Not enough data for retention analysis.")
        return

    # Date range indicator
    if "REFERRAL_DATE" in source.columns and not source.empty:
        d_min = source["REFERRAL_DATE"].min()
        d_max = source["REFERRAL_DATE"].max()
        if pd.notna(d_min) and pd.notna(d_max):
            st.markdown(
                f'<span style="font-size:10px; color:#999;">Data range: {d_min.strftime("%b %d, %Y")} — {d_max.strftime("%b %d, %Y")}</span>',
                unsafe_allow_html=True,
            )

    if use_full:
        st.markdown(
            '<div style="background-color: #f5f7fa; padding: 6px 12px; border-radius: 5px; font-size: 12px; margin-bottom: 8px;">'
            'Using <b>full referral history</b> to determine each provider\'s first referral month. '
            'This ensures cohort sizes are accurate regardless of the dashboard date filter. '
            'Provider identity: coalesce(NPI, physician name).</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background-color: #fff3cd; padding: 6px 12px; border-radius: 5px; font-size: 12px; margin-bottom: 8px;">'
            'Using <b>dashboard date range only</b>. Cohort sizes may be inflated — '
            'providers whose first referral is before the date range will appear as "new" in the earliest visible month.</div>',
            unsafe_allow_html=True,
        )

    display = ret.copy()
    m_cols = [c for c in display.columns if c.startswith("M")]

    for col in m_cols:
        display[col] = display[col].apply(
            lambda v: f"{v:.1f}%" if pd.notna(v) and v != 0 else ("0.0%" if v == 0 else "")
        )
    if "M0" in display.columns:
        display["M0"] = display["M0"].replace("", "100.0%")

    def color_cell(val):
        if not isinstance(val, str) or val == "":
            return ""
        try:
            v = float(val.replace("%", ""))
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
