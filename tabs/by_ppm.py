import streamlit as st
from components.kpi_row import render_kpi_row
from components.trend_chart import render_trend_chart
from components.entity_table import render_entity_table
from components.account_signals_table import render_account_callout, render_account_signals_table
from components.retention_table import render_retention_table
from components.action_plan import render_action_plan
from components.pdf_export import generate_ppm_report


@st.fragment
def render(df, period_col, df_ne_full=None, chase_df=None):
    ppms = sorted(df["PPM"].unique().tolist())

    # PPM selector + PDF export on same line
    sel_col, pdf_col = st.columns([4, 1])
    with sel_col:
        selected_ppm = st.selectbox("PPM", ppms, index=None, placeholder="Select a PPM...", key="ppm_select")
    with pdf_col:
        if selected_ppm:
            pdf_bytes = generate_ppm_report(df, selected_ppm, period_col)
            if pdf_bytes:
                st.markdown("<br>", unsafe_allow_html=True)
                st.download_button(
                    "Export PDF Report", pdf_bytes,
                    file_name=f"{selected_ppm.replace(' ', '_')}_report.pdf",
                    mime="application/pdf", key="ppm_pdf_export",
                )

    if not selected_ppm:
        st.info("Select a PPM to view their dashboard.")
        return
    ppm_df = df[df["PPM"] == selected_ppm]

    # Filter chase list to this PPM (pass None if no chase data available)
    ppm_chase = None
    if chase_df is not None and not chase_df.empty:
        ppm_chase = chase_df[chase_df["ppm"] == selected_ppm]
        if ppm_chase.empty:
            ppm_chase = None

    render_action_plan(ppm_df, period_col, chase_df=ppm_chase, df_full=df_ne_full)
    render_kpi_row(ppm_df, period_col)

    render_account_callout(ppm_df, period_col)
    st.subheader("Account Portfolio")
    render_account_signals_table(ppm_df, period_col, toggle_key="ppm_signals_toggle", rank_df=df)

    render_trend_chart(ppm_df, period_col, group_col="PARTNER_ASSIGNMENT", key="ppm")

    acct_vol = ppm_df.groupby("PARTNER_ASSIGNMENT")["REFERRAL_ID"].count().sort_values(ascending=False)
    ppm_accounts = ["All"] + acct_vol.index.tolist()
    acct = st.selectbox("Drill into account", ppm_accounts, index=None, placeholder="All accounts — type to search...", key="ppm_acct_drill")
    drill_df = ppm_df if not acct or acct == "All" else ppm_df[ppm_df["PARTNER_ASSIGNMENT"] == acct]

    entity_focus = st.radio("View by", ["Clinics", "Providers"], horizontal=True, key="ppm_entity_toggle")
    entity_col = "REFERRING_CLINIC" if entity_focus == "Clinics" else "REFERRING_PHYSICIAN"
    entity_label = "Clinic" if entity_focus == "Clinics" else "Provider"

    ppm_multi_acct = (not acct or acct == "All") and ppm_df["PARTNER_ASSIGNMENT"].nunique() > 1
    render_entity_table(drill_df, entity_col, period_col, label=entity_label, include_account=ppm_multi_acct, title=f"{entity_label} Rankings")

    partner = acct if acct and acct != "All" else None
    with st.expander("Provider Retention Cohorts"):
        retention_data = df_ne_full if df_ne_full is not None else df
        render_retention_table(retention_data, df_filtered=ppm_df, partner_filter=partner)
