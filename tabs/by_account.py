import streamlit as st
import pandas as pd
from components.kpi_row import render_kpi_row
from components.trend_chart import render_trend_chart
from components.entity_table import render_entity_table
from components.retention_table import render_retention_table
from components.regional_comparison import render_regional_comparison
from components.action_plan import render_action_plan
from components.pdf_export import generate_account_report


def _get_sorted_accounts(df):
    last_month = sorted(df["month_of"].dropna().unique())
    if len(last_month) >= 2:
        target = last_month[-2]
    elif len(last_month) >= 1:
        target = last_month[-1]
    else:
        return df["PARTNER_ASSIGNMENT"].unique().tolist()
    counts = (
        df[df["month_of"] == target]
        .groupby("PARTNER_ASSIGNMENT")["REFERRAL_ID"]
        .count()
        .sort_values(ascending=False)
    )
    remaining = [a for a in df["PARTNER_ASSIGNMENT"].unique() if a not in counts.index]
    return counts.index.tolist() + sorted(remaining)


def _render_account_callout(df, period_col):
    """One-line summary of account-level action items below Account Rankings title."""
    from data.transforms import compute_entity_table
    table = compute_entity_table(df, "PARTNER_ASSIGNMENT", period_col)
    if table.empty:
        return

    parts = []

    # Accounts with high days silent (>7d) that have meaningful volume
    silent = table[(table["days_since_last"] >= 7) & (table["referrals"] >= 10)].sort_values("days_since_last", ascending=False)
    if not silent.empty:
        top_silent = silent.iloc[0]
        parts.append(f"<b>{top_silent['PARTNER_ASSIGNMENT']}</b> has been silent {int(top_silent['days_since_last'])}d")

    # Biggest grower
    growers = table[table["trend"].notna() & (table["trend"] > 0) & (table["referrals"] >= 10)].sort_values("trend", ascending=False)
    if not growers.empty:
        top_grower = growers.iloc[0]
        parts.append(f"<b>{top_grower['PARTNER_ASSIGNMENT']}</b> up {top_grower['trend']:+.0%}")

    # Biggest decliner
    decliners = table[table["trend"].notna() & (table["trend"] < -0.15) & (table["referrals"] >= 10)].sort_values("trend")
    if not decliners.empty:
        top_dec = decliners.iloc[0]
        parts.append(f"<b>{top_dec['PARTNER_ASSIGNMENT']}</b> down {top_dec['trend']:+.0%}")

    if parts:
        st.markdown(
            '<div style="background-color: #f5f7fa; padding: 8px 14px; border-radius: 6px; font-size: 13px;">'
            + " · ".join(parts) + "</div>",
            unsafe_allow_html=True,
        )


def render(df, period_col, df_all=None):
    sorted_accounts = _get_sorted_accounts(df)
    selected = st.multiselect(
        "Account(s)", options=sorted_accounts, default=None,
        placeholder="All Accounts — type to search...", key="acct_select",
    )
    filtered = df[df["PARTNER_ASSIGNMENT"].isin(selected)] if selected else df

    # PDF export when accounts selected
    if selected:
        pdf_bytes = generate_account_report(df, selected, period_col)
        if pdf_bytes:
            label = selected[0] if len(selected) == 1 else f"{len(selected)}_accounts"
            st.download_button(
                "Export Account Report as PDF", pdf_bytes,
                file_name=f"{label.replace(' ', '_')}_report.pdf",
                mime="application/pdf", key="acct_pdf_export",
            )

    # Regional comparison
    if df_all is not None and df_all["AREA"].nunique() > 1:
        with st.expander("How does Northeast compare to other regions?"):
            render_regional_comparison(df_all, period_col)

    # #5: Action plan when account(s) selected
    if selected:
        render_action_plan(filtered, period_col)

    # KPIs
    render_kpi_row(filtered, period_col)

    # Trend charts
    if not selected or len(selected) > 1:
        render_trend_chart(filtered, period_col, group_col="PARTNER_ASSIGNMENT")
    else:
        render_trend_chart(filtered, period_col)

    # #3: Show account table only when no specific account is selected
    if not selected:
        st.subheader("Account Rankings")
        _render_account_callout(filtered, period_col)
        render_entity_table(filtered, "PARTNER_ASSIGNMENT", period_col, label="Account")

    # #7: Inline entity toggle
    entity_focus = st.radio("View by", ["Clinics", "Providers"], horizontal=True, key="acct_entity_toggle")
    entity_col = "REFERRING_CLINIC" if entity_focus == "Clinics" else "REFERRING_PHYSICIAN"
    entity_label = "Clinic" if entity_focus == "Clinics" else "Provider"

    multi_acct = not selected or len(selected) > 1
    st.subheader(f"{entity_label} Rankings")
    render_entity_table(filtered, entity_col, period_col, label=entity_label, include_account=multi_acct)

    # Retention
    partner = selected[0] if selected and len(selected) == 1 else None
    with st.expander("Provider Retention Cohorts", expanded=False):
        render_retention_table(df, partner_filter=partner)
