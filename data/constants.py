"""
constants.py
------------
Single source of truth for all shared thresholds, tiers, and magic numbers.
Import from here instead of hardcoding values across files.
"""

# ── Conversion thresholds (Ref→Intake, Ref→Booked) ───────────────────────────
INTAKE_HEALTHY   = 0.55   # Ref→Intake: ≥55% = Healthy
INTAKE_WATCH     = 0.45   # Ref→Intake: ≥45% = Watch, <45% = At Risk
BOOKED_HEALTHY   = 0.35   # Ref→Booked: ≥35% = Healthy
BOOKED_WATCH     = 0.25   # Ref→Booked: ≥25% = Watch, <25% = At Risk

# ── M1 Retention thresholds ───────────────────────────────────────────────────
M1_STRONG        = 0.35   # M1 Retention: ≥35% = Strong
M1_MODERATE      = 0.25   # M1 Retention: ≥25% = Moderate, <25% = Low

# ── Volume / signal thresholds ────────────────────────────────────────────────
MIN_REFS         = 5      # Minimum referrals for a signal or metric to fire
MIN_COHORT       = 3      # Minimum intake starters for booked-rate signal
TREND_DECLINING  = -0.10  # Refs/Day MoM: ≤-10% = declining signal
TREND_GROWING    =  0.20  # Refs/Day MoM: ≥+20% = positive signal
MOM_DROP_PP      = -0.03  # MoM pp change: ≤-3pp = noteworthy drop

# ── Percentile tier cutoffs (used in account signals ranking) ─────────────────
PCT_TIERS        = [80, 60, 40, 20, 0]

# ── Working day defaults (used when period boundary is unknown) ───────────────
DEFAULT_WDAYS_MONTH = 22
DEFAULT_WDAYS_WEEK  = 5
