"""
account_signals_table.py
------------------------
Shared components for the account-level signals view.
Used by both the Market Health tab (all accounts) and the My Team tab (PPM portfolio).

Public functions:
  render_account_callout(df, period_col)   — one-line summary bar above the table
  render_account_signals_table(df, period_col) — full signals table with toggle
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
from functools import partial

from data.transforms import compute_account_signals_table, last_complete_periods
from data.constants import INTAKE_HEALTHY, INTAKE_WATCH, BOOKED_HEALTHY, BOOKED_WATCH, M1_STRONG, M1_MODERATE

# ── Colour palette ────────────────────────────────────────────────────────────
_STATUS_BG: dict[str, str] = {
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
_STATUS_FG: dict[str, str] = {
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


# ── Formatters ────────────────────────────────────────────────────────────────
def _fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:.1%}"


def _fmt_signed_pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1%}"


def _fmt_pp(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    pp = v * 100
    sign = "+" if pp >= 0 else ""
    return f"{sign}{pp:.1f}pp"


def _fmt_days(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{int(v)}d"


# ── Period label helpers ──────────────────────────────────────────────────────
def _period_label(period, period_col: str) -> str:
    """Human-readable short label for a period value."""
    try:
        if period_col == "month_of":
            return pd.Period(str(period), freq="M").strftime("%B %Y")
        else:
            monday = pd.Timestamp(str(period))
            return f"week of {monday.strftime('%b %-d')}"
    except Exception:
        return str(period)


# ── Styler helpers ────────────────────────────────────────────────────────────
def _style_status(val: str) -> str:
    bg = _STATUS_BG.get(str(val), "")
    fg = _STATUS_FG.get(str(val), "#333333")
    if bg:
        return f"background-color:{bg};color:{fg};font-weight:600;"
    return "color:#aaaaaa;"


def _style_signed(val: str) -> str:
    if not isinstance(val, str) or val == "—":
        return "color:#aaaaaa;"
    if val.startswith("+"):
        return "color:#2E7D32;font-weight:600;"
    if val.startswith("-"):
        return "color:#C62828;font-weight:600;"
    return ""


def _style_abs_threshold(val: str, healthy: float, watch: float) -> str:
    """Color a formatted percentage value green/yellow/red against absolute thresholds."""
    if not isinstance(val, str) or val in ("—", ""):
        return "color:#aaaaaa;"
    try:
        v = float(val.strip('%')) / 100
    except Exception:
        return ""
    if v >= healthy:
        return "color:#2E7D32;font-weight:600;"
    if v >= watch:
        return "color:#F57F17;font-weight:600;"
    return "color:#C62828;font-weight:600;"


# ── Callout bar ──────────────────────────────────────────────────────────────
def render_account_callout(df: pd.DataFrame, period_col: str):
    """One-line summary comparing the last two COMPLETE periods.
    Shows: most-recently-silent account · biggest grower · biggest decliner.
    Filters to accounts active within the last 60 days with meaningful volume.
    """
    periods = sorted(df[period_col].dropna().unique())
    curr_period, prev_period, _ = last_complete_periods(periods, period_col)
    if curr_period is None or prev_period is None:
        return

    try:
        curr_lbl = _period_label(curr_period, period_col)
        prev_lbl = _period_label(prev_period, period_col)
    except Exception:
        curr_lbl, prev_lbl = str(curr_period), str(prev_period)

    curr_counts = df[df[period_col] == curr_period].groupby("PARTNER_ASSIGNMENT")["REFERRAL_ID"].count()
    prev_counts = df[df[period_col] == prev_period].groupby("PARTNER_ASSIGNMENT")["REFERRAL_ID"].count()
    trend = ((curr_counts - prev_counts) / prev_counts.replace(0, float("nan"))).dropna()

    today = pd.Timestamp.now().normalize()
    last_ref = df.groupby("PARTNER_ASSIGNMENT")["REFERRAL_DATE"].max()
    days_silent = (today - last_ref).dt.days
    recently_active = days_silent[days_silent <= 60]

    parts = []

    # Most silent (active ≤60d, ≥5 refs in last complete period)
    vol_mask = curr_counts.reindex(recently_active.index).fillna(0) >= 5
    silent_candidates = recently_active[vol_mask].sort_values(ascending=False)
    if not silent_candidates.empty:
        acct = silent_candidates.index[0]
        parts.append(f"<b>{acct}</b> has been silent {int(silent_candidates.iloc[0])}d")

    # Biggest grower (min 10 refs in prior period)
    vol_ok = prev_counts[prev_counts >= 10].index
    growers = trend.reindex(vol_ok).dropna().sort_values(ascending=False)
    if not growers.empty and growers.iloc[0] > 0:
        acct = growers.index[0]
        parts.append(f"<b>{acct}</b> up {growers.iloc[0]:+.0%} ({prev_lbl}→{curr_lbl})")

    # Biggest decliner (min 10 refs in prior period)
    decliners = trend.reindex(vol_ok).dropna().sort_values()
    if not decliners.empty and decliners.iloc[0] < -0.15:
        acct = decliners.index[0]
        parts.append(f"<b>{acct}</b> down {decliners.iloc[0]:+.0%} ({prev_lbl}→{curr_lbl})")

    if parts:
        st.markdown(
            '<div style="background-color:#f5f7fa;padding:8px 14px;border-radius:6px;font-size:13px;">'
            + " · ".join(parts) + "</div>",
            unsafe_allow_html=True,
        )


# ── Public entry point ────────────────────────────────────────────────────────
def render_account_signals_table(df: pd.DataFrame, period_col: str, toggle_key: str = "acct_signals_toggle", rank_df=None):
    sig = compute_account_signals_table(df, period_col, rank_df=rank_df)
    if sig.empty:
        st.info("Not enough periods of data to compute account signals.")
        return

    is_monthly = period_col == "month_of"

    # ── Resolve period labels for tooltip text ────────────────────────────────
    periods = sorted(df[period_col].dropna().unique())
    curr_p, prev_p, prev2_p = last_complete_periods(periods, period_col)
    curr_lbl  = _period_label(curr_p,  period_col) if curr_p  else "current period"
    prev_lbl  = _period_label(prev_p,  period_col) if prev_p  else "prior period"
    prev2_lbl = _period_label(prev2_p, period_col) if prev2_p else "two periods ago"

    # ── Toggle ────────────────────────────────────────────────────────────────
    view_mode = st.pills(
        "View mode",
        options=["Status", "Metric"],
        default="Status",
        selection_mode="single",
        key=toggle_key,
        label_visibility="collapsed",
    )
    if view_mode is None:
        view_mode = "Status"

    # ── Build display DataFrame ───────────────────────────────────────────────
    disp = pd.DataFrame()
    disp["Account"]     = sig["PARTNER_ASSIGNMENT"]
    disp["PPM"]         = sig["PPM"]
    disp["Referrals"]   = sig["total_refs"].apply(lambda x: f"{int(x):,}")
    disp["Days Silent"] = sig["days_silent"].apply(_fmt_days)

    if view_mode == "Metric":
        disp["Refs/Day MoM"]       = sig["mom_pct"].apply(_fmt_signed_pct)
        disp["Ref→Intake"]         = sig["intake_rate"].apply(_fmt_pct)
        disp["Ref→Booked"]      = sig["booked_rate"].apply(_fmt_pct)
        disp["Ref→Intake MoM"]     = sig["intake_mom"].apply(_fmt_pp)
        disp["Ref→Booked MoM"]  = sig["booked_mom"].apply(_fmt_pp)
        if is_monthly:
            disp["M1 Retention"]   = sig["m1_rate"].apply(_fmt_pct)
            disp["M1 MoM"]         = sig["m1_mom"].apply(_fmt_pp)
    else:
        disp["Refs/Day MoM"]       = sig["trend_status"]
        disp["Ref→Intake"]         = sig["intake_status"]
        disp["Ref→Booked"]      = sig["booked_status"]
        disp["Ref→Intake MoM"]     = sig["intake_mom_status"]
        disp["Ref→Booked MoM"]  = sig["booked_mom_status"]
        if is_monthly:
            disp["M1 Retention"]   = sig["m1_status"]
            disp["M1 MoM"]         = sig["m1_mom_status"]

    signal_cols = [
        "Refs/Day MoM", "Ref→Intake", "Ref→Booked",
        "Ref→Intake MoM", "Ref→Booked MoM",
    ]
    if is_monthly:
        signal_cols += ["M1 Retention", "M1 MoM"]

    # ── Apply styling ─────────────────────────────────────────────────────────
    if view_mode == "Status":
        styled = disp.style.applymap(_style_status, subset=signal_cols)
    else:
        delta_cols = ["Refs/Day MoM", "Ref→Intake MoM", "Ref→Booked MoM"]
        if is_monthly:
            delta_cols.append("M1 MoM")
        styled = disp.style.applymap(_style_signed, subset=delta_cols)
        # Color absolute metric columns by threshold
        styled = styled.applymap(
            partial(_style_abs_threshold, healthy=INTAKE_HEALTHY, watch=INTAKE_WATCH),
            subset=["Ref→Intake"],
        ).applymap(
            partial(_style_abs_threshold, healthy=BOOKED_HEALTHY, watch=BOOKED_WATCH),
            subset=["Ref→Booked"],
        )
        if is_monthly:
            styled = styled.applymap(
                partial(_style_abs_threshold, healthy=M1_STRONG, watch=M1_MODERATE),
                subset=["M1 Retention"],
            )

    # ── Column tooltips ───────────────────────────────────────────────────────
    col_cfg = {
        "Account":     st.column_config.TextColumn("Account"),
        "PPM":         st.column_config.TextColumn("PPM"),
        "Referrals":   st.column_config.TextColumn(
            "Referrals",
            help="Total referrals from this account across the full selected date range.",
        ),
        "Days Silent": st.column_config.TextColumn(
            "Days Silent",
            help="Days since the most recent referral from this account.",
        ),
        "Refs/Day MoM": st.column_config.TextColumn(
            "Refs/Day MoM",
            help=(
                f"% change in referrals per working day from {prev_lbl} to {curr_lbl}. "
                f"Ranked relative to all accounts — top 20% = Strong, bottom 20% = At Risk."
            ),
        ),
        "Ref→Intake": st.column_config.TextColumn(
            "Ref→Intake",
            help=(
                f"% of {curr_lbl} referrals that started intake. "
                f"Healthy ≥55% · Watch ≥45% · At Risk <45%."
            ),
        ),
        "Ref→Booked": st.column_config.TextColumn(
            "Ref→Booked",
            help=(
                f"% of {curr_lbl} referrals that booked a visit (visit_booked ÷ total refs). "
                f"Healthy ≥35% · Watch ≥25% · At Risk <25%."
            ),
        ),
        "Ref→Intake MoM": st.column_config.TextColumn(
            "Ref→Intake MoM",
            help=(
                f"Percentage-point change in Ref→Intake rate from {prev_lbl} to {curr_lbl}. "
                f"Ranked relative to all accounts."
            ),
        ),
        "Ref→Booked MoM": st.column_config.TextColumn(
            "Ref→Booked MoM",
            help=(
                f"Percentage-point change in % Visit Booked (of total refs) from {prev_lbl} to {curr_lbl}. "
                f"Ranked relative to all accounts."
            ),
        ),
    }

    if is_monthly:
        col_cfg["M1 Retention"] = st.column_config.TextColumn(
            "M1 Retention",
            help=(
                f"% of providers who referred for the first time in {prev_lbl} "
                f"who came back and referred again in {curr_lbl}. "
                f"Strong ≥35% · Moderate ≥25% · Low <25%."
            ),
        )
        col_cfg["M1 MoM"] = st.column_config.TextColumn(
            "M1 MoM",
            help=(
                f"Percentage-point change in M1 retention comparing the {prev_lbl} cohort "
                f"vs the {prev2_lbl} cohort. Ranked relative to all accounts."
            ),
        )

    st.markdown(
        '<div style="background:#f0f4fa;border-left:3px solid #4A90D9;border-radius:4px;'
        'padding:8px 12px;margin-bottom:8px;font-size:11px;color:#444;">'
        '<b>How to read this table:</b> '
        'Status labels for MoM columns (Refs/Day MoM, Ref→Intake MoM, etc.) are assigned by '
        '<b>percentile rank within the region</b> — an account can have a technically positive '
        'change and still show <b>Flat</b> if most peers grew faster. '
        '<b>— (dash)</b> means the account had fewer than 5 referrals in that period, '
        'which is below the minimum threshold for reliable metrics.'
        '</div>',
        unsafe_allow_html=True,
    )
    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config=col_cfg,
        height=min(60 + len(disp) * 35, 620),
    )

    notes = [
        f"Refs/Day MoM: % change in refs per working day, {prev_lbl} → {curr_lbl}, ranked across accounts",
        f"Ref→Intake: intake starters ÷ total referrals in {curr_lbl} · ≥55% Healthy · ≥45% Watch · &lt;45% At Risk",
        f"Ref→Booked: visits booked ÷ total referrals in {curr_lbl} · ≥35% Healthy · ≥25% Watch · &lt;25% At Risk",
        "MoM Δ: percentage-point change vs prior period, ranked across accounts",
    ]
    if is_monthly:
        notes.append(
            f"M1: % of {prev_lbl} first-time providers who referred again in {curr_lbl} · ≥35% Strong · ≥25% Moderate · &lt;25% Low"
        )
    st.markdown(
        f'<span style="font-size:10px;color:#999;">{len(disp)} accounts &nbsp;·&nbsp; '
        + " &nbsp;·&nbsp; ".join(notes) + "</span>",
        unsafe_allow_html=True,
    )
