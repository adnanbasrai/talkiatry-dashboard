import streamlit as st
import pandas as pd
from components.kpi_row import render_kpi_row
from components.trend_chart import render_trend_chart
from components.entity_table import render_entity_table
from components.category_sections import render_category_sections
from components.retention_table import render_retention_table


def _get_sorted_accounts(df):
    """Return accounts sorted by last full month referrals descending."""
    last_month = df["month_of"].dropna().unique()
    last_month = sorted(last_month)
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
    all_accounts = df["PARTNER_ASSIGNMENT"].unique()
    remaining = [a for a in all_accounts if a not in counts.index]
    return counts.index.tolist() + sorted(remaining)


def render(df, period_col, entity_col, entity_label):
    sorted_accounts = _get_sorted_accounts(df)

    selected = st.multiselect(
        "Account(s)",
        options=sorted_accounts,
        default=None,
        placeholder="All Accounts — type to search...",
        key="acct_select",
    )

    if selected:
        filtered = df[df["PARTNER_ASSIGNMENT"].isin(selected)]
    else:
        filtered = df

    # KPIs — last complete period with delta
    render_kpi_row(filtered, period_col)

    # Trend charts
    if not selected or len(selected) > 1:
        render_trend_chart(filtered, period_col, group_col="PARTNER_ASSIGNMENT")
    else:
        render_trend_chart(filtered, period_col)

    # Account ranking table
    st.subheader("Account Rankings")
    render_entity_table(filtered, "PARTNER_ASSIGNMENT", period_col, label="Account")

    # Entity table and categories (always shown)
    # Show account column when not filtered to a single account
    multi_acct = not selected or len(selected) > 1
    st.subheader(f"Top {entity_label}s")
    render_entity_table(filtered, entity_col, period_col, label=entity_label, include_account=multi_acct)

    st.subheader(f"{entity_label} Categories")
    render_category_sections(filtered, entity_col, period_col, label=entity_label, key_prefix="acct", include_account=multi_acct)

    # Retention (only when single account selected)
    if selected and len(selected) == 1:
        render_retention_table(df, partner_filter=selected[0])
