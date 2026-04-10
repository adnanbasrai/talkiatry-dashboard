import streamlit as st
from components.kpi_row import render_kpi_row
from components.trend_chart import render_trend_chart
from components.entity_table import render_entity_table
from components.category_sections import render_category_sections
from components.retention_table import render_retention_table


def render(df, period_col, entity_col, entity_label):
    ppms = sorted(df["PPM"].unique().tolist())
    selected_ppm = st.selectbox("PPM", ppms, key="ppm_select")

    ppm_df = df[df["PPM"] == selected_ppm]

    # KPIs — last complete period with delta
    render_kpi_row(ppm_df, period_col)

    # Account breakdown within PPM
    st.subheader("Account Portfolio")
    render_entity_table(ppm_df, "PARTNER_ASSIGNMENT", period_col, label="Account")

    # Trend
    render_trend_chart(ppm_df, period_col, group_col="PARTNER_ASSIGNMENT")

    # Drill into a specific account within this PPM
    acct_vol = ppm_df.groupby("PARTNER_ASSIGNMENT")["REFERRAL_ID"].count().sort_values(ascending=False)
    ppm_accounts = ["All"] + acct_vol.index.tolist()
    acct = st.selectbox("Drill into account", ppm_accounts, key="ppm_acct_drill")

    drill_df = ppm_df if acct == "All" else ppm_df[ppm_df["PARTNER_ASSIGNMENT"] == acct]

    ppm_multi_acct = acct == "All" and ppm_df["PARTNER_ASSIGNMENT"].nunique() > 1
    st.subheader(f"Top {entity_label}s")
    render_entity_table(drill_df, entity_col, period_col, label=entity_label, include_account=ppm_multi_acct)

    st.subheader(f"{entity_label} Categories")
    render_category_sections(drill_df, entity_col, period_col, label=entity_label, key_prefix="ppm", include_account=ppm_multi_acct)

    # Retention scoped to PPM's portfolio
    partner = acct if acct != "All" else None
    render_retention_table(ppm_df, partner_filter=partner)
