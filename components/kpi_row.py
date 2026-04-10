import streamlit as st
import pandas as pd
from data.transforms import compute_metrics


def _provider_change_detail(curr_df, prev_df, include_account=False):
    """Return (new_providers_df, lost_providers_df). Includes Account column when multi-account."""
    def _valid_provs(d):
        s = d["REFERRING_PHYSICIAN"].dropna()
        return set(s[s.str.strip() != ""])

    curr_provs = _valid_provs(curr_df)
    prev_provs = _valid_provs(prev_df)

    group_cols = ["REFERRING_PHYSICIAN", "PARTNER_ASSIGNMENT"] if include_account else ["REFERRING_PHYSICIAN"]

    # Lost: referred prior but not current
    lost_names = prev_provs - curr_provs
    lost_df = prev_df[prev_df["REFERRING_PHYSICIAN"].isin(lost_names)]
    if not lost_df.empty:
        lost = (
            lost_df.groupby(group_cols)
            .agg(prior_referrals=("REFERRAL_ID", "count"))
            .reset_index()
            .sort_values("prior_referrals", ascending=False)
        )
        rename = {"REFERRING_PHYSICIAN": "Provider", "prior_referrals": "Prior Referrals"}
        if include_account:
            rename["PARTNER_ASSIGNMENT"] = "Account"
        lost = lost.rename(columns=rename)
    else:
        cols = ["Provider", "Account", "Prior Referrals"] if include_account else ["Provider", "Prior Referrals"]
        lost = pd.DataFrame(columns=cols)

    # New: referred current but not prior
    new_names = curr_provs - prev_provs
    new_df = curr_df[curr_df["REFERRING_PHYSICIAN"].isin(new_names)]
    if not new_df.empty:
        new = (
            new_df.groupby(group_cols)
            .agg(referrals=("REFERRAL_ID", "count"))
            .reset_index()
            .sort_values("referrals", ascending=False)
        )
        rename = {"REFERRING_PHYSICIAN": "Provider", "referrals": "Referrals"}
        if include_account:
            rename["PARTNER_ASSIGNMENT"] = "Account"
        new = new.rename(columns=rename)
    else:
        cols = ["Provider", "Account", "Referrals"] if include_account else ["Provider", "Referrals"]
        new = pd.DataFrame(columns=cols)

    return new, lost


def _conversion_drivers(curr_df, prev_df, metric_col, metric_label):
    """Accounts that drove the biggest change in a conversion metric."""
    def _by_account(d):
        return d.groupby("PARTNER_ASSIGNMENT").agg(
            referrals=("REFERRAL_ID", "count"),
            metric_sum=(metric_col, "sum"),
        ).reset_index()

    curr_acct = _by_account(curr_df)
    prev_acct = _by_account(prev_df)

    merged = curr_acct.merge(prev_acct, on="PARTNER_ASSIGNMENT", how="outer", suffixes=("_curr", "_prev")).fillna(0)
    merged["pct_curr"] = merged["metric_sum_curr"] / merged["referrals_curr"].replace(0, 1)
    merged["pct_prev"] = merged["metric_sum_prev"] / merged["referrals_prev"].replace(0, 1)
    merged["change"] = merged["pct_curr"] - merged["pct_prev"]
    merged["impact"] = merged["change"].abs() * (merged["referrals_curr"] + merged["referrals_prev"])
    merged = merged.sort_values("impact", ascending=False).head(10)

    display = merged[["PARTNER_ASSIGNMENT", "referrals_curr", "pct_curr", "pct_prev", "change"]].copy()
    display["pct_curr"] = (display["pct_curr"] * 100).round(1).astype(str) + "%"
    display["pct_prev"] = (display["pct_prev"] * 100).round(1).astype(str) + "%"
    display["change"] = display["change"].apply(lambda x: f"{x:+.1%}")
    display = display.rename(columns={
        "PARTNER_ASSIGNMENT": "Account",
        "referrals_curr": "Referrals",
        "pct_curr": f"{metric_label} (Current)",
        "pct_prev": f"{metric_label} (Prior)",
        "change": "Change",
    })
    return display


