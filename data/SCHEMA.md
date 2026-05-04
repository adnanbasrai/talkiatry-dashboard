# Referral Data Schema

Documentation of all columns available after `loader.py` processes the raw CSV.

---

## Raw / Source Columns (preserved after load)

| Column | Type | Description |
|--------|------|-------------|
| `REFERRAL_ID` | string | Unique identifier for each referral record |
| `REFERRAL_DATE` | datetime | Date the referral was submitted |
| `PARTNER_ASSIGNMENT` | string | Account / partner practice name (e.g. "Mass General Hospital") |
| `AREA` | string | Geographic region (e.g. "Northeast", "West", "Central") |
| `PPM` | string | Partner Performance Manager assigned to this account |
| `REFERRING_CLINIC` | string | Name of the clinic that submitted the referral |
| `REFERRING_CLINIC_ZIP` | string | 5-digit zip code of the referring clinic (coalesced from patient zip if missing) |
| `REFERRING_PHYSICIAN` | string | Name of the referring physician |
| `REFERRING_PROVIDER` | string | Pre-coalesced provider identity: NPI if available, physician name as fallback |
| `REFERRING_PROVIDER_NPI` | string | Raw NPI number of the referring provider |
| `SESSION_PATIENT_ID` | string | ID assigned when the patient is entered as a session patient (non-null = intake started) |
| `PSYCHIATRY_APPOINTMENT_ID_FIRST_SCHEDULED` | string | ID of the first scheduled psychiatry appointment (non-null = visit booked) |
| `PSYCHIATRY_APPOINTMENT_STATUS_FIRST_SCHEDULED_NON_CANCELED` | string | Attendance status of first appointment: ARR, CHK, No Show, LATE CANC |
| `IS_INTAKE_COMPLETED` | int | 1 if the intake process was marked complete, 0 otherwise |
| `INTAKE_ACTION_STATUS` | string | Current intake workflow status (New, Called, CalledSecondTime, CalledThirdTime, NonResponsive, Rejected) |
| `INTAKE_START_DATE` | datetime | Date intake was started |
| `TERMINATION_REASON` | string | Reason the referral was terminated (null = not terminated) |
| `APPOINTMENT_DATE_BOOKED_FIRST_SCHEDULED` | datetime | Date the first appointment was scheduled |
| `APPOINTMENT_DATE_BOOKED_FIRST_COMPLETED` | datetime | Date the first appointment was completed |
| `APPOINTMENT_SOURCE_FIRST_SCHEDULED` | string | Source channel for the first scheduled appointment |
| `IS_OUTREACH_CAMPAIGN_COMPLETED` | int | 1 if outreach campaign completed, 0 = in progress, null = none |
| `PATIENT_DOB` | datetime | Patient date of birth (parsed from raw, PII retained only as datetime) |
| `PATIENT_AGE` | int/float | Patient age in years (if DOB not available) |
| `PATIENT_INSURANCE_NAME` | string | Patient insurance plan name |

---

## Derived Columns (added by `loader.py`)

| Column | Type | Description |
|--------|------|-------------|
| `provider_id` | string | Coalesced provider identity: NPI (from `REFERRING_PROVIDER`) with physician name as fallback. Nulls excluded. |
| `patient_name` | string | Derived from `PATIENT_NAME_FIRST` + `PATIENT_NAME_LAST` (raw PII columns are dropped after derivation) |
| `has_email` | bool | True if `PATIENT_EMAIL` was non-null/non-blank before PII drop |
| `has_phone` | bool | True if `PATIENT_PHONE_NUMBER` was non-null/non-blank before PII drop |
| `month_of` | Period (M) | Calendar month of `REFERRAL_DATE` (e.g. `2026-04`) |
| `week_of` | datetime | Monday of the ISO week containing `REFERRAL_DATE` |
| `intake_started` | int (0/1) | 1 if `SESSION_PATIENT_ID` or `PSYCHIATRY_APPOINTMENT_ID_FIRST_SCHEDULED` is non-null |
| `intake_completed` | int (0/1) | 1 if `IS_INTAKE_COMPLETED == 1` |
| `visit_booked` | int (0/1) | 1 if `PSYCHIATRY_APPOINTMENT_ID_FIRST_SCHEDULED` is non-null |
| `visit_completed` | int (0/1) | 1 if first appointment was attended. Non-Kaiser: ARR/CHK/No Show/LATE CANC. Kaiser: ARR/CHK only. |
| `outreach_status` | string | Human-readable outreach state: "No outreach data", "Outreach in progress", "Outreach completed" |
| `termination_category` | string | Bucketed termination reason: Insurance OON, Recently Inpatient, Clinical Exclusion, Emergency, Minor, State Not Covered, Patient Declined, None, Other |

---

## Metric Derivations (computed in `transforms.py`)

These are not stored as columns but are computed on-demand by `compute_metrics()`:

| Metric | Formula | Notes |
|--------|---------|-------|
| `pct_intake` | `intake_started / referrals` | Omni-aligned denominator = total referrals |
| `pct_booked` | `visit_booked / referrals` | Omni-aligned denominator = total referrals |
| `pct_completed` | `visit_completed / referrals` | Omni-aligned denominator = total referrals |
| `pct_terminated` | `TERMINATION_REASON.notna() / referrals` | |
| `unique_providers` | `provider_id.nunique()` | Excludes null and blank provider IDs |

---

## Threshold Constants (from `data/constants.py`)

| Constant | Value | Used For |
|----------|-------|---------|
| `INTAKE_HEALTHY` | 0.55 | Ref→Intake ≥55% = Healthy |
| `INTAKE_WATCH` | 0.45 | Ref→Intake ≥45% = Watch |
| `BOOKED_HEALTHY` | 0.35 | Ref→Booked ≥35% = Healthy |
| `BOOKED_WATCH` | 0.25 | Ref→Booked ≥25% = Watch |
| `M1_STRONG` | 0.35 | M1 Retention ≥35% = Strong |
| `M1_MODERATE` | 0.25 | M1 Retention ≥25% = Moderate |
| `MIN_REFS` | 5 | Minimum referrals for a signal to fire |
| `MIN_COHORT` | 3 | Minimum first-time providers for M1 rate |
| `TREND_DECLINING` | -0.10 | Refs/Day MoM ≤-10% = declining |
| `TREND_GROWING` | 0.20 | Refs/Day MoM ≥+20% = growing |
| `MOM_DROP_PP` | -0.03 | MoM pp change ≤-3pp = noteworthy drop |
