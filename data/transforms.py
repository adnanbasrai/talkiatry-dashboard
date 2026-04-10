import pandas as pd
import numpy as np


def compute_metrics(df: pd.DataFrame) -> dict:
    """Compute KPI metrics for a given slice of data."""
    n = len(df)
    if n == 0:
        return {k: 0 for k in ["referrals", "unique_providers", "pct_intake", "pct_booked", "pct_completed"]}
    physicians = df["REFERRING_PHYSICIAN"].dropna()
    physicians = physicians[physicians.str.strip() != ""]
    return {
        "referrals": n,
        "unique_providers": physicians.nunique(),
        "pct_intake": df["intake_started"].sum() / n,
        "pct_booked": df["visit_booked"].sum() / n,
        "pct_completed": df["visit_completed"].sum() / n,
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
    """Build a ranking table for clinics or providers with trend."""
    group_cols = [entity_col, "PARTNER_ASSIGNMENT"] if include_account else [entity_col]
    agg = df.groupby(group_cols).agg(
        referrals=("REFERRAL_ID", "count"),
        intake_started=("intake_started", "sum"),
        visit_booked=("visit_booked", "sum"),
        visit_completed=("visit_completed", "sum"),
    ).reset_index()
    agg["pct_intake"] = (agg["intake_started"] / agg["referrals"]).fillna(0)
    agg["pct_booked"] = (agg["visit_booked"] / agg["referrals"]).fillna(0)
    agg["pct_completed"] = (agg["visit_completed"] / agg["referrals"]).fillna(0)

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

    return agg.sort_values("referrals", ascending=False)


def classify_entities(df: pd.DataFrame, entity_col: str, period_col: str = "month_of", include_account: bool = False) -> dict:
    """Classify entities into Champions, Lowest Converting, Stopped, First-Time."""
    table = compute_entity_table(df, entity_col, period_col, include_account=include_account)
    periods = sorted(df[period_col].dropna().unique())
    group_cols = [entity_col, "PARTNER_ASSIGNMENT"] if include_account else [entity_col]

    # Champions: high volume + high conversion
    qualified = table[table["referrals"] >= 5]
    if len(qualified) > 0:
        med_vol = qualified["referrals"].median()
        med_conv = qualified["pct_booked"].median()
        champions = qualified[
            (qualified["referrals"] >= med_vol) & (qualified["pct_booked"] >= med_conv)
        ].head(20)
    else:
        champions = pd.DataFrame()

    # Lowest converting: enough volume but low conversion
    if len(qualified) > 0:
        p25 = qualified["pct_booked"].quantile(0.25)
        lowest = qualified[qualified["pct_booked"] <= p25].sort_values("pct_booked").head(20)
    else:
        lowest = pd.DataFrame()

    # Stopped referring: active in prior period, zero in current
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

    # First-time referrers: first referral within the data's date range
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


def compute_retention(df: pd.DataFrame, partner_filter: str = None) -> pd.DataFrame:
    """Provider retention cohort analysis using REFERRING_PHYSICIAN."""
    sub = df.copy()
    if partner_filter:
        sub = sub[sub["PARTNER_ASSIGNMENT"] == partner_filter]

    sub = sub[sub["REFERRING_PHYSICIAN"].notna() & (sub["REFERRING_PHYSICIAN"].str.strip() != "")]
    sub["ref_month"] = sub["REFERRAL_DATE"].dt.to_period("M")

    # First referral month per physician
    first_ref = sub.groupby("REFERRING_PHYSICIAN")["ref_month"].min().reset_index()
    first_ref.columns = ["REFERRING_PHYSICIAN", "first_referral_month"]

    # Active months per physician
    provider_months = sub.groupby("REFERRING_PHYSICIAN")["ref_month"].apply(set).reset_index()
    provider_months.columns = ["REFERRING_PHYSICIAN", "active_months"]

    cohort = first_ref.merge(provider_months, on="REFERRING_PHYSICIAN")
    all_cohorts = sorted(cohort["first_referral_month"].unique())

    rows = []
    for cm in all_cohorts:
        cp = cohort[cohort["first_referral_month"] == cm]
        size = len(cp)
        row = {"Cohort": str(cm), "Cohort Size": size}
        for offset in range(6):
            target = cm + offset
            retained = cp["active_months"].apply(lambda s: target in s).sum()
            row[f"M{offset}"] = round(retained / size * 100, 1) if size > 0 else 0
        rows.append(row)

    return pd.DataFrame(rows)
