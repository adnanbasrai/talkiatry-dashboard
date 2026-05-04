import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np
from data.transforms import _count_weekdays, count_unique_providers


def render_regional_comparison(df_all, period_col, active_region="Northeast"):
    """Render a compact regional comparison: size-normalized metrics across regions."""
    regions = sorted(df_all["AREA"].dropna().unique())
    if len(regions) < 2:
        st.info("Only one region in data — nothing to compare.")
        return

    is_weekly = period_col == "week_of"
    periods = sorted(df_all[period_col].dropna().unique())
    if len(periods) < 2:
        return

    # Use last complete period
    curr_period = periods[-2]
    prev_period = periods[-3] if len(periods) >= 3 else None

    curr = df_all[df_all[period_col] == curr_period]
    prev = df_all[df_all[period_col] == prev_period] if prev_period is not None else None

    # Working days in the period (for referrals per working day)
    if period_col == "month_of":
        p_start = pd.Period(curr_period, freq="M").start_time
        p_end = pd.Period(curr_period, freq="M").end_time + pd.Timedelta(days=1)
    else:
        p_start = pd.Timestamp(curr_period)
        p_end = p_start + pd.Timedelta(days=5)
    working_days = _count_weekdays(p_start, p_end)

    # Format period label
    try:
        dt = pd.Timestamp(str(curr_period))
        period_name = dt.strftime("%b %Y") if not is_weekly else f"Week of {(dt - pd.Timedelta(days=dt.weekday())).strftime('%b %d')}"
    except Exception:
        period_name = str(curr_period)

    if "REFERRAL_DATE" in df_all.columns and not df_all.empty:
        d_min = df_all["REFERRAL_DATE"].min()
        d_max = df_all["REFERRAL_DATE"].max()
        if pd.notna(d_min) and pd.notna(d_max):
            st.markdown(
                f'<span style="font-size:10px; color:#999;">Data range: {d_min.strftime("%b %d, %Y")} — {d_max.strftime("%b %d, %Y")}</span>',
                unsafe_allow_html=True,
            )

    # Compute per-region metrics
    rows = []
    for region in regions:
        rc = curr[curr["AREA"] == region]
        refs = len(rc)
        providers = count_unique_providers(rc["provider_id"])
        clinics = rc["REFERRING_CLINIC"].nunique()
        refs_per_day = round(refs / working_days, 1) if working_days > 0 else 0
        pct_intake = rc["intake_started"].sum() / refs if refs > 0 else 0
        pct_booked = rc["visit_booked"].sum() / refs if refs > 0 else 0

        # New providers this period (not in any prior period for this region)
        all_prior = df_all[(df_all["AREA"] == region) & (df_all[period_col] < curr_period)]
        prior_provs = set(all_prior["provider_id"].dropna())
        curr_provs = set(rc["provider_id"].dropna())
        new_providers = len(curr_provs - prior_provs)

        # New clinics this period
        prior_clinics = set(all_prior["REFERRING_CLINIC"].dropna())
        curr_clinics = set(rc["REFERRING_CLINIC"].dropna())
        new_clinics = len(curr_clinics - prior_clinics)

        rows.append({
            "Region": region,
            "Referrals/Day": refs_per_day,
            "New Providers": new_providers,
            "New Clinics": new_clinics,
            "% Intake": pct_intake,
            "% Booked": pct_booked,
        })

    table = pd.DataFrame(rows)

    # Highlight active region row
    def highlight_ne(row):
        if row["Region"] == active_region:
            return ["font-weight: bold; background-color: #e8f4fd"] * len(row)
        return [""] * len(row)

    display = table.copy()
    display["Referrals/Day"] = display["Referrals/Day"].apply(lambda x: f"{x:.1f}")
    display["% Intake"] = (display["% Intake"] * 100).round(1).astype(str) + "%"
    display["% Booked"] = (display["% Booked"] * 100).round(1).astype(str) + "%"

    st.caption(f"Regional comparison — {period_name} ({working_days} working days)")
    st.dataframe(
        display.style.apply(highlight_ne, axis=1),
        use_container_width=True, hide_index=True,
    )

    # Small bar charts side by side
    col1, col2, col3 = st.columns(3)

    bar_colors = ["#4A90D9" if r == active_region else "#B0C4DE" for r in table["Region"]]

    with col1:
        fig = go.Figure(go.Bar(
            x=table["Region"], y=table["Referrals/Day"],
            marker_color=bar_colors,
            text=[f"{v:.1f}" for v in table["Referrals/Day"]], textposition="auto",
            textfont=dict(size=11, color="white"),
        ))
        fig.update_layout(title="Referrals per Working Day", height=250, margin=dict(t=40, b=20), showlegend=False, yaxis_title="")
        st.plotly_chart(fig, use_container_width=True, key="rc_refs_day")

    with col2:
        fig = go.Figure(go.Bar(
            x=table["Region"], y=table["New Providers"],
            marker_color=bar_colors,
            text=table["New Providers"], textposition="auto",
            textfont=dict(size=14, color="white"),
        ))
        fig.update_layout(title="New Providers", height=250, margin=dict(t=40, b=20), showlegend=False, yaxis_title="")
        st.plotly_chart(fig, use_container_width=True, key="rc_new_provs")

    with col3:
        fig = go.Figure(go.Bar(
            x=table["Region"], y=table["New Clinics"],
            marker_color=bar_colors,
            text=table["New Clinics"], textposition="auto",
            textfont=dict(size=14, color="white"),
        ))
        fig.update_layout(title="New Clinics", height=250, margin=dict(t=40, b=20), showlegend=False, yaxis_title="")
        st.plotly_chart(fig, use_container_width=True, key="rc_new_clinics")
