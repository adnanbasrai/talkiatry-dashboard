import os
import pandas as pd
import streamlit as st
from config import DATA_PATH


def _load_from_gsheets():
    """Load data from Google Sheets using service account credentials."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        from config import GSHEET_URL

        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_url(GSHEET_URL)
        data = sh.sheet1.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.warning(f"Could not load from Google Sheets: {e}")
        return None


def _csv_mtime() -> float:
    """Return file modification time so cache busts automatically when the CSV changes."""
    try:
        return os.path.getmtime(DATA_PATH)
    except OSError:
        return 0.0


@st.cache_data(ttl=3600)
def load_referrals(_mtime: float = 0.0) -> pd.DataFrame:
    """Load referral data. Uses local CSV if available, falls back to Google Sheets."""
    if os.path.exists(DATA_PATH):
        df = pd.read_csv(DATA_PATH, low_memory=False)
    else:
        df = _load_from_gsheets()
        if df is None:
            st.error("No data source available. Place the CSV in Downloads or configure Google Sheets.")
            return pd.DataFrame()

    # --- Rename duplicate columns (handle both .1 and _1 suffixes) ---
    rename_map = {}
    for old, new in [
        ("IS_INTAKE_COMPLETED.1", "_IS_INTAKE_COMPLETED_2"),
        ("IS_INTAKE_COMPLETED_1", "_IS_INTAKE_COMPLETED_2"),
        ("INTAKE_ACTION_STATUS.1", "_INTAKE_ACTION_STATUS_2"),
        ("INTAKE_ACTION_STATUS_1", "_INTAKE_ACTION_STATUS_2"),
        ("APPOINTMENT_SOURCE_FIRST_SCHEDULED.1", "_APPT_SOURCE_2"),
        ("APPOINTMENT_SOURCE_FIRST_SCHEDULED_1", "_APPT_SOURCE_2"),
        ("PARTNER_ASSIGNMENT.1", "_PARTNER_ASSIGNMENT_2"),
        ("PARTNER_ASSIGNMENT_1", "_PARTNER_ASSIGNMENT_2"),
        ("AREA.1", "_AREA_2"),
        ("AREA_1", "_AREA_2"),
        ("PATIENT_INSURANCE_NAME.1", "_PATIENT_INSURANCE_2"),
        ("PATIENT_INSURANCE_NAME_1", "_PATIENT_INSURANCE_2"),
        ("REFERRAL_ID.1", "_REFERRAL_ID_2"),
    ]:
        if old in df.columns:
            rename_map[old] = new
    df = df.rename(columns=rename_map)

    # --- Track contact info presence BEFORE dropping PII ---
    df["has_email"] = df["PATIENT_EMAIL"].notna() & (df["PATIENT_EMAIL"].astype(str).str.strip() != "")
    df["has_phone"] = df["PATIENT_PHONE_NUMBER"].notna() & (df["PATIENT_PHONE_NUMBER"].astype(str).str.strip() != "")

    # --- Provider identity: use pre-coalesced REFERRING_PROVIDER (NPI first, physician fallback) ---
    if "REFERRING_PROVIDER" in df.columns:
        df["provider_id"] = (
            df["REFERRING_PROVIDER"].astype(str).str.strip()
            .str.replace(r"\.0$", "", regex=True)
            .replace({"nan": None, "None": None, "": None, "0": None})
        )
    else:
        # Fallback: manual coalesce if REFERRING_PROVIDER column missing
        npi = df["REFERRING_PROVIDER_NPI"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).replace({"nan": "", "None": "", "0": ""})
        physician = df["REFERRING_PHYSICIAN"].astype(str).str.strip().replace({"nan": "", "None": ""})
        df["provider_id"] = npi.where(npi != "", physician)
        df.loc[df["provider_id"] == "", "provider_id"] = None

    # --- Build patient display name (for visit prep only) ---
    if "PATIENT_NAME_FIRST" in df.columns and "PATIENT_NAME_LAST" in df.columns:
        df["patient_name"] = (
            df["PATIENT_NAME_FIRST"].fillna("").astype(str).str.strip()
            + " "
            + df["PATIENT_NAME_LAST"].fillna("").astype(str).str.strip()
        ).str.strip()
        df.loc[df["patient_name"] == "", "patient_name"] = None

    # --- Parse patient DOB ---
    if "PATIENT_DOB" in df.columns:
        df["PATIENT_DOB"] = pd.to_datetime(df["PATIENT_DOB"], errors="coerce")

    # --- Drop raw PII columns (keep derived patient_name and PATIENT_DOB) ---
    pii_cols = [
        "PATIENT_NAME_FIRST", "PATIENT_NAME_LAST", "PATIENT_EMAIL",
        "PATIENT_PHONE_NUMBER", "REASON_FOR_REFERRAL",
    ]
    df = df.drop(columns=[c for c in pii_cols if c in df.columns], errors="ignore")

    # --- Parse dates ---
    for col in ["REFERRAL_DATE", "INTAKE_START_DATE",
                 "APPOINTMENT_DATE_BOOKED_FIRST_SCHEDULED",
                 "APPOINTMENT_DATE_BOOKED_FIRST_COMPLETED"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # --- Filter out future-dated referrals ---
    today = pd.Timestamp.now().normalize()
    df = df[df["REFERRAL_DATE"] <= today]

    # --- Clean zip codes to 5 digits, coalesce clinic zip -> patient zip ---
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

    # --- Derive conversion booleans (Omni-aligned methodology) ---

    # Intake Started: session patient exists OR psychiatry appointment scheduled
    df["intake_started"] = (
        df["SESSION_PATIENT_ID"].notna()
        | df["PSYCHIATRY_APPOINTMENT_ID_FIRST_SCHEDULED"].notna()
    ).astype(int)

    # Intake Completed: intake marked as successfully completed
    df["intake_completed"] = (df["IS_INTAKE_COMPLETED"] == 1).astype(int) \
        if "IS_INTAKE_COMPLETED" in df.columns else 0

    # First Visit Booked: psychiatry appointment scheduled
    df["visit_booked"] = df["PSYCHIATRY_APPOINTMENT_ID_FIRST_SCHEDULED"].notna().astype(int)

    # First Visit Completed: attended first appointment
    # Non-Kaiser: ARR, CHK, No Show, LATE CANC all count as completed
    # Kaiser: only ARR, CHK count
    _status = df["PSYCHIATRY_APPOINTMENT_STATUS_FIRST_SCHEDULED_NON_CANCELED"].fillna("") \
        if "PSYCHIATRY_APPOINTMENT_STATUS_FIRST_SCHEDULED_NON_CANCELED" in df.columns \
        else pd.Series("", index=df.index)
    _is_kaiser = df["PARTNER_ASSIGNMENT"].str.contains("Kaiser", case=False, na=False)
    _non_kaiser_done = _status.isin(["ARR", "CHK", "No Show", "LATE CANC"])
    _kaiser_done     = _status.isin(["ARR", "CHK"])
    df["visit_completed"] = ((~_is_kaiser & _non_kaiser_done) | (_is_kaiser & _kaiser_done)).astype(int)

    # --- Derive root cause fields for conversion deep dive ---
    df["outreach_status"] = "No outreach data"
    df.loc[df["IS_OUTREACH_CAMPAIGN_COMPLETED"] == 0, "outreach_status"] = "Outreach in progress"
    df.loc[df["IS_OUTREACH_CAMPAIGN_COMPLETED"] == 1, "outreach_status"] = "Outreach completed"

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
