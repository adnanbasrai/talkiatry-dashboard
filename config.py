import os

# Data source
DATA_PATH = os.path.expanduser("~/Downloads/NE Control Tower Query_2026-04-14-1721.csv")

# PII columns to drop on load
PII_COLUMNS = [
    "PATIENT_NAME_FIRST", "PATIENT_NAME_LAST", "PATIENT_EMAIL",
    "PATIENT_PHONE_NUMBER", "PATIENT_AGE", "DATE_OF_BIRTH",
]

# Columns we actually need (keeps memory lean)
# We keep PATIENT_EMAIL and PATIENT_PHONE_NUMBER presence as booleans, not the values

# Category thresholds
MIN_REFERRALS_FOR_CATEGORY = 5
CHAMPION_MIN_REFERRALS = 5
LOWEST_CONVERTING_MIN_REFERRALS = 5
