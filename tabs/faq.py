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

    with st.expander("Referral Pacing / Velocity", expanded=False):
        st.markdown("""
**How pacing is calculated:**
Pacing projects the current incomplete month or week to a full period based on **working days only** (Monday through Friday). Weekends and US federal holidays are excluded.

```
Projected = (Referrals so far / Working days elapsed) x Total working days in period
```

**Example:** If April 2026 has 608 referrals through April 11 (8 working days), and April has 22 total working days:
- Rate = 608 / 8 = 76 referrals per working day
- Projected = 76 x 22 = 1,672 for the full month

**Weekly pacing** uses 5 working days (Monday through Friday) as the denominator.

**Holidays excluded:** New Year's Day, MLK Day, Presidents' Day, Memorial Day, Independence Day, Labor Day, Columbus Day, Veterans Day, Thanksgiving, Christmas.

**"Behind/ahead" comparison:** The projected total is compared against the prior complete period's actual total. For example, "behind 11% vs prior" means the projected April total is 11% lower than March's actual total.

**Why working days?** Referrals primarily come from provider offices that operate on business days. Using calendar days would underestimate the daily rate (dividing by weekends when no referrals come in) and produce an artificially low projection.
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
The dashboard uses a coalesced provider identity: `REFERRING_PROVIDER_NPI` is the primary identifier. When NPI is missing or empty, we fall back to `REFERRING_PHYSICIAN` (the physician name field).

```
provider_id = REFERRING_PROVIDER_NPI ?? REFERRING_PHYSICIAN
```

NPI is available for ~78% of referrals. The fallback to physician name ensures the remaining ~22% are still counted.

**Unique provider counts:** "Unique Providers" in the KPI row, charts, and provider change detail counts distinct non-empty `provider_id` values within the selected scope and period.

**Provider Retention** uses `REFERRING_PHYSICIAN` (name only) to match the methodology validated against internal Talkiatry retention dashboards.
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

    with st.expander("Clinic Visit Plan — Priority Signals", expanded=False):
        st.markdown("""
**How the Clinic Visit Plan works:**
The My Team tab generates a prioritized list of clinics for each PPM to visit, based on signals detected in the referral data. Each clinic is scored, and the top clinics are assigned to P1, P2, or P3.

**Signals and scoring:**

| Signal | Score | Color | When it fires |
|---|---|---|---|
| Silent clinic | 4 | Red | Had 5+ referrals last period, zero this period |
| New high-volume clinic | 3 | Green | Never referred before, now has 3+ referrals |
| Volume surge | 3 | Green | Paced referral volume up 50%+ vs prior period (min 5 refs) |
| Volume cliff | 3 | Red | Paced referral volume down 50%+ vs prior period (min 5 refs) |
| Intake crash | 3 | Red | Intake start rate dropped 15+ percentage points (min 5 refs) |
| High-converting clinic | 2 | Green | 55%+ intake start rate with 5+ referrals — visit to learn what's working |
| New provider cluster | 2 | Green | 3+ first-time-ever providers referring from the same clinic |
| Volume doubled | 2 | Green | Paced volume is 2x+ the prior period (min 3 refs) |
| Persistently low intake | 2 | Red | Intake rate below 35% for both current AND prior period, with 5+ refs each |

**Priority tiers:**
- **P1 (Visit This Week)**: Total signal score of 4 or higher. Top 3 shown.
- **P2 (Visit This Month)**: Total signal score of 2-3. Next 3 shown.
- **P3 (Monitor / Schedule)**: Remaining signals. Next 3 shown.

**A clinic can trigger multiple signals.** For example, a clinic with a volume surge (+3) AND new provider cluster (+2) would score 5 and appear as P1. Scores are additive.

**Color coding:**
- **Green** = positive visit — thank them, learn from them, reinforce the relationship
- **Red** = intervention visit — something needs attention (volume drop, low conversion, silence)

**Pacing adjustment:**
The current partial month/week is projected to a full period using working days only (Monday-Friday, excluding US federal holidays). This prevents the incomplete current period from triggering false "volume cliff" alarms. For example, if April has 6 referrals in 9 working days, it's paced to 6/9 * 22 = 15 for the full month, not compared raw against March's 25.

**Minimum thresholds:**
Most signals require a minimum of 5 referrals to fire. This filters out noise from very small clinics where a single referral can swing percentages wildly. The "silent clinic" signal also requires 5+ in the prior period — a clinic that sent 1 referral last month and 0 this month is not a meaningful signal.
""")