def render_kpi_row(df, period_col):
    """Render KPI cards for the last complete period with delta vs prior period."""
    periods = sorted(df[period_col].dropna().unique())

    if len(periods) < 1:
        st.info("No data for this selection.")
        return

    is_weekly = period_col == "week_of"
    period_label = "last week" if is_weekly else "last month"

    if len(periods) >= 2:
        curr_period = periods[-2]
        prev_period = periods[-3] if len(periods) >= 3 else None
    else:
        curr_period = periods[-1]
        prev_period = None

    curr_df = df[df[period_col] == curr_period]
    prev_df = df[df[period_col] == prev_period] if prev_period is not None else None

    m = compute_metrics(curr_df)
    m_prev = compute_metrics(prev_df) if prev_df is not None and len(prev_df) > 0 else None

    # Format period header
    try:
        dt = pd.Timestamp(str(curr_period))
        if is_weekly:
            monday = dt - pd.Timedelta(days=dt.weekday())
            header = f"Week of {monday.strftime('%b %d, %Y')}"
        else:
            header = dt.strftime("%B %Y")
    except Exception:
        header = str(curr_period)
    st.caption(header)

    cols = st.columns(5)
    labels = [
        ("Referrals", "referrals", False),
        ("Unique Providers", "unique_providers", False),
        ("% Intake Started", "pct_intake", True),
        ("% Visit Booked", "pct_booked", True),
        ("% Visit Completed", "pct_completed", True),
    ]
    for col, (label, key, is_pct) in zip(cols, labels):
        val = m[key]
        delta = None
        if m_prev and m_prev["referrals"] > 0:
            delta_raw = val - m_prev[key]
            if is_pct:
                delta = f"{delta_raw:+.1%} vs {period_label}"
            else:
                delta = f"{delta_raw:+,.0f} vs {period_label}"
        display = f"{val:.1%}" if is_pct else f"{val:,.0f}"
        col.metric(label, display, delta)

    # --- Drill-down popovers below the metrics ---
    if prev_df is not None and len(prev_df) > 0:
        drill_cols = st.columns(5)

        # Col 1: Provider change detail
        with drill_cols[1]:
            include_acct = curr_df["PARTNER_ASSIGNMENT"].nunique() > 1
            new_provs, lost_provs = _provider_change_detail(curr_df, prev_df, include_account=include_acct)

            with st.popover("View provider change detail", use_container_width=True):
                tab_new, tab_lost = st.tabs([
                    f"New Providers ({len(new_provs)})",
                    f"Lost Providers ({len(lost_provs)})",
                ])
                with tab_new:
                    st.caption(f"{len(new_provs)} providers referring this period who did not refer {period_label}")
                    if new_provs.empty:
                        st.info("No new providers.")
                    else:
                        st.dataframe(new_provs.reset_index(drop=True), use_container_width=True, hide_index=True, height=500)
                with tab_lost:
                    st.caption(f"{len(lost_provs)} providers who referred {period_label} but not this period")
                    if lost_provs.empty:
                        st.info("No lost providers.")
                    else:
                        st.dataframe(lost_provs.reset_index(drop=True), use_container_width=True, hide_index=True, height=500)

        # Col 2: Intake drivers
        with drill_cols[2]:
            drivers = _conversion_drivers(curr_df, prev_df, "intake_started", "% Intake")
            if not drivers.empty:
                with st.popover("View intake drivers by account", use_container_width=True):
                    st.caption(f"Accounts with biggest intake rate change vs {period_label}")
                    st.dataframe(drivers.reset_index(drop=True), use_container_width=True, hide_index=True, height=400)

        # Col 3: Booking drivers
        with drill_cols[3]:
            drivers = _conversion_drivers(curr_df, prev_df, "visit_booked", "% Booked")
            if not drivers.empty:
                with st.popover("View booking drivers by account", use_container_width=True):
                    st.caption(f"Accounts with biggest booking rate change vs {period_label}")
                    st.dataframe(drivers.reset_index(drop=True), use_container_width=True, hide_index=True, height=400)

        # Col 4: Completion drivers
        with drill_cols[4]:
            drivers = _conversion_drivers(curr_df, prev_df, "visit_completed", "% Completed")
            if not drivers.empty:
                with st.popover("View completion drivers by account", use_container_width=True):
                    st.caption(f"Accounts with biggest completion rate change vs {period_label}")
                    st.dataframe(drivers.reset_index(drop=True), use_container_width=True, hide_index=True, height=400)
