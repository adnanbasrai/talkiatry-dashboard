import pandas as pd
import numpy as np
from data.constants import (
    INTAKE_HEALTHY, INTAKE_WATCH, BOOKED_HEALTHY, BOOKED_WATCH,
    M1_STRONG, M1_MODERATE, MIN_REFS, MIN_COHORT,
    TREND_DECLINING, TREND_GROWING, MOM_DROP_PP,
    PCT_TIERS, DEFAULT_WDAYS_MONTH,
)


def format_period_label(period, period_col: str) -> str:
    """Return a human-readable short label for a period value.

    Args:
        period: A pandas Period (for month_of) or Timestamp/string (for week_of).
        period_col: Either "month_of" or "week_of".

    Returns:
        e.g. "April 2026" for monthly, "week of Apr 7" for weekly.
    """
    try:
        if period_col == "month_of":
            return pd.Period(str(period), freq="M").strftime("%B %Y")
        else:
            monday = pd.Timestamp(str(period))
            return f"week of {monday.strftime('%b %-d')}"
    except Exception:
        return str(period)


def derive_referral_status(row) -> str:
    """Map a referral row to a human-readable status string.

    This is the single source of truth for referral status derivation — used by
    the Visit Prep tab, the PDF export, and any future status displays. Keeps
    business logic out of rendering modules.

    Args:
        row: A dict-like object (DataFrame row) with referral fields.

    Returns:
        A status string such as "Visit Completed", "Rejected — Insurance OON", etc.
    """
    if row.get("visit_completed") == 1:
        return "Visit Completed"
    if row.get("visit_booked") == 1:
        return "Visit Booked"

    action = row.get("INTAKE_ACTION_STATUS", "") or ""
    termination = row.get("TERMINATION_REASON", "") or ""

    if action == "Rejected":
        if pd.notna(termination) and termination:
            tr = str(termination)
            if any(k in tr for k in ("OON", "OutOfNetwork", "InsurancePlan", "Payor")):
                return "Rejected — Insurance OON"
            if "Minor" in tr:
                return "Rejected — Minor"
            if "Inpatient" in tr:
                return "Rejected — Recently Inpatient"
            if "Emergency" in tr:
                return "Rejected — Emergency"
            if "Schizo" in tr:
                return "Rejected — Clinical"
            return f"Rejected — {tr[:30]}"
        return "Rejected"

    is_completed = row.get("IS_INTAKE_COMPLETED")
    if is_completed == 1 and action == "NonResponsive":
        return "Intake Done — Non-Responsive"
    if is_completed == 1 and action in ("New", "Called", "CalledSecondTime", "CalledThirdTime"):
        return "Intake Done — Awaiting Booking"
    if is_completed == 1:
        return "Intake Completed"

    if action == "NonResponsive":
        return "Non-Responsive"
    if action == "New":
        return "Intake In Progress"
    if action in ("Called", "CalledSecondTime", "CalledThirdTime"):
        return "Outreach In Progress"
    if row.get("intake_started") == 1:
        return "Intake Started"

    return "Not Started"


def count_unique_providers(series: pd.Series) -> int:
    """Count unique non-blank provider_ids. Nulls and empty strings are excluded."""
    non_null = series.dropna()
    non_blank = non_null[non_null.astype(str).str.strip() != ""]
    return non_blank.nunique()


def _period_is_complete(period, period_col: str) -> bool:
    """Return True if the given period has fully elapsed as of today."""
    today = pd.Timestamp.now().normalize()
    try:
        if period_col == "month_of":
            end = pd.Period(str(period), freq="M").end_time.normalize()
        else:
            end = pd.Timestamp(str(period)) + pd.Timedelta(days=6)
        return today > end
    except Exception:
        return False


def last_complete_periods(periods, period_col: str):
    """Return (curr, prev, prev2) — the last 3 fully elapsed periods.
    Handles the case where the last period in the data IS complete
    (e.g. it's May 1 and the data only goes through April)."""
    complete = [p for p in periods if _period_is_complete(p, period_col)]
    if not complete:
        complete = list(periods[:-1]) if len(periods) >= 2 else list(periods)
    curr  = complete[-1] if len(complete) >= 1 else None
    prev  = complete[-2] if len(complete) >= 2 else None
    prev2 = complete[-3] if len(complete) >= 3 else None
    return curr, prev, prev2


