import streamlit as st
import pandas as pd
from data.transforms import compute_metrics, last_complete_periods


def _enrich_provider_detail(agg_df, source_df, include_account):
    """Add physician name, NPI, and clinic to a provider aggregation."""
    # For each provider_id, get the first physician name, NPI, and clinic
    detail = (
        source_df.groupby("provider_id")
        .agg(
            physician=("REFERRING_PHYSICIAN", "first"),
            npi=("REFERRING_PROVIDER_NPI", "first"),
            clinic=("REFERRING_CLINIC", "first"),
        )
        .reset_index()
    )
    # Clean NPI
    detail["npi"] = detail["npi"].astype(str).str.replace(r"\.0$", "", regex=True).replace({"nan": "", "None": ""})

    merged = agg_df.merge(detail, on="provider_id", how="left")
    return merged


def _provider_change_detail(curr_df, prev_df, include_account=False):
    """Return (new_providers_df, lost_providers_df). Includes physician name, NPI, and clinic."""
    curr_provs = set(curr_df["provider_id"].dropna())
    prev_provs = set(prev_df["provider_id"].dropna())

    group_cols = ["provider_id", "PARTNER_ASSIGNMENT"] if include_account else ["provider_id"]

    # Lost: referred prior but not current
    lost_names = prev_provs - curr_provs
    lost_df = prev_df[prev_df["provider_id"].isin(lost_names)]
    if not lost_df.empty:
        lost = (
            lost_df.groupby(group_cols)
            .agg(prior_referrals=("REFERRAL_ID", "count"))
            .reset_index()
            .sort_values("prior_referrals", ascending=False)
        )
        lost = _enrich_provider_detail(lost, lost_df, include_account)
        col_order = ["physician", "npi", "clinic"]
        if include_account:
            col_order.append("PARTNER_ASSIGNMENT")
        col_order.append("prior_referrals")
        lost = lost[[c for c in col_order if c in lost.columns]]
        rename = {"physician": "Provider", "npi": "NPI", "clinic": "Clinic", "prior_referrals": "Prior Referrals"}
        if include_account:
            rename["PARTNER_ASSIGNMENT"] = "Account"
        lost = lost.rename(columns=rename)
    else:
        base = ["Provider", "NPI", "Clinic"]
        if include_account:
            base.append("Account")
        base.append("Prior Referrals")
        lost = pd.DataFrame(columns=base)

    # New: referred current but not prior
    new_names = curr_provs - prev_provs
    new_df = curr_df[curr_df["provider_id"].isin(new_names)]
    if not new_df.empty:
        new = (
            new_df.groupby(group_cols)
            .agg(referrals=("REFERRAL_ID", "count"))
            .reset_index()
            .sort_values("referrals", ascending=False)
        )
        new = _enrich_provider_detail(new, new_df, include_account)
        col_order = ["physician", "npi", "clinic"]
        if include_account:
            col_order.append("PARTNER_ASSIGNMENT")
        col_order.append("referrals")
        new = new[[c for c in col_order if c in new.columns]]
        rename = {"physician": "Provider", "npi": "NPI", "clinic": "Clinic", "referrals": "Referrals"}
        if include_account:
            rename["PARTNER_ASSIGNMENT"] = "Account"
        new = new.rename(columns=rename)
    else:
        base = ["Provider", "NPI", "Clinic"]
        if include_account:
            base.append("Account")
        base.append("Referrals")
        new = pd.DataFrame(columns=base)

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

    curr_period, prev_period, _ = last_complete_periods(periods, period_col)
    if curr_period is None:
        curr_period = periods[-1] if periods else None

    curr_df = df[df[period_col] == curr_period]
    prev_df = df[df[period_col] == prev_period] if prev_period is not None else None

    m = compute_metrics(curr_df)
    m_prev = compute_metrics(prev_df) if prev_df is not None and len(prev_df) > 0 else None

    # Format period names
    try:
        dt = pd.Timestamp(str(curr_period))
        if is_weekly:
            monday = dt - pd.Timedelta(days=dt.weekday())
            header = f"Week of {monday.strftime('%b %d, %Y')}"
        else:
            header = dt.strftime("%B %Y")
    except Exception:
        header = str(curr_period)

    if prev_period is not None:
        try:
            dt_prev = pd.Timestamp(str(prev_period))
            if is_weekly:
                prev_monday = dt_prev - pd.Timedelta(days=dt_prev.weekday())
                period_label = f"week of {prev_monday.strftime('%b %d')}"
            else:
                period_label = dt_prev.strftime("%b %Y")
        except Exception:
            period_label = str(prev_period)
    else:
        period_label = "prior period"

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

    # --- Terminated footnote (contextualises conversion rates) ---
    n_term = round(m.get("pct_terminated", 0) * m["referrals"])
    if n_term > 0:
        st.caption(
            f"ℹ️ **{n_term:,} terminated referral{'s' if n_term != 1 else ''}** "
            f"({m['pct_terminated']:.1%} of total) are included in conversion rates above — "
            f"screened out for clinical or insurance reasons."
        )

    # --- Drill-down popovers below the metrics ---
    if prev_df is not None and len(prev_df) > 0:
        drill_cols = st.columns(5)

        # Col 1: Provider change detail
        # "New" = referred in the last complete period but never in the entire date range before that
        with drill_cols[1]:
            include_acct = curr_df["PARTNER_ASSIGNMENT"].nunique() > 1
            all_prior_df = df[df[period_col] < curr_period]
            new_provs, lost_provs = _provider_change_detail(curr_df, all_prior_df, include_account=include_acct)

            with st.popover("View provider change detail", use_container_width=True):
                tab_new, tab_lost = st.tabs([
                    f"New Providers ({len(new_provs)})",
                    f"Lost Providers ({len(lost_provs)})",
                ])
                with tab_new:
                    st.caption(f"{len(new_provs)} providers who referred in {header} but never before in the selected date range")
                    if new_provs.empty:
                        st.info("No new providers.")
                    else:
                        st.dataframe(new_provs.reset_index(drop=True), use_container_width=True, hide_index=True, height=500)
                with tab_lost:
                    st.caption(f"{len(lost_provs)} providers who referred in {period_label} but not in {header}")
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
