"""
constants.py
------------
Single source of truth for all shared thresholds, tiers, magic numbers,
colour palettes, and column names.
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

# ── Status label → background/foreground colours (used in signals table + action plan) ──
# Single source of truth — import in account_signals_table.py and action_plan.py
STATUS_BG: dict = {
    "STRONG":    "#E8F5E9",
    "GROWING":   "#F1F8E9",
    "HEALTHY":   "#E8F5E9",
    "FLAT":      "#FFFDE7",
    "MODERATE":  "#FFF8E1",
    "WATCH":     "#FFF8E1",
    "DECLINING": "#FBE9E7",
    "LOW":       "#FFEBEE",
    "AT RISK":   "#FFEBEE",
}
STATUS_FG: dict = {
    "STRONG":    "#2E7D32",
    "GROWING":   "#558B2F",
    "HEALTHY":   "#2E7D32",
    "FLAT":      "#F57F17",
    "MODERATE":  "#F57F17",
    "WATCH":     "#F57F17",
    "DECLINING": "#E65100",
    "LOW":       "#C62828",
    "AT RISK":   "#C62828",
}

# ── Insight sentiment styles (used in action_plan.py) ────────────────────────
SENTIMENT_STYLES: dict = {
    "negative": {"border": "#dc3545", "bg": "#fff5f5", "icon": "🔴", "badge": "background:#dc3545;color:white;"},
    "warning":  {"border": "#f5a623", "bg": "#fffbf0", "icon": "🟡", "badge": "background:#f5a623;color:white;"},
    "positive": {"border": "#27AE60", "bg": "#f0faf4", "icon": "🟢", "badge": "background:#27AE60;color:white;"},
}

# ── Column name constants (update here if CSV schema changes) ─────────────────
COL_REFERRAL_ID        = "REFERRAL_ID"
COL_REFERRAL_DATE      = "REFERRAL_DATE"
COL_PARTNER            = "PARTNER_ASSIGNMENT"
COL_PPM                = "PPM"
COL_CLINIC             = "REFERRING_CLINIC"
COL_CLINIC_ZIP         = "REFERRING_CLINIC_ZIP"
COL_PHYSICIAN          = "REFERRING_PHYSICIAN"
COL_PROVIDER_ID        = "provider_id"
COL_INTAKE_STARTED     = "intake_started"
COL_VISIT_BOOKED       = "visit_booked"
COL_VISIT_COMPLETED    = "visit_completed"