def compute_metrics(df: pd.DataFrame) -> dict:
    """Compute KPI metrics for a given slice of data.
    Funnel denominators (matches Omni):
      Ref→Intake    = intake_started  / total_referrals
      Ref→Booked    = visit_booked    / total_referrals
      Ref→Completed = visit_completed / total_referrals
    """
    n = len(df)
    if n == 0:
        return {k: 0 for k in ["referrals", "unique_providers", "pct_intake", "pct_booked", "pct_completed", "pct_terminated"]}
    n_term   = df["TERMINATION_REASON"].notna().sum() if "TERMINATION_REASON" in df.columns else 0
    n_booked = int(df["visit_booked"].sum())
    return {
        "referrals":        n,
        "unique_providers": count_unique_providers(df["provider_id"]),
        "pct_intake":       int(df["intake_started"].sum()) / n,
        "pct_booked":       n_booked / n,
        "pct_completed":    df["visit_completed"].sum() / n,
        "pct_terminated":   n_term / n,
    }


def _us_holidays(year: int) -> list:
    """Return US federal holiday dates for a given year."""
    from datetime import date
    holidays = [
        date(year, 1, 1),    # New Year's Day
        date(year, 7, 4),    # Independence Day
        date(year, 12, 25),  # Christmas
        date(year, 11, 11),  # Veterans Day
    ]
    # MLK Day: 3rd Monday in January
    jan1 = date(year, 1, 1)
    mlk = date(year, 1, 15 + (0 - date(year, 1, 15).weekday()) % 7)
    holidays.append(mlk)
    # Presidents' Day: 3rd Monday in February
    holidays.append(date(year, 2, 15 + (0 - date(year, 2, 15).weekday()) % 7))
    # Memorial Day: last Monday in May
    may31 = date(year, 5, 31)
    holidays.append(date(year, 5, 31 - (may31.weekday()) % 7) if may31.weekday() >= 0 else may31)
    # Labor Day: 1st Monday in September
    holidays.append(date(year, 9, 1 + (0 - date(year, 9, 1).weekday()) % 7))
    # Columbus Day: 2nd Monday in October
    holidays.append(date(year, 10, 8 + (0 - date(year, 10, 8).weekday()) % 7))
    # Thanksgiving: 4th Thursday in November
    holidays.append(date(year, 11, 22 + (3 - date(year, 11, 22).weekday()) % 7))
    return holidays


def _count_weekdays(start: pd.Timestamp, end: pd.Timestamp) -> int:
    """Count Mon-Fri business days between two dates, excluding US holidays."""
    if start >= end:
        return 1
    years = set(range(start.year, end.year + 1))
    holidays = []
    for y in years:
        holidays.extend(_us_holidays(y))
    holiday_dates = np.array([np.datetime64(h) for h in holidays])
    return max(int(np.busday_count(start.date(), end.date(), holidays=holiday_dates)), 1)


# Public alias — use this name in new code; _count_weekdays preserved for back-compat.
wdays = _count_weekdays


def compute_velocity(df: pd.DataFrame, period_col: str) -> dict:
    """Project current partial period to full period based on working-day run rate."""
    periods = sorted(df[period_col].dropna().unique())
    if len(periods) < 2:
        return None

    curr_period = periods[-1]
    prev_period = periods[-2]
    curr_df = df[df[period_col] == curr_period]
    curr_count = len(curr_df)
    today = pd.Timestamp.now().normalize()

    if period_col == "month_of":
        month_start = pd.Period(curr_period, freq="M").start_time
        month_end = pd.Period(curr_period, freq="M").end_time + pd.Timedelta(days=1)  # exclusive end
        weekdays_elapsed = max(_count_weekdays(month_start, today), 1)
        weekdays_total = max(_count_weekdays(month_start, month_end), 1)
        projected = int(curr_count / weekdays_elapsed * weekdays_total)
        prev_count = len(df[df[period_col] == prev_period])
        return {
            "current": curr_count,
            "projected": projected,
            "prior": prev_count,
            "pct_vs_prior": (projected - prev_count) / prev_count if prev_count > 0 else 0,
            "label": f"{pd.Period(curr_period, freq='M').strftime('%b %Y')}",
        }
    else:
        week_start = pd.Timestamp(curr_period)
        week_end = week_start + pd.Timedelta(days=5)  # Mon-Fri = 5 weekdays
        weekdays_elapsed = max(_count_weekdays(week_start, today), 1)
        weekdays_total = 5  # Mon-Fri
        projected = int(curr_count / weekdays_elapsed * weekdays_total)
        prev_count = len(df[df[period_col] == prev_period])
        return {
            "current": curr_count,
            "projected": projected,
            "prior": prev_count,
            "pct_vs_prior": (projected - prev_count) / prev_count if prev_count > 0 else 0,
            "label": f"Week of {week_start.strftime('%b %d')}",
        }


