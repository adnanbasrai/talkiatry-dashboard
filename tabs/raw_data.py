import streamlit as st
import pandas as pd


def render(df, period_col):
    st.subheader("Raw Data Explorer")

    # Quick filters in columns
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        accounts = sorted(df["PARTNER_ASSIGNMENT"].unique().tolist())
        acct = st.selectbox("Account", accounts, index=None, placeholder="All — type to search...", key="raw_acct")
    with col2:
        ppms = sorted(df["PPM"].unique().tolist())
        ppm = st.selectbox("PPM", ppms, index=None, placeholder="All — type to search...", key="raw_ppm")
    with col3:
        clinics = sorted(df["REFERRING_CLINIC"].dropna().unique().tolist())
        clinic = st.selectbox("Clinic", clinics, index=None, placeholder="All — type to search...", key="raw_clinic")
    with col4:
        providers = sorted(df["provider_id"].dropna().unique().tolist())
        provider = st.selectbox("Provider", providers, index=None, placeholder="All — type to search...", key="raw_provider")

    filtered = df.copy()
    if acct:
        filtered = filtered[filtered["PARTNER_ASSIGNMENT"] == acct]
    if ppm:
        filtered = filtered[filtered["PPM"] == ppm]
    if clinic:
        filtered = filtered[filtered["REFERRING_CLINIC"] == clinic]
    if provider:
        filtered = filtered[filtered["provider_id"] == provider]

    # Display columns (exclude internal/derived, keep useful ones)
    display_cols = [
        "REFERRAL_DATE", "REFERRAL_ID", "PARTNER_ASSIGNMENT", "PPM",
        "REFERRING_CLINIC", "REFERRING_CLINIC_ZIP", "provider_id",
        "REFERRING_PHYSICIAN", "REFERRAL_SOURCE_TYPE",
        "PATIENT_INSURANCE_NAME", "intake_started", "visit_booked", "visit_completed",
        "INTAKE_ACTION_STATUS", "TERMINATION_REASON",
        "APPOINTMENT_SOURCE_FIRST_SCHEDULED", "TEAM_TYPE",
    ]
    display_cols = [c for c in display_cols if c in filtered.columns]

    st.caption(f"{len(filtered):,} rows")
    st.dataframe(
        filtered[display_cols].sort_values("REFERRAL_DATE", ascending=False).reset_index(drop=True),
        use_container_width=True, hide_index=True, height=600,
    )

    csv = filtered[display_cols].to_csv(index=False)
    st.download_button("Export filtered data as CSV", csv, "filtered_data.csv", "text/csv", key="raw_export")
