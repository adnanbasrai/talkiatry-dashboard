import streamlit as st


def render():
    st.header("Methodology & FAQs")
    st.caption("How metrics are calculated and key data assumptions throughout this dashboard.")

    with st.expander("Referral Counting", expanded=False):
        st.markdown("""
**What counts as a referral?**
Each row in the data represents one unique referral, identified by `REFERRAL_ID`. The referral date (`REFERRAL_DATE`) determines which month or week it falls into.

**Time periods:**
- **Monthly view**: Groups by calendar month (e.g., Jan 2026 = Jan 1–31).
- **Weekly view**: Groups by the Monday of each week. A referral on Wednesday Jan 15 belongs to the week of Monday Jan 13.

**Incomplete period shading:**
The most recent month or week is shown as a lighter bar color to indicate the period is not yet complete and numbers will continue to grow.

**KPI cards:**
The KPI row shows the **last complete period** (second-to-last month/week), not the current partial one. Deltas compare against the period before that.
""")

    with st.expander("Intake Started", expanded=False):
        st.markdown("""
**Definition:**
A referral is counted as "intake started" if **any** of the following are true:
1. `INTAKE_START_DATE` is not empty (patient began the intake assessment), **OR**
2. `APPOINTMENT_ID_FIRST_SCHEDULED` is not empty (a visit was booked), **OR**
3. `APPOINTMENT_DATE_BOOKED_FIRST_SCHEDULED` is not empty

**Why include booked visits?**
Some patients have a booked appointment without a recorded intake start date. Since booking a visit implies the intake process was engaged, we count these as intake started to avoid undercounting.

**% Intake Started** = Referrals where intake started / Total referrals

**What "not started" means:**
If none of the three fields above have a value, the patient never engaged with the intake process after being referred. This is the largest drop-off point in the funnel (~46% of referrals).
""")

    with st.expander("Visit Booked", expanded=False):
        st.markdown("""
**Definition:**
A referral is counted as "visit booked" if `APPOINTMENT_ID_FIRST_SCHEDULED` is not empty.

**% Visit Booked** = Referrals with a booked first appointment / Total referrals

This measures the full funnel from referral to booking, not just intake-to-booking.
""")

    with st.expander("Visit Completed", expanded=False):
        st.markdown("""
**Definition:**
A referral is counted as "visit completed" if `APPOINTMENT_ID_FIRST_COMPLETED` is not empty.

**% Visit Completed** = Referrals with a completed first visit / Total referrals

**Note on recency:** Recent referrals (especially the last 2–4 weeks) will naturally show lower completion rates because appointments may be scheduled but haven't occurred yet. This is expected, not a conversion problem.
""")

    with st.expander("Zip Code Logic", expanded=False):
        st.markdown("""
**Coalesce rule:** Clinic zip code is the primary geographic identifier. If `REFERRING_CLINIC_ZIP` is missing, we fall back to `PATIENT_POSTAL_CODE`.

```
ZIP = REFERRING_CLINIC_ZIP ?? PATIENT_POSTAL_CODE
```

**Cleaning:** All zip codes are normalized to 5 digits (e.g., `10006-1901` becomes `10006`).

**Coverage:** This coalesce recovers ~1,000 referrals that would otherwise have no geographic data. Approximately 600 referrals still have no zip from either source.

**Map visualization:** Bubble size represents referral volume at that zip. Color represents booking rate (green = high, red = low). Hovering shows the partner breakdown for that zip.
""")

    with st.expander("Provider Identity (NPI vs. Physician Name)", expanded=False):
        st.markdown("""
**How providers are identified:**
Throughout this dashboard, providers are identified by `REFERRING_PHYSICIAN` (the physician name field). This matches the methodology used in the internal Talkiatry retention dashboards.

**Why not NPI?**
While `REFERRING_PROVIDER_NPI` is available for ~78% of referrals, using it as the primary identifier can split the same physician into multiple identities (e.g., when an NPI is missing for some referrals). The physician name field provides more consistent matching.

**Unique provider counts:** "Unique Providers" in the KPI row and charts counts distinct non-empty `REFERRING_PHYSICIAN` values within the selected scope and period.
""")

    with st.expander("Provider Retention Cohorts", expanded=False):
        st.markdown("""
**How retention is calculated:**
1. Each provider's **cohort** is the month they first referred within the selected scope (account, PPM, or all).
2. **M0** (first month) is always 100% — every provider referred in their cohort month by definition.
3. **M1, M2, M3...** show what percentage of that cohort's providers referred again 1, 2, 3 months later.

**Example:** If 34 providers first referred to Allara Health in January 2026, and 24 of them also referred in February, M1 = 70.6%.

**NaN values** in later months mean that month hasn't occurred yet, not that retention is 0%.

**Color coding:** Green (60%+), Yellow (40–60%), Red (below 40%).
""")

    with st.expander("Provider & Clinic Categories", expanded=False):
        st.markdown("""
**Champions:**
Entities (clinics or providers) with referral count **at or above the median** AND booking rate **at or above the median** among all entities with 5+ referrals. These are high-volume, high-converting partners. Sorted by volume descending. Top 20 shown.

**Lowest Converting:**
Entities with 5+ referrals but booking rate in the **bottom 25th percentile**. These have enough volume to be statistically meaningful but are converting poorly. Sorted by booking rate ascending. Top 20 shown.

**Stopped Referring:**
Entities that referred in the prior period (month or week, based on your toggle) but have **zero referrals** in the most recent period. Sorted by their prior period volume descending.

**First-Time Referrers:**
Entities whose very first referral in the dataset falls within the most recent period. These are newly activated partners.
""")

    with st.expander("Conversion Deep Dive — Root Causes", expanded=False):
        st.markdown("""
**Stage 1: Referral to Intake Start**
Root cause categories for referrals that never started intake:
- **No outreach data**: `IS_OUTREACH_CAMPAIGN_COMPLETED` is empty — no record of the care team reaching out.
- **Outreach completed**: Care team completed outreach but the patient still didn't start intake.
- **Outreach in progress**: Outreach campaign is underway but not yet completed.
- **Missing contact info**: Patient has no email AND no phone number on file.

**Stage 2: Intake Start to Visit Booked**
Root cause categories for patients who started intake but didn't book:
- **Insurance OON**: Terminated because the patient's insurance is out of network. Identified by `TERMINATION_REASON` containing "OON" or "InsurancePlanOutOfNetwork".
- **Non-responsive**: `INTAKE_ACTION_STATUS` = "NonResponsive" — patient stopped engaging during intake.
- **Still in progress**: `INTAKE_ACTION_STATUS` = "New" — patient hasn't finished intake yet (may still convert).
- **Clinical rejection**: Terminated for clinical reasons (recently inpatient, schizophrenia, emergency, minor).
- **Patient declined**: Patient indicated they are no longer interested.

**Stage 3: Visit Booked to Visit Completed**
Root cause categories for booked visits that weren't completed:
- **Future appointment**: The booked visit date hasn't occurred yet.
- **Rejected after booking**: Patient was rejected after booking (e.g., insurance issue discovered later).
- **Non-responsive after booking**: Patient stopped responding after booking.
- Broken down by **booking source**: organic (patient self-scheduled through intake) vs. PCC (care team scheduled).
""")

    with st.expander("KPI Drill-Down Popovers", expanded=False):
        st.markdown("""
**Provider Change Detail** (under Unique Providers):
Shows two tabs:
- **New Providers**: Providers who referred this period but did NOT refer in the prior period. Sorted by referral count.
- **Lost Providers**: Providers who referred last period but have ZERO referrals this period. Sorted by their prior referral count.
When viewing across multiple accounts, an Account column is included.

**Intake / Booking / Completion Drivers** (under each conversion metric):
Shows the top 10 accounts driving the biggest change in that conversion rate vs. the prior period. Ranked by **volume-weighted impact** (percentage change multiplied by referral volume) so large accounts that move the needle surface first, rather than tiny accounts with 100% swings.
""")

    with st.expander("Team Type", expanded=False):
        st.markdown("""
**What is Team Type?**
Each account is classified as one of:
- **Core Managed**: Strategic accounts actively managed by a PPM with regular engagement cadence.
- **Core Not Managed**: Important accounts that don't currently have a dedicated PPM assigned.
- **Outreach**: Accounts being prospected or in early engagement stages by the outreach team.

This field appears in the Account Rankings table across all tabs.
""")
