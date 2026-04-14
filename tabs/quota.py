import streamlit as st
import pandas as pd
from data.transforms import count_unique_providers

# Q2 2026 quotas from AD screenshot
Q2_QUOTAS = {
    "Luke Young":          {"providers": 685,  "referrals": 1513, "visits": 542},
    "Danielle Maddi":      {"providers": 218,  "referrals": 481,  "visits": 173},
    "Christopher Breen":   {"providers": 153,  "referrals": 337,  "visits": 122},
    "Brittany Smith":      {"providers": 190,  "referrals": 419,  "visits": 151},
    "Ashley Alexander":    {"providers": 315,  "referrals": 695,  "visits": 250},
}

Q2_START = pd.Timestamp("2026-04-01")
Q2_END = pd.Timestamp("2026-06-30")
Q2_MONTHS = [pd.Period("2026-04", "M"), pd.Period("2026-05", "M"), pd.Period("2026-06", "M")]


def render(df):
    st.subheader("Q2 2026 Quota Attainment")
    st.markdown(
        '<div style="background-color: #fff3cd; padding: 8px 14px; border-radius: 6px; font-size: 13px; border-left: 4px solid #ffc107;">'
        'Work in progress. Unique providers are counted at the monthly level '
        '(a provider referring in April and May counts as 2). Q2 = April + May + June 2026.</div>',
        unsafe_allow_html=True,
    )

    # Filter to Q2 data
    q2 = df[(df["REFERRAL_DATE"] >= Q2_START) & (df["REFERRAL_DATE"] <= Q2_END)]

    if q2.empty:
        st.warning("No Q2 2026 data available yet.")
        return

    # Compute actuals per PPM
    rows = []
    for ppm, targets in Q2_QUOTAS.items():
        ppm_df = q2[q2["PPM"] == ppm]

        actual_refs = len(ppm_df)

        actual_provs = 0
        for m in Q2_MONTHS:
            month_df = ppm_df[ppm_df["month_of"] == m]
            if not month_df.empty:
                actual_provs += count_unique_providers(month_df["provider_id"])

        actual_visits = int(ppm_df["visit_booked"].sum())

        rows.append({
            "PPM": ppm,
            "Refs Actual": actual_refs,
            "Refs Quota": targets["referrals"],
            "Refs %": actual_refs / targets["referrals"] if targets["referrals"] > 0 else 0,
            "Provs Actual": actual_provs,
            "Provs Quota": targets["providers"],
            "Provs %": actual_provs / targets["providers"] if targets["providers"] > 0 else 0,
            "Visits Actual": actual_visits,
            "Visits Quota": targets["visits"],
            "Visits %": actual_visits / targets["visits"] if targets["visits"] > 0 else 0,
        })

    result = pd.DataFrame(rows)

    display = result.copy()
    display["Referrals"] = display.apply(lambda r: f"{int(r['Refs Actual']):,} / {int(r['Refs Quota']):,} ({r['Refs %']:.0%})", axis=1)
    display["Providers"] = display.apply(lambda r: f"{int(r['Provs Actual']):,} / {int(r['Provs Quota']):,} ({r['Provs %']:.0%})", axis=1)
    display["Visits"] = display.apply(lambda r: f"{int(r['Visits Actual']):,} / {int(r['Visits Quota']):,} ({r['Visits %']:.0%})", axis=1)

    st.dataframe(
        display[["PPM", "Providers", "Referrals", "Visits"]].reset_index(drop=True),
        use_container_width=True, hide_index=True,
    )

    st.caption("Note: Estimated actual attainment will be calculated at the end of the quarter (June 30, 2026). Current numbers reflect partial Q2 progress.")