def compute_period_metrics(df: pd.DataFrame, period_col: str) -> pd.DataFrame:
    """Aggregate metrics by time period (month_of or week_of).
    All referrals are included in conversion denominators.
    """
    grouped = df.groupby(period_col).agg(
        referrals=("REFERRAL_ID", "count"),
        intake_started=("intake_started", "sum"),
        visit_booked=("visit_booked", "sum"),
        visit_completed=("visit_completed", "sum"),
    ).reset_index()

    grouped["pct_intake"]    = grouped["intake_started"]  / grouped["referrals"].replace(0, np.nan)
    grouped["pct_booked"]    = grouped["visit_booked"]    / grouped["referrals"].replace(0, np.nan)
    grouped["pct_completed"] = grouped["visit_completed"] / grouped["referrals"].replace(0, np.nan)
    grouped[period_col] = grouped[period_col].astype(str)
    return grouped.sort_values(period_col)


def compute_entity_table(df: pd.DataFrame, entity_col: str, period_col: str = "month_of", include_account: bool = False) -> pd.DataFrame:
    """Build a ranking table for clinics or providers with trend and days since last referral.
    All referrals are included in conversion denominators.
    """
    group_cols = [entity_col, "PARTNER_ASSIGNMENT"] if include_account else [entity_col]

    agg = df.groupby(group_cols).agg(
        referrals=("REFERRAL_ID", "count"),
        last_referral_date=("REFERRAL_DATE", "max"),
        first_referral_date=("REFERRAL_DATE", "min"),
        intake_started=("intake_started", "sum"),
        visit_booked=("visit_booked", "sum"),
        visit_completed=("visit_completed", "sum"),
    ).reset_index()

    # Average days between referrals (total span / referral count)
    span_days = (agg["last_referral_date"] - agg["first_referral_date"]).dt.days
    agg["avg_days_between"] = (span_days / agg["referrals"].clip(lower=1)).round(1)
    agg["pct_intake"]    = (agg["intake_started"]  / agg["referrals"].replace(0, np.nan)).fillna(0)
    agg["pct_booked"]    = (agg["visit_booked"]    / agg["referrals"].replace(0, np.nan)).fillna(0)
    agg["pct_completed"] = (agg["visit_completed"] / agg["referrals"].replace(0, np.nan)).fillna(0)

    # Days since last referral
    today = pd.Timestamp.now().normalize()
    agg["days_since_last"] = (today - agg["last_referral_date"]).dt.days

    # Trend: compare last 2 periods
    periods = sorted(df[period_col].dropna().unique())
    if len(periods) >= 2:
        curr_period, prev_period = periods[-1], periods[-2]
        curr = df[df[period_col] == curr_period].groupby(group_cols)["REFERRAL_ID"].count()
        prev = df[df[period_col] == prev_period].groupby(group_cols)["REFERRAL_ID"].count()
        trend = ((curr - prev) / prev.replace(0, np.nan)).rename("trend")
        agg = agg.merge(trend.reset_index(), on=group_cols, how="left")
    else:
        agg["trend"] = np.nan

    # Category tags
    qualified = agg[agg["referrals"] >= 5]
    agg["category"] = ""
    if len(qualified) > 0:
        med_vol = qualified["referrals"].median()
        med_intake = qualified["pct_intake"].median()
        p25_intake = qualified["pct_intake"].quantile(0.25)
        champ_mask = (agg["referrals"] >= med_vol) & (agg["pct_intake"] >= med_intake) & (agg["referrals"] >= 5)
        low_mask = (agg["pct_intake"] <= p25_intake) & (agg["referrals"] >= 5) & (~champ_mask)
        agg.loc[champ_mask, "category"] = "Champion"
        agg.loc[low_mask, "category"] = "Low Converting"

    # First-time (first referral in most recent period)
    if len(periods) >= 1:
        first_dates = df.groupby(group_cols)["REFERRAL_DATE"].min().reset_index()
        first_dates.columns = group_cols + ["first_referral_date"]
        cutoff = pd.Period(periods[-1], freq="M").start_time if period_col == "month_of" else periods[-1]
        first_names = set(first_dates[first_dates["first_referral_date"] >= cutoff][entity_col])
        new_mask = agg[entity_col].isin(first_names) & (agg["category"] == "")
        agg.loc[new_mask, "category"] = "New"

    # Stopped (had referrals in prior period, none in current)
    if len(periods) >= 2:
        prev_entities = set(df[df[period_col] == prev_period][entity_col].unique())
        curr_entities = set(df[df[period_col] == curr_period][entity_col].unique())
        stopped_names = prev_entities - curr_entities
        stopped_mask = agg[entity_col].isin(stopped_names) & (agg["category"] == "")
        agg.loc[stopped_mask, "category"] = "Stopped"

    return agg.sort_values("referrals", ascending=False)


