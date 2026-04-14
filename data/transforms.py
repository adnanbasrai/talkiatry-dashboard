import pandas as pd
import numpy as np


def count_unique_providers(series: pd.Series) -> int:
    """Count unique provider_ids. Null/blank counts as 1 distinct provider if any exist."""
    non_null = series.dropna()
    count = non_null.nunique()
    if series.isna().any():
        count += 1
    return count


def compute_metrics(df: pd.DataFrame) -> dict:
    """Compute KPI metrics for a given slice of data."""
    n = len(df)
    if n == 0:
        return {k: 0 for k in ["referrals", "unique_providers", "pct_intake", "pct_booked", "pct_completed"]}
    return {
        "referrals": n,
        "unique_providers": count_unique_providers(df["provider_id"]),
        "pct_intake": df["intake_started"].sum() / n,
        "pct_booked": df["visit_booked"].sum() / n,
        "pct_completed": df["visit_completed"].sum() / n,
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
    """Aggregate metrics by time period (month_of or week_of)."""
    grouped = df.groupby(period_col).agg(
        referrals=("REFERRAL_ID", "count"),
        intake_started=("intake_started", "sum"),
        visit_booked=("visit_booked", "sum"),
        visit_completed=("visit_completed", "sum"),
    ).reset_index()
    grouped["pct_intake"] = grouped["intake_started"] / grouped["referrals"]
    grouped["pct_booked"] = grouped["visit_booked"] / grouped["referrals"]
    grouped["pct_completed"] = grouped["visit_completed"] / grouped["referrals"]
    grouped[period_col] = grouped[period_col].astype(str)
    return grouped.sort_values(period_col)


def compute_entity_table(df: pd.DataFrame, entity_col: str, period_col: str = "month_of", include_account: bool = False) -> pd.DataFrame:
    """Build a ranking table for clinics or providers with trend and days since last referral."""
    group_cols = [entity_col, "PARTNER_ASSIGNMENT"] if include_account else [entity_col]
    agg = df.groupby(group_cols).agg(
        referrals=("REFERRAL_ID", "count"),
        intake_started=("intake_started", "sum"),
        visit_booked=("visit_booked", "sum"),
        visit_completed=("visit_completed", "sum"),
        last_referral_date=("REFERRAL_DATE", "max"),
    ).reset_index()
    agg["pct_intake"] = (agg["intake_started"] / agg["referrals"]).fillna(0)
    agg["pct_booked"] = (agg["visit_booked"] / agg["referrals"]).fillna(0)
    agg["pct_completed"] = (agg["visit_completed"] / agg["referrals"]).fillna(0)

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
    """Provider retention cohort analysis using REFERRING_PHYSICIAN."""
    sub = df.copy()
    if partner_filter:
        sub = sub[sub["PARTNER_ASSIGNMENT"] == partner_filter]

    sub = sub[sub["REFERRING_PHYSICIAN"].notna() & (sub["REFERRING_PHYSICIAN"].str.strip() != "")]
    sub["ref_month"] = sub["REFERRAL_DATE"].dt.to_period("M")

    first_ref = sub.groupby("REFERRING_PHYSICIAN")["ref_month"].min().reset_index()
    first_ref.columns = ["REFERRING_PHYSICIAN", "first_referral_month"]

    provider_months = sub.groupby("REFERRING_PHYSICIAN")["ref_month"].apply(set).reset_index()
    provider_months.columns = ["REFERRING_PHYSICIAN", "active_months"]

    cohort = first_ref.merge(provider_months, on="REFERRING_PHYSICIAN")
    all_cohorts = sorted(cohort["first_referral_month"].unique())

    rows = []
    for cm in all_cohorts:
        cp = cohort[cohort["first_referral_month"] == cm]
        size = len(cp)
        row = {"Cohort": str(cm), "Cohort Size": size}
        for offset in range(1, 6):
            target = cm + offset
            retained = cp["active_months"].apply(lambda s: target in s).sum()
            row[f"M{offset}"] = round(retained / size * 100, 1) if size > 0 else 0
        rows.append(row)

    return pd.DataFrame(rows)
