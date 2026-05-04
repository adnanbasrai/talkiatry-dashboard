import streamlit as st
import pandas as pd
from components.kpi_row import render_kpi_row
from components.trend_chart import render_trend_chart
from components.entity_table import render_entity_table
from components.account_signals_table import render_account_callout, render_account_signals_table
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



@st.fragment
def render(df, period_col, df_all=None, df_ne_full=None, region="Northeast"):
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
        with st.expander(f"How does {region} compare to other regions?"):
            render_regional_comparison(df_all, period_col, active_region=region)

    # #5: Action plan when account(s) selected
    if selected:
        render_action_plan(filtered, period_col, df_full=df_ne_full)

    # KPIs
    render_kpi_row(filtered, period_col)

    # Trend charts
    if not selected or len(selected) > 1:
        render_trend_chart(filtered, period_col, group_col="PARTNER_ASSIGNMENT", key="acct")
    else:
        render_trend_chart(filtered, period_col, key="acct")

    # Account signals table — always visible; callout only when showing all accounts
    if not selected:
        render_account_callout(filtered, period_col)
        st.subheader("Account Rankings")
    else:
        st.subheader("Account Signals")
    render_account_signals_table(filtered, period_col)

    # #7: Inline entity toggle
    entity_focus = st.radio("View by", ["Clinics", "Providers"], horizontal=True, key="acct_entity_toggle")
    entity_col = "REFERRING_CLINIC" if entity_focus == "Clinics" else "REFERRING_PHYSICIAN"
    entity_label = "Clinic" if entity_focus == "Clinics" else "Provider"

    multi_acct = not selected or len(selected) > 1
    render_entity_table(filtered, entity_col, period_col, label=entity_label, include_account=multi_acct, title=f"{entity_label} Rankings")

    # Retention — uses full history by default
    partner = selected[0] if selected and len(selected) == 1 else None
    with st.expander("Provider Retention Cohorts", expanded=False):
        retention_data = df_ne_full if df_ne_full is not None else df
        render_retention_table(retention_data, df_filtered=df, partner_filter=partner)
