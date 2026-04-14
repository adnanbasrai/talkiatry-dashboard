import streamlit as st
from components.kpi_row import render_kpi_row
from components.trend_chart import render_trend_chart
from components.entity_table import render_entity_table
from components.retention_table import render_retention_table
from components.action_plan import render_action_plan
from components.pdf_export import generate_ppm_report


def render(df, period_col):
    ppms = sorted(df["PPM"].unique().tolist())
    selected_ppm = st.selectbox("PPM", ppms, index=None, placeholder="Select a PPM...", key="ppm_select")
    if not selected_ppm:
        st.info("Select a PPM to view their dashboard.")
        return
    ppm_df = df[df["PPM"] == selected_ppm]

    # PDF export button
    pdf_bytes = generate_ppm_report(df, selected_ppm, period_col)
    if pdf_bytes:
        st.download_button(
            "Export PPM Report as PDF",
            pdf_bytes,
            file_name=f"{selected_ppm.replace(' ', '_')}_report.pdf",
            mime="application/pdf",
            key="ppm_pdf_export",
        )

    render_action_plan(ppm_df, period_col)
    render_kpi_row(ppm_df, period_col)

    st.subheader("Account Portfolio")
    render_entity_table(ppm_df, "PARTNER_ASSIGNMENT", period_col, label="Account")

    render_trend_chart(ppm_df, period_col, group_col="PARTNER_ASSIGNMENT")

    acct_vol = ppm_df.groupby("PARTNER_ASSIGNMENT")["REFERRAL_ID"].count().sort_values(ascending=False)
    ppm_accounts = ["All"] + acct_vol.index.tolist()
    acct = st.selectbox("Drill into account", ppm_accounts, index=None, placeholder="All accounts — type to search...", key="ppm_acct_drill")
    drill_df = ppm_df if not acct or acct == "All" else ppm_df[ppm_df["PARTNER_ASSIGNMENT"] == acct]

    # Inline entity toggle
    entity_focus = st.radio("View by", ["Clinics", "Providers"], horizontal=True, key="ppm_entity_toggle")
    entity_col = "REFERRING_CLINIC" if entity_focus == "Clinics" else "REFERRING_PHYSICIAN"
    entity_label = "Clinic" if entity_focus == "Clinics" else "Provider"

    ppm_multi_acct = acct == "All" and ppm_df["PARTNER_ASSIGNMENT"].nunique() > 1
    st.subheader(f"{entity_label} Rankings")
    render_entity_table(drill_df, entity_col, period_col, label=entity_label, include_account=ppm_multi_acct)

    partner = acct if acct != "All" else None
    with st.expander("Provider Retention Cohorts"):
        render_retention_table(ppm_df, partner_filter=partner)