def compute_account_signals_table(df: pd.DataFrame, period_col: str, rank_df=None) -> pd.DataFrame:
    """
    Compute per-account signal metrics and statuses for the account rankings table.
    Mirrors the 7-signal methodology from the NE Account Signals Excel.

    Args:
      df       — accounts to display (may be a filtered subset, e.g. one PPM's portfolio)
      rank_df  — population to use for percentile ranking (default: same as df).
                 Pass the full NE dataset so statuses mean the same thing regardless
                 of which filter is active.

    Returns one row per account in df with both raw values and status labels.
    Signal columns:
      trend_*        — refs/working-day MoM % change (percentile-ranked)
      intake_*       — Ref→Intake current rate (absolute thresholds)
      booked_*       — Intake→Booked current rate (absolute thresholds)
      intake_mom_*   — Ref→Intake MoM pp change (percentile-ranked)
      booked_mom_*   — Intake→Booked MoM pp change (percentile-ranked)
      m1_*           — M1 retention current (absolute thresholds, monthly only)
      m1_mom_*       — M1 MoM pp change (percentile-ranked, monthly only)
    """
    # rank_df is the full population for percentile ranking.
    # If not supplied, rank within df itself (preserves existing behaviour).
    if rank_df is None:
        rank_df = df

    # Derive periods from rank_df so the ranking window is consistent.
    periods = sorted(rank_df[period_col].dropna().unique())
    if len(periods) < 2:
        return pd.DataFrame()

    curr_period, prev_period, prev2_period = last_complete_periods(periods, period_col)
    if curr_period is None:
        return pd.DataFrame()

    is_monthly = period_col == "month_of"

    # ── Working days per period ───────────────────────────────────────────────
    def _workdays(period):
        try:
            if is_monthly:
                p     = pd.Period(str(period), freq="M")
                start = p.start_time
                end   = p.end_time + pd.Timedelta(days=1)
            else:
                start = pd.Timestamp(str(period))
                end   = start + pd.Timedelta(days=7)
            return max(_count_weekdays(start, end), 1)
        except Exception:
            return DEFAULT_WDAYS_MONTH

    curr_days = _workdays(curr_period)
    prev_days = _workdays(prev_period) if prev_period is not None else None

    # ── Thresholds (from data.constants) ─────────────────────────────────────
    INTAKE_ABS  = {"HEALTHY": INTAKE_HEALTHY, "WATCH": INTAKE_WATCH}
    BOOKED_ABS  = {"HEALTHY": BOOKED_HEALTHY, "WATCH": BOOKED_WATCH}  # % of total refs (matches Omni)
    M1_ABS      = {"STRONG": M1_STRONG, "MODERATE": M1_MODERATE}
    _PCT_TIERS  = [("STRONG", 80), ("GROWING", 60), ("FLAT", 40), ("DECLINING", 20), ("AT RISK", 0)]

    def _pct_status(rank):
        if rank is None or (isinstance(rank, float) and np.isnan(rank)):
            return "N/A"
        for label, threshold in _PCT_TIERS:
            if rank >= threshold:
                return label
        return "AT RISK"

    def _intake_status(r):
        if r is None or (isinstance(r, float) and np.isnan(r)): return "N/A"
        if r >= INTAKE_ABS["HEALTHY"]: return "HEALTHY"
        if r >= INTAKE_ABS["WATCH"]:   return "WATCH"
        return "AT RISK"

    def _booked_status(r):
        if r is None or (isinstance(r, float) and np.isnan(r)): return "N/A"
        if r >= BOOKED_ABS["HEALTHY"]: return "HEALTHY"
        if r >= BOOKED_ABS["WATCH"]:   return "WATCH"
        return "AT RISK"

    def _m1_status(r):
        if r is None or (isinstance(r, float) and np.isnan(r)): return "N/A"
        if r >= M1_ABS["STRONG"]:   return "STRONG"
        if r >= M1_ABS["MODERATE"]: return "MODERATE"
        return "LOW"

    def _m1_rate(df_acct, cohort_period, retention_period):
        """% of providers whose first referral to this account was in cohort_period
        who also referred in retention_period."""
        first = df_acct.groupby("provider_id")["REFERRAL_DATE"].min().reset_index()
        first["first_period"] = first["REFERRAL_DATE"].dt.to_period("M").astype(str)
        cohort = set(first[first["first_period"] == str(cohort_period)]["provider_id"])
        if len(cohort) < MIN_COHORT:
            return None
        retained = set(df_acct[df_acct[period_col] == retention_period]["provider_id"].dropna())
        return len(cohort & retained) / len(cohort)

    # ── Per-account computation ───────────────────────────────────────────────
    rows = []
    # Compute metrics for every account in rank_df (full NE population).
    # Percentile ranks are then computed across this full set.
    # At the end we filter rows down to accounts present in df.
    for acct, adf in rank_df.groupby("PARTNER_ASSIGNMENT"):
        curr_df = adf[adf[period_col] == curr_period]
        prev_df = adf[adf[period_col] == prev_period] if prev_period is not None else pd.DataFrame()

        curr_n = len(curr_df)
        prev_n = len(prev_df)

        # Total referrals across full date range
        total_refs = len(adf)

        # Days since last referral
        last_ref    = adf["REFERRAL_DATE"].max()
        days_silent = int((pd.Timestamp.now().normalize() - last_ref).days) if pd.notna(last_ref) else None

        # Referral trend — refs per working day MoM %
        curr_rpd = curr_n / curr_days
        prev_rpd = (prev_n / prev_days) if prev_days else None
        mom_pct  = (curr_rpd - prev_rpd) / prev_rpd if (prev_rpd and prev_rpd > 0) else None

        # Conversion current
        intake_n    = int(curr_df["intake_started"].sum())
        intake_rate = intake_n / curr_n if curr_n >= MIN_REFS else None
        booked_rate = curr_df["visit_booked"].sum() / curr_n if curr_n >= MIN_REFS else None

        # Conversion prior
        intake_prev_n = int(prev_df["intake_started"].sum()) if not prev_df.empty else 0
        intake_prev   = intake_prev_n / prev_n if prev_n >= MIN_REFS else None
        booked_prev   = prev_df["visit_booked"].sum() / prev_n if prev_n >= MIN_REFS else None

        # Conversion MoM (pp change)
        intake_mom = (intake_rate - intake_prev) if (intake_rate is not None and intake_prev is not None) else None
        booked_mom = (booked_rate - booked_prev) if (booked_rate is not None and booked_prev is not None) else None

        # M1 retention (monthly view only)
        m1_curr = m1_mom = None
        if is_monthly and prev_period is not None:
            m1_curr    = _m1_rate(adf, prev_period, curr_period)
            if prev2_period is not None:
                m1_prev_val = _m1_rate(adf, prev2_period, prev_period)
                if m1_curr is not None and m1_prev_val is not None:
                    m1_mom = m1_curr - m1_prev_val

        rows.append({
            "PARTNER_ASSIGNMENT": acct,
            "total_refs":         total_refs,
            "days_silent":        days_silent,
            "curr_rpd":           curr_rpd,
            "prev_rpd":           prev_rpd,
            "mom_pct":            mom_pct,
            "intake_rate":        intake_rate,
            "booked_rate":        booked_rate,
            "intake_mom":         intake_mom,
            "booked_mom":         booked_mom,
            "m1_rate":            m1_curr,
            "m1_mom":             m1_mom,
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # ── Percentile ranks for trend and MoM signals ────────────────────────────
    def _rank(s):
        return s.rank(pct=True, na_option="keep") * 100

    out["trend_rank"]       = _rank(out["mom_pct"])
    out["intake_mom_rank"]  = _rank(out["intake_mom"])
    out["booked_mom_rank"]  = _rank(out["booked_mom"])

    # ── Statuses ──────────────────────────────────────────────────────────────
    out["trend_status"]       = out["trend_rank"].map(_pct_status)
    out["intake_status"]      = out["intake_rate"].map(_intake_status)
    out["booked_status"]      = out["booked_rate"].map(_booked_status)
    out["intake_mom_status"]  = out["intake_mom_rank"].map(_pct_status)
    out["booked_mom_status"]  = out["booked_mom_rank"].map(_pct_status)

    if is_monthly:
        out["m1_mom_rank"]   = _rank(out["m1_mom"])
        out["m1_status"]     = out["m1_rate"].map(_m1_status)
        out["m1_mom_status"] = out["m1_mom_rank"].map(_pct_status)

    # ── PPM ───────────────────────────────────────────────────────────────────
    ppm_map     = rank_df.groupby("PARTNER_ASSIGNMENT")["PPM"].first()
    out["PPM"]  = out["PARTNER_ASSIGNMENT"].map(ppm_map)

    # Filter displayed rows to accounts that appear in df (the caller's subset).
    display_accounts = set(df["PARTNER_ASSIGNMENT"].unique())
    out = out[out["PARTNER_ASSIGNMENT"].isin(display_accounts)]

    return out.sort_values("total_refs", ascending=False).reset_index(drop=True)


def classify_entities(df: pd.DataFrame, entity_col: str, period_col: str = "month_of", include_account: bool = False) -> dict:
    """Classify entities into Champions, Lowest Converting, Stopped, First-Time."""
    table = compute_entity_table(df, entity_col, period_col, include_account=include_account)
    periods = sorted(df[period_col].dropna().unique())
    group_cols = [entity_col, "PARTNER_ASSIGNMENT"] if include_account else [entity_col]

    champions = table[table["category"] == "Champion"].head(20)
    lowest = table[table["category"] == "Low Converting"].sort_values("pct_intake").head(20)

    # Stopped referring
    if len(periods) >= 2:
        curr_period, prev_period = periods[-1], periods[-2]
        prev_entities = set(df[df[period_col] == prev_period][entity_col].unique())
        curr_entities = set(df[df[period_col] == curr_period][entity_col].unique())
        stopped_names = prev_entities - curr_entities
        prev_df = df[df[period_col] == prev_period]
        stopped = (
            prev_df[prev_df[entity_col].isin(stopped_names)]
            .groupby(group_cols)
            .agg(prior_referrals=("REFERRAL_ID", "count"))
            .reset_index()
            .sort_values("prior_referrals", ascending=False)
        )
    else:
        stopped = pd.DataFrame()

    # First-time
    first_dates = df.groupby(group_cols)["REFERRAL_DATE"].min().reset_index()
    first_dates.columns = group_cols + ["first_referral_date"]
    if len(periods) >= 1:
        cutoff = pd.Period(periods[-1], freq="M").start_time if period_col == "month_of" else periods[-1]
        first_time = first_dates[first_dates["first_referral_date"] >= cutoff].sort_values(
            "first_referral_date", ascending=False
        )
    else:
        first_time = pd.DataFrame()

    return {
        "champions": champions,
        "lowest_converting": lowest,
        "stopped_referring": stopped,
        "first_time": first_time,
    }


def generate_summary(df: pd.DataFrame, period_col: str) -> str:
    """Generate a one-line summary sentence for the current period."""
    periods = sorted(df[period_col].dropna().unique())
    if len(periods) < 2:
        return ""

    is_weekly = period_col == "week_of"
    curr_period = periods[-2]  # last complete
    prev_period = periods[-3] if len(periods) >= 3 else None
    curr_df = df[df[period_col] == curr_period]
    m = compute_metrics(curr_df)

    # Format period name
    try:
        dt = pd.Timestamp(str(curr_period))
        if is_weekly:
            monday = dt - pd.Timedelta(days=dt.weekday())
            period_name = f"Week of {monday.strftime('%b %d')}"
        else:
            period_name = dt.strftime("%b %Y")
    except Exception:
        period_name = str(curr_period)

    parts = [f"<b>{period_name}</b>: {m['referrals']:,} referrals"]

    # Trend vs prior
    if prev_period is not None:
        prev_df = df[df[period_col] == prev_period]
        m_prev = compute_metrics(prev_df)
        if m_prev["referrals"] > 0:
            delta_pct = (m["referrals"] - m_prev["referrals"]) / m_prev["referrals"]
            parts.append(f"({delta_pct:+.0%} vs prior)")

    parts.append(f"from {m['unique_providers']:,} providers.")

    # Top account
    top_acct = curr_df.groupby("PARTNER_ASSIGNMENT")["REFERRAL_ID"].count().sort_values(ascending=False)
    if len(top_acct) > 0:
        top_name = top_acct.index[0]
        top_pct = top_acct.iloc[0] / m["referrals"]
        parts.append(f"{top_name} drove {top_pct:.0%} of volume.")

    # Biggest conversion mover
    if prev_period is not None and m_prev["referrals"] > 0:
        intake_delta = m["pct_intake"] - m_prev["pct_intake"]
        if abs(intake_delta) >= 0.02:
            direction = "up" if intake_delta > 0 else "down"
            parts.append(f"Intake rate {direction} {abs(intake_delta):.1%}pp.")

    return " ".join(parts)


def compute_retention(df: pd.DataFrame, partner_filter: str = None) -> pd.DataFrame:
    """Provider retention cohort analysis matching Snowflake source-of-truth logic.

    Key design decisions (aligned with SQL):
    - Exclude today's partial data (referral_date < today)
    - Provider key: REFERRING_PHYSICIAN — matches Snowflake retention SQL (which filters
      WHERE referring_physician IS NOT NULL on the raw name column before coalescing).
    - Therapy referrals are NYU-only and recent — excluded from CSV, no impact on historical cohorts.
    - Cohorts are per (REFERRING_PHYSICIAN, PARTNER_ASSIGNMENT) — same provider at two accounts = two cohort entries
    - First-ever referral month is the min referral date for that provider within that account
    - M1 = referred in exactly month M+1; M2 = M+2; etc.
    """
    today = pd.Timestamp.now().normalize()
    sub = df.copy()
    # Mirror SQL: referral_date < CURRENT_DATE() (exclude today's partial data)
    sub = sub[sub["REFERRAL_DATE"] < today]

    if partner_filter:
        sub = sub[sub["PARTNER_ASSIGNMENT"] == partner_filter]

    # Use REFERRING_PHYSICIAN (physician name) to match Snowflake retention SQL.
    # Note: Snowflake aliases COALESCE(NPI, physician) as "referring_physician" but filters
    # WHERE referring_physician IS NOT NULL on the raw name column — effectively the same
    # population as filtering on REFERRING_PHYSICIAN directly.
    # Therapy referrals are NYU-only and only started recently — no impact on historical cohorts.
    sub = sub[sub["REFERRING_PHYSICIAN"].notna() & (sub["REFERRING_PHYSICIAN"].astype(str).str.strip() != "")]
    sub["ref_month"] = sub["REFERRAL_DATE"].dt.to_period("M")

    # Group key: per physician × partner (matches Snowflake cohort scoping)
    group_key = ["REFERRING_PHYSICIAN", "PARTNER_ASSIGNMENT"]

    # First referral month per provider × partner
    first_ref = (
        sub.groupby(group_key)["ref_month"]
        .min()
        .reset_index()
        .rename(columns={"ref_month": "first_referral_month"})
    )

    # Set of active months per provider × partner (for retention check within same partner)
    provider_months = (
        sub.groupby(group_key)["ref_month"]
        .apply(set)
        .reset_index()
        .rename(columns={"ref_month": "active_months"})
    )

    cohort = first_ref.merge(provider_months, on=group_key)
    all_cohorts = sorted(cohort["first_referral_month"].unique())

    rows = []
    for cm in all_cohorts:
        cp = cohort[cohort["first_referral_month"] == cm]
        size = len(cp)
        row = {"Cohort": str(cm), "Cohort Size": size}
        for offset in range(1, 6):
            target = cm + offset
            if size == 0:
                # NaN instead of 0 so display layer can show "—" rather than
                # a misleading 0% that looks identical to "zero retained"
                row[f"M{offset}"] = float("nan")
            else:
                retained = cp["active_months"].apply(lambda s, t=target: t in s).sum()
                row[f"M{offset}"] = round(retained / size * 100, 1)
        rows.append(row)

    return pd.DataFrame(rows)
