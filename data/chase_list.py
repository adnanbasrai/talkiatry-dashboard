"""
Chase list loader — NE prospect / partner practices from HubSpot.
Filters to NE PPMs only, remaps partner labels to match referral data,
geocodes by zip, and returns a clean DataFrame.
"""
import os
import pandas as pd
import streamlit as st

CHASE_PATH = os.path.join(os.path.dirname(__file__), "NE_chase_list.csv")

NE_PPMS = {
    "Ashley Alexander", "Brittany Smith", "Christopher Breen",
    "Luke Young", "Danielle Maddi",
}

# Chase list label → referral data PARTNER_ASSIGNMENT
LABEL_REMAP = {
    "Arches Medical":                       "Arches Medical Group",
    "UMass":                                "UMass Memorial Hospital",
    "Consensus Health - North NJ":          "Consensus Health North NJ",
    "Consensus/PIC - North NJ":             "Consensus Health North NJ",
    "Consensus Health - South Central NJ":  "Consensus Health South NJ",
    "Consensus/PIC - South Central NJ":     "Consensus Health South NJ",
    "RWJBarnabas Health":                   "RWJ Barnabas Health",
    "NYU - Long Island":                    "NYU Long Island",
}

# Lifecycle priority (higher = more urgent to visit)
LIFECYCLE_PRIORITY = {
    "Go-Live":          5,
    "Pre-Launch":       4,
    "Active Partner":   3,
    "Active Engagement": 2,
    "Cold":             1,
}

# Colors for map rendering (R, G, B)
LIFECYCLE_COLOR = {
    "Go-Live":          [123, 45,  139],   # purple
    "Pre-Launch":       [155, 89,  182],   # light purple
    "Active Partner":   [52,  152, 219],   # blue
    "Active Engagement": [39, 174, 96],    # green
    "Cold":             [149, 165, 166],   # gray
}


@st.cache_data(ttl=3600)
def load_chase_list() -> pd.DataFrame:
    """Load and clean the NE chase list. Returns empty DataFrame if file not found."""
    if not os.path.exists(CHASE_PATH):
        return pd.DataFrame()

    df = pd.read_csv(CHASE_PATH, low_memory=False)

    # Filter to active NE PPMs only
    df = df[df["Company owner"].isin(NE_PPMS)].copy()

    # Rename columns to snake_case
    df = df.rename(columns={
        "Company name":                 "practice_name",
        "Company owner":                "ppm",
        "Partner Label":                "partner_label",
        "Lifecycle Stage":              "lifecycle_stage",
        "Postal Code":                  "zip",
        "Street Address":               "address",
        "City":                         "city",
        "State/Region":                 "state",
        "Number of Affiliated Physicians": "num_physicians",
        "Number of Associated Contacts":   "num_contacts",
        "Specialty":                    "specialty",
        "Healthcare Type":              "healthcare_type",
        "Last Activity Date":           "last_activity_date",
        "Record ID":                    "record_id",
    })

    # Remap partner labels to match referral account names
    df["partner_label"] = df["partner_label"].replace(LABEL_REMAP)

    # Clean zips to 5-digit strings
    df["zip"] = (
        df["zip"].astype(str)
        .str.split("-").str[0]
        .str.strip()
        .str.zfill(5)
        .replace({"00nan": None, "00000": None, "0None": None, "nan00": None})
    )

    # Numeric fields
    df["num_physicians"] = pd.to_numeric(df["num_physicians"], errors="coerce")
    df["num_contacts"]   = pd.to_numeric(df["num_contacts"],   errors="coerce")

    # Lifecycle priority rank (for sorting)
    df["lifecycle_rank"] = df["lifecycle_stage"].map(LIFECYCLE_PRIORITY).fillna(0)

    # Lifecycle colors (store as list per row)
    default_color = [150, 150, 150]
    df["color"] = df["lifecycle_stage"].apply(lambda lc: LIFECYCLE_COLOR.get(lc, default_color))

    # Geocode by zip (deferred — caller should merge after geocoding to avoid
    # importing geo_map here and creating a circular dep)
    return df
