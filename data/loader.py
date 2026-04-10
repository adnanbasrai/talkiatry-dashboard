import pandas as pd
import streamlit as st
from config import DATA_PATH


@st.cache_data
def load_referrals() -> pd.DataFrame:
    """Load and clean the consolidated referral CSV."""
    df = pd.read_csv(DATA_PATH, low_memory=False)

    # --- Rename duplicate columns (pandas auto-appends .1) ---
    # Keep the second copy of IS_INTAKE_COMPLETED and INTAKE_ACTION_STATUS
    # since they align with the termination/appointment block
    df = df.rename(columns={
        "IS_INTAKE_COMPLETED.1": "_IS_INTAKE_COMPLETED_2",
        "INTAKE_ACTION_STATUS.1": "_INTAKE_ACTION_STATUS_2",
        "APPOINTMENT_SOURCE_FIRST_SCHEDULED.1": "_APPT_SOURCE_2",
        "PARTNER_ASSIGNMENT.1": "_PARTNER_ASSIGNMENT_2",
        "AREA.1": "_AREA_2",
        "PATIENT_INSURANCE_NAME.1": "_PATIENT_INSURANCE_2",
    })

    # --- Track contact info presence BEFORE dropping PII ---
    df["has_email"] = df["PATIENT_EMAIL"].notna() & (df["PATIENT_EMAIL"].astype(str).str.strip() != "")
    df["has_phone"] = df["PATIENT_PHONE_NUMBER"].notna() & (df["PATIENT_PHONE_NUMBER"].astype(str).str.strip() != "")

    # --- Drop PII ---
    pii_cols = [
        "PATIENT_NAME_FIRST", "PATIENT_NAME_LAST", "PATIENT_EMAIL",
        "PATIENT_PHONE_NUMBER", "PATIENT_AGE", "REASON_FOR_REFERRAL",
    ]
    df = df.drop(columns=[c for c in pii_cols if c in df.columns], errors="ignore")

    # --- Parse dates ---
    for col in ["REFERRAL_DATE", "INTAKE_START_DATE",
                 "APPOINTMENT_DATE_BOOKED_FIRST_SCHEDULED",
                 "APPOINTMENT_DATE_BOOKED_FIRST_COMPLETED"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # --- Clean zip codes to 5 digits, coalesce clinic zip → patient zip ---
    def _clean_zip(series):
        return (
            series.astype(str)
            .str.split("-").str[0]
            .str.strip()
            .str.zfill(5)
            .replace({"00nan": None, "0nan0": None, "00000": None, "0None": None})
        )

    clinic_zip = _clean_zip(df["REFERRING_CLINIC_ZIP"])
    patient_zip = _clean_zip(df["PATIENT_POSTAL_CODE"]) if "PATIENT_POSTAL_CODE" in df.columns else clinic_zip
    df["REFERRING_CLINIC_ZIP"] = clinic_zip.where(clinic_zip.notna() & (clinic_zip.str.len() == 5), patient_zip)

    # --- Derive time periods ---
    df["month_of"] = df["REFERRAL_DATE"].dt.to_period("M")
    # Week starts on Monday
    df["week_of"] = df["REFERRAL_DATE"].apply(lambda d: d - pd.Timedelta(days=d.weekday()) if pd.notna(d) else pd.NaT)

    # --- Derive conversion booleans (validated logic) ---
    df["intake_started"] = (
        df["INTAKE_START_DATE"].notna()
        | df["APPOINTMENT_ID_FIRST_SCHEDULED"].notna()
        | df["APPOINTMENT_DATE_BOOKED_FIRST_SCHEDULED"].notna()
    ).astype(int)

    df["visit_booked"] = df["APPOINTMENT_ID_FIRST_SCHEDULED"].notna().astype(int)
    df["visit_completed"] = df["APPOINTMENT_ID_FIRST_COMPLETED"].notna().astype(int)

    # --- Derive root cause fields for conversion deep dive ---
    # Stage 1: why didn't intake start?
    df["outreach_status"] = "No outreach data"
    df.loc[df["IS_OUTREACH_CAMPAIGN_COMPLETED"] == 0, "outreach_status"] = "Outreach in progress"
    df.loc[df["IS_OUTREACH_CAMPAIGN_COMPLETED"] == 1, "outreach_status"] = "Outreach completed"

    # Stage 2: why didn't they book?
    df["termination_category"] = "Other"
    tr = df["TERMINATION_REASON"].fillna("")
    df.loc[tr.str.contains("OON|OutOfNetwork|InsurancePlan", case=False, na=False), "termination_category"] = "Insurance OON"
    df.loc[tr.str.contains("Inpatient", case=False, na=False), "termination_category"] = "Recently Inpatient"
    df.loc[tr.str.contains("Schizo", case=False, na=False), "termination_category"] = "Clinical Exclusion"
    df.loc[tr.str.contains("Emergency", case=False, na=False), "termination_category"] = "Emergency"
    df.loc[tr.str.contains("Minor", case=False, na=False), "termination_category"] = "Minor"
    df.loc[tr.str.contains("StateNotCovered", case=False, na=False), "termination_category"] = "State Not Covered"
    df.loc[tr.str.contains("not interested|no longer interested", case=False, na=False), "termination_category"] = "Patient Declined"
    df.loc[tr == "", "termination_category"] = "None"

    # --- Drop internal/fivetran columns ---
    drop_cols = ["_LINE", "_FIVETRAN_SYNCED", "_PARTNER_ASSIGNMENT_2",
                 "_AREA_2", "_IS_INTAKE_COMPLETED_2", "_INTAKE_ACTION_STATUS_2",
                 "_APPT_SOURCE_2", "_PATIENT_INSURANCE_2", "PATIENT_POSTAL_CODE"]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore")

    return df
