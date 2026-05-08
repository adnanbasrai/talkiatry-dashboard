"""
account_insights.py
-------------------
Computes 2-4 key insights per account, each with specific clinic visit
recommendations driven by the account-level signal statuses from the
Account Signals table.

Signal → clinic mapping:
  refs_declining   — Refs/Day MoM < -10%     → clinic with biggest refs/day drop
  intake_low       — Ref→Intake < 55%         → clinic with worst intake rate
  intake_dropping  — Ref→Intake MoM < -3pp   → clinic with biggest intake rate drop
  booked_low       — Intake→Booked < 70%      → clinic with worst booked rate
  booked_dropping  — Intake→Booked MoM < -3pp → clinic with biggest booked rate drop
  m1_low           — M1 Retention < 35%       → clinic with most lost first-timers
  providers_stopped — providers active last period, silent now
  termination_spike — termination rate up ≥8pp
  volume_up        — Refs/Day up ≥20%         → top growth clinics (say thanks)
  new_clinic       — first referral in current period
  champion         — above-median volume and conversion

Period convention: curr = periods[-2] (last complete), prev = periods[-3] (prior).
All referrals (including terminated) are included in conversion denominators.
Provider names always come from REFERRING_PHYSICIAN (never NPI).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Literal
from data.transforms import last_complete_periods, _count_weekdays
from data.constants import (
    INTAKE_HEALTHY as _INTAKE_WATCH, INTAKE_WATCH as _INTAKE_AT_RISK,
    BOOKED_HEALTHY as _BOOKED_WATCH, BOOKED_WATCH as _BOOKED_AT_RISK,
    M1_STRONG as _M1_MODERATE, M1_MODERATE as _M1_LOW,
    TREND_DECLINING as _TREND_DECLINING, TREND_GROWING as _TREND_GROWING,
    MOM_DROP_PP as _MOM_DROP_PP, MIN_REFS as _MIN_REFS, MIN_COHORT as _MIN_COHORT,
)

Sentiment = Literal["negative", "warning", "positive"]


@dataclass
class InsightVisitClinic:
    clinic: str
    reason: str
    refs: int = 0
    providers: int = 0
    pct_booked: float = 0.0
    days_since: int | None = None
    zip_code: str | None = None
    provider_names: list[str] = field(default_factory=list)  # top referrers for map tooltip


@dataclass
class AccountInsight:
    type: str
    sentiment: Sentiment
    headline: str
    detail: str
    visit_action: str
    clinics: list[InsightVisitClinic] = field(default_factory=list)
    table_data: list[dict] = field(default_factory=list)
    full_table_data: list[dict] = field(default_factory=list)
    priority: int = 0



# ── Internal helpers ──────────────────────────────────────────────────────────

def _period_str(period, period_col: str) -> str:
    """Human-readable short label: 'Apr 2026' or 'wk of Apr 14'."""
    try:
        if period_col == "month_of":
            return pd.Period(str(period), freq="M").strftime("%b %Y")
        monday = pd.Timestamp(str(period))
        return f"wk of {monday.strftime('%b %-d')}"
    except Exception:
        return str(period)


def _wdays(period, period_col: str) -> int:
    """Number of business days in the period."""
    try:
        if period_col == "month_of":
            start = pd.Period(period, freq="M").start_time
            end   = pd.Period(period, freq="M").end_time.normalize() + pd.Timedelta(days=1)
        else:
            start = pd.Timestamp(period)
            end   = start + pd.Timedelta(days=7)
        return max(_count_weekdays(start, end), 1)
    except Exception:
        return 22


def _days_since(sub: pd.DataFrame) -> int | None:
    last = sub["REFERRAL_DATE"].max()
    if pd.isna(last):
        return None
    return int((pd.Timestamp.now().normalize() - last).days)


def _top_physicians(sub: pd.DataFrame, n: int = 5) -> list[str]:
    """Top-n physician names by referral count (REFERRING_PHYSICIAN column)."""
    if "REFERRING_PHYSICIAN" not in sub.columns:
        return []
    return (
        sub["REFERRING_PHYSICIAN"].dropna()
        .loc[lambda s: s.str.strip() != ""]
        .value_counts()
        .head(n)
        .index.tolist()
    )


def _top_physicians_any(sub: pd.DataFrame, n: int = 5) -> list[str]:
    """Like _top_physicians but falls back to REFERRING_PROVIDER then provider_id.
    Used for new clinics where a single referral may lack a REFERRING_PHYSICIAN value."""
    for col in ("REFERRING_PHYSICIAN", "REFERRING_PROVIDER", "provider_id"):
        if col not in sub.columns:
            continue
        names = (
            sub[col].dropna()
            .astype(str)
            .loc[lambda s: s.str.strip().ne("") & s.str.strip().ne("nan")]
            .value_counts()
            .head(n)
            .index.tolist()
        )
        if names:
            return names
    return []


def _clinic_zip(sub: pd.DataFrame) -> str | None:
    if "REFERRING_CLINIC_ZIP" not in sub.columns:
        return None
    mode = sub["REFERRING_CLINIC_ZIP"].dropna().mode()
    return str(mode.iloc[0]) if not mode.empty else None


def _build_visit_clinic(df: pd.DataFrame, clinic: str, reason: str,
                        provider_override=None) -> InsightVisitClinic:
    sub = df[df["REFERRING_CLINIC"] == clinic]
    n   = len(sub)
    return InsightVisitClinic(
        clinic=clinic,
        reason=reason,
        refs=n,
        providers=sub["provider_id"].dropna().nunique(),
        pct_booked=float(sub["visit_booked"].sum()) / n if n > 0 else 0.0,
        days_since=_days_since(sub),
        zip_code=_clinic_zip(sub),
        provider_names=(provider_override if provider_override is not None
                        else _top_physicians(sub)),
    )


def _clinic_agg(period_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate refs/intake/booked per clinic for a single period."""
    agg = period_df.groupby("REFERRING_CLINIC").agg(
        refs    =("REFERRAL_ID",    "count"),
        intake  =("intake_started", "sum"),
        booked  =("visit_booked",   "sum"),
    )
    agg["intake_rate"] = agg["intake"] / agg["refs"]
    agg["booked_rate"] = agg["booked"] / agg["refs"]   # % of total refs (matches Omni)
    return agg


# ── Public entry point ────────────────────────────────────────────────────────

def compute_account_insights(
    df: pd.DataFrame,
    period_col: str,
    max_insights: int = 4,
    df_full: pd.DataFrame | None = None,
) -> list[AccountInsight]:
    """Return up to max_insights AccountInsight objects for a single-account df slice."""
    if df.empty:
        return []

    periods = sorted(df[period_col].dropna().unique())
    if len(periods) < 2:
        return []

    # Use last-complete convention — same as signals table
    curr_period, prev_period, _ = last_complete_periods(periods, period_col)
    if curr_period is None:
        return []
    is_monthly  = period_col == "month_of"
    lbl         = "month" if is_monthly else "week"

    curr_df = df[df[period_col] == curr_period]
    prev_df = df[df[period_col] == prev_period] if prev_period else pd.DataFrame()

    curr_n = len(curr_df)
    prev_n = len(prev_df)

    c_wdays  = _wdays(curr_period, period_col)
    p_wdays  = _wdays(prev_period, period_col) if prev_period else 22
    curr_lbl = _period_str(curr_period, period_col)
    prev_lbl = _period_str(prev_period, period_col) if prev_period else "prior period"

    # ── Account-level metrics ─────────────────────────────────────────────────
    curr_rpd = curr_n / c_wdays
    prev_rpd = prev_n / p_wdays if prev_n > 0 else 0.0
    mom_pct  = (curr_rpd - prev_rpd) / prev_rpd if prev_rpd > 0 else None

    curr_intake = int(curr_df["intake_started"].sum())
    curr_booked = float(curr_df["visit_booked"].sum())
    prev_intake = int(prev_df["intake_started"].sum()) if not prev_df.empty else 0
    prev_booked = float(prev_df["visit_booked"].sum()) if not prev_df.empty else 0.0

    intake_rate      = curr_intake / curr_n if curr_n > 0 else None
    booked_rate      = curr_booked / curr_n if curr_n > 0 else None       # % of total refs (matches Omni)
    prev_intake_rate = prev_intake / prev_n if prev_n > 0 else None
    prev_booked_rate = prev_booked / prev_n if prev_n > 0 else None       # % of total refs (matches Omni)

    intake_mom = (intake_rate - prev_intake_rate
                  if intake_rate is not None and prev_intake_rate is not None else None)
    booked_mom = (booked_rate - prev_booked_rate
                  if booked_rate is not None and prev_booked_rate is not None else None)

    # Provider name lookup (id → name)
    id_to_physician: dict = {}
    if "REFERRING_PHYSICIAN" in df.columns and "provider_id" in df.columns:
        id_to_physician = (
            df.dropna(subset=["provider_id", "REFERRING_PHYSICIAN"])
            .groupby("provider_id")["REFERRING_PHYSICIAN"]
            .first().to_dict()
        )

    insights: list[AccountInsight] = []

    # ─────────────────────────────────────────────────────────────────────────
    # SIGNAL 1: Refs/Day declining
    # ─────────────────────────────────────────────────────────────────────────
    if (mom_pct is not None and mom_pct <= _TREND_DECLINING
            and prev_n >= _MIN_REFS and curr_n >= 1 and prev_period):

        curr_c = (curr_df.groupby("REFERRING_CLINIC")["REFERRAL_ID"].count() / c_wdays).rename("curr_rpd")
        prev_c = (prev_df.groupby("REFERRING_CLINIC")["REFERRAL_ID"].count() / p_wdays).rename("prev_rpd")
        rpd_df = pd.concat([curr_c, prev_c], axis=1).fillna(0)
        rpd_df["drop"] = rpd_df["prev_rpd"] - rpd_df["curr_rpd"]
        all_top = rpd_df[rpd_df["drop"] > 0].sort_values("prev_rpd", ascending=False).index.tolist()
        top = all_top[:3]

        clinics, all_table_rows = [], []
        for c in all_top:
            cc = curr_df[curr_df["REFERRING_CLINIC"] == c]
            pc = prev_df[prev_df["REFERRING_CLINIC"] == c]
            cr = len(cc) / c_wdays
            pr = len(pc) / p_wdays if len(pc) > 0 else 0.0
            pct_c = (cr - pr) / pr if pr > 0 else None
            pct_str = f"{pct_c:+.0%}" if pct_c is not None else "new"
            status_str = f"Refs/Day MoM: {pct_str}"
            clinics.append(_build_visit_clinic(
                df, c,
                f"⬇ {status_str} · Driving the account-level decline in referral rate",
                provider_override=_top_physicians(pc) or _top_physicians(cc),
            ))
            all_table_rows.append({
                "Clinic":              c,
                "Signal":              f"Refs/Day {pct_str}",
                "Key Providers to Visit":  " | ".join(_top_physicians(pc)) or "—",
                f"Refs ({curr_lbl})":  len(cc),
                f"Refs ({prev_lbl})":  len(pc),
                "Refs/Day Change":     pct_str,
            })
        table_rows = all_table_rows

        insights.append(AccountInsight(
            type="refs_declining", sentiment="negative",
            headline=f"Referrals/day down {abs(mom_pct):.0%} — {prev_n} refs in {prev_lbl} → {curr_n} in {curr_lbl}",
            detail=f"Rate fell from {prev_rpd:.1f}/day ({prev_lbl}) → {curr_rpd:.1f}/day ({curr_lbl}). Clinics below drove the largest drops.",
            visit_action="Visit these clinics to find out what changed — check for staff turnover, competing referrers, or referral friction.",
            clinics=clinics, table_data=table_rows[:3], full_table_data=all_table_rows, priority=10,
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # SIGNAL 2: Ref→Intake low
    # ─────────────────────────────────────────────────────────────────────────
    if intake_rate is not None and intake_rate < _INTAKE_WATCH and curr_n >= _MIN_REFS:

        agg = _clinic_agg(curr_df)
        valid = agg[agg["refs"] >= _MIN_COHORT]
        # Sort by intake rate ascending — worst offenders first
        all_top = valid["intake_rate"].sort_values(ascending=True).index.tolist()
        top = all_top[:3]

        clinics, all_table_rows = [], []
        for c in all_top:
            sub   = curr_df[curr_df["REFERRING_CLINIC"] == c]
            r     = agg.loc[c]
            rate  = r["intake_rate"] if not np.isnan(r["intake_rate"]) else 0.0
            status = "AT RISK" if rate < _INTAKE_AT_RISK else "WATCH"
            clinics.append(_build_visit_clinic(
                df, c,
                f"⬇ Ref→Intake {status} ({rate:.0%}) · Lowest intake conversion in this account",
            ))
            all_table_rows.append({
                "Clinic":              c,
                "Signal":              f"Ref→Intake {status}: {rate:.0%}",
                "Key Providers to Visit":  " | ".join(_top_physicians(sub)) or "—",
                f"Refs ({curr_lbl})":  int(r["refs"]),
                "Intake Started":      int(r["intake"]),
                "Ref→Intake":          f"{rate:.0%}",
                "Intake→Booked":       f"{r['booked_rate']:.0%}" if not np.isnan(r["booked_rate"]) else "—",
            })
        table_rows = all_table_rows

        sent   = "negative" if intake_rate < _INTAKE_AT_RISK else "warning"
        status = "AT RISK" if intake_rate < _INTAKE_AT_RISK else "WATCH"
        insights.append(AccountInsight(
            type="intake_low", sentiment=sent,
            headline=f"Ref→Intake {status} — {intake_rate:.0%} in {curr_lbl} (healthy ≥55%)",
            detail=(f"{curr_intake} of {curr_n} referrals started intake ({intake_rate:.0%}). "
                    f"Healthy ≥55% · Watch ≥45% · At Risk <45%."),
            visit_action="Re-educate providers on ideal patient fit criteria and intake steps — not enough referrals are reaching the intake stage.",
            clinics=clinics, table_data=table_rows[:3], full_table_data=all_table_rows, priority=9,
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # SIGNAL 3: Ref→Intake MoM declining
    # ─────────────────────────────────────────────────────────────────────────
    if (intake_mom is not None and intake_mom <= _MOM_DROP_PP
            and prev_n >= _MIN_REFS and curr_n >= _MIN_REFS and prev_period):

        curr_agg = _clinic_agg(curr_df)[["refs", "intake", "intake_rate"]]
        prev_agg = _clinic_agg(prev_df)[["intake_rate"]].rename(columns={"intake_rate": "prev_ir"})
        ir_df    = curr_agg.join(prev_agg, how="inner").dropna(subset=["intake_rate", "prev_ir"])
        ir_df    = ir_df[ir_df["refs"] >= _MIN_COHORT]
        ir_df["drop_pp"] = (ir_df["prev_ir"] - ir_df["intake_rate"]) * 100
        all_top = ir_df[ir_df["drop_pp"] > 0].sort_values("drop_pp", ascending=False).index.tolist()
        top = all_top[:3]

        clinics, all_table_rows = [], []
        for c in all_top:
            sub  = curr_df[curr_df["REFERRING_CLINIC"] == c]
            r    = ir_df.loc[c]
            drop = r["drop_pp"]
            clinics.append(_build_visit_clinic(
                df, c,
                f"⬇ Ref→Intake dropped {drop:.1f}pp vs {prev_lbl} · Biggest intake rate decline",
            ))
            all_table_rows.append({
                "Clinic":                       c,
                "Signal":                       f"Ref→Intake −{drop:.1f}pp",
                "Key Providers to Visit":           " | ".join(_top_physicians(sub)) or "—",
                f"Ref→Intake ({curr_lbl})":     f"{r['intake_rate']:.0%}",
                f"Ref→Intake ({prev_lbl})":     f"{r['prev_ir']:.0%}",
                "Change":                       f"−{drop:.1f}pp",
                f"Refs ({curr_lbl})":           int(r["refs"]),
            })
        table_rows = all_table_rows

        mom_pp = abs(intake_mom * 100)
        insights.append(AccountInsight(
            type="intake_dropping", sentiment="warning",
            headline=f"Ref→Intake dropped {mom_pp:.1f}pp — {prev_intake_rate:.0%} → {intake_rate:.0%}",
            detail=f"Fewer referrals are reaching intake in {curr_lbl} vs {prev_lbl}. Clinics below had the largest drops.",
            visit_action="Find out what changed in the referral handoff — check for new staff, workflow changes, or referral friction.",
            clinics=clinics, table_data=table_rows[:3], full_table_data=all_table_rows, priority=8,
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # SIGNAL 6: M1 Retention low (monthly only)
    # ─────────────────────────────────────────────────────────────────────────
    if is_monthly and prev_period and len(periods) >= 3:
        first_ref_period  = df.groupby("provider_id")[period_col].min()
        first_timers_prev = set(first_ref_period[first_ref_period == prev_period].index)

        if len(first_timers_prev) >= _MIN_COHORT:
            returned = set(curr_df["provider_id"].dropna().unique()) & first_timers_prev
            m1_rate  = len(returned) / len(first_timers_prev)

            if m1_rate < _M1_MODERATE:
                lost    = first_timers_prev - returned
                lost_df = prev_df[prev_df["provider_id"].isin(lost)]

                clinic_lost = (
                    lost_df.groupby("REFERRING_CLINIC")
                    .agg(lost_count=("provider_id", "nunique"), refs=("REFERRAL_ID", "count"))
                    .sort_values("lost_count", ascending=False)
                )
                all_top_m1 = clinic_lost.index.tolist()
                top = all_top_m1[:3]

                clinics, all_table_rows = [], []
                for c in all_top_m1:
                    prov_ids = lost_df[lost_df["REFERRING_CLINIC"] == c]["provider_id"].dropna().unique()
                    names = [id_to_physician.get(p, str(p)) for p in prov_ids]
                    names = [n for n in names if n and n.lower() not in ("nan", "none", "")]
                    clinics.append(_build_visit_clinic(
                        df, c,
                        f"⬇ {int(clinic_lost.loc[c,'lost_count'])} first-time provider(s) from {prev_lbl} didn't return in {curr_lbl}",
                        provider_override=names[:5],
                    ))
                    all_table_rows.append({
                        "Clinic":                      c,
                        "Signal":                      f"M1: {int(clinic_lost.loc[c,'lost_count'])} providers lapsed",
                        "Key Providers to Visit":  " | ".join(names[:3]) or "—",
                        "Providers Who Didn't Return":  int(clinic_lost.loc[c, "lost_count"]),
                        "Their Refs Last Period":       int(clinic_lost.loc[c, "refs"]),
                    })
                table_rows = all_table_rows

                status = "LOW" if m1_rate < _M1_LOW else "MODERATE"
                sent   = "negative" if m1_rate < _M1_LOW else "warning"
                insights.append(AccountInsight(
                    type="m1_low", sentiment=sent,
                    headline=f"M1 Retention {status} — only {m1_rate:.0%} of first-time providers came back",
                    detail=(f"{len(first_timers_prev)} providers referred for the first time in {prev_lbl}. "
                            f"Only {len(returned)} ({m1_rate:.0%}) referred again in {curr_lbl}. "
                            f"Strong ≥35% · Moderate ≥25% · Low <25%."),
                    visit_action="Re-engage lapsed first-time providers — the habit window is closing and these relationships haven't yet become sticky.",
                    clinics=clinics, table_data=table_rows[:3], full_table_data=all_table_rows, priority=8,
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # SIGNAL 7: Providers stopped (active last period, silent now)
    # ─────────────────────────────────────────────────────────────────────────
    if prev_period and not prev_df.empty:
        prev_provs = set(prev_df["provider_id"].dropna().unique())
        curr_provs = set(curr_df["provider_id"].dropna().unique())
        stopped    = prev_provs - curr_provs

        if len(stopped) >= 2:
            stopped_df    = prev_df[prev_df["provider_id"].isin(stopped)]
            clinic_counts = (
                stopped_df.groupby("REFERRING_CLINIC")
                .agg(n_stopped=("provider_id", "nunique"), prev_refs=("REFERRAL_ID", "count"))
                .sort_values("n_stopped", ascending=False)
            )
            all_clinics = clinic_counts.index.tolist()

            clinic_physicians: dict[str, list[str]] = {}
            for c in all_clinics:
                prov_ids = stopped_df[stopped_df["REFERRING_CLINIC"] == c]["provider_id"].dropna().unique()
                names    = [id_to_physician.get(p, str(p)) for p in prov_ids]
                clinic_physicians[c] = [n for n in names if n and n.lower() not in ("nan", "none", "")]

            clinics = [
                _build_visit_clinic(
                    df, c,
                    f"⬇ {int(clinic_counts.loc[c,'n_stopped'])} provider(s) active in {prev_lbl}, silent since",
                    provider_override=clinic_physicians.get(c, []),
                )
                for c in all_clinics
            ]

            # Table shows ALL stopped providers across ALL clinics (sorted by clinic priority)
            all_clinics_sorted = all_clinics
            table_rows = []
            for c in all_clinics_sorted:
                prov_ids = stopped_df[stopped_df["REFERRING_CLINIC"] == c]["provider_id"].dropna().unique()
                for pid in prov_ids:
                    name    = id_to_physician.get(pid, str(pid))
                    prov_df = stopped_df[(stopped_df["REFERRING_CLINIC"] == c) &
                                         (stopped_df["provider_id"] == pid)]
                    table_rows.append({
                        "Clinic":                   c,
                        "Provider to Visit":   name,
                        f"Refs in {prev_lbl}":      len(prov_df),
                        "Last Referral":            f"{_days_since(prov_df)}d ago" if _days_since(prov_df) else "—",
                    })
            table_rows.sort(key=lambda r: r.get(f"Refs in {prev_lbl}", 0), reverse=True)

            n_clinics = len(clinic_counts)
            insights.append(AccountInsight(
                type="providers_stopped", sentiment="negative",
                headline=f"{len(stopped)} provider{'s' if len(stopped)>1 else ''} active in {prev_lbl}, silent now",
                detail=(f"They generated {len(stopped_df)} referrals in {prev_lbl} and have referred 0 in {curr_lbl}. "
                        f"Spread across {n_clinics} clinic{'s' if n_clinics>1 else ''} — all shown in table and map below."),
                visit_action="Re-engage these providers before they become permanently lapsed — ask what changed.",
                clinics=clinics, table_data=table_rows, full_table_data=table_rows, priority=9,
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # SIGNAL 8: Termination spike
    # ─────────────────────────────────────────────────────────────────────────
    if "TERMINATION_REASON" in df.columns and prev_n >= _MIN_REFS and curr_n >= _MIN_REFS:
        curr_tr = curr_df["TERMINATION_REASON"].notna().sum() / curr_n
        prev_tr = prev_df["TERMINATION_REASON"].notna().sum() / prev_n if prev_n else 0.0
        spike   = curr_tr - prev_tr

        if spike >= 0.08 and curr_tr >= 0.10:
            top_reason = (curr_df["TERMINATION_REASON"].dropna().value_counts().index[0]
                          if curr_df["TERMINATION_REASON"].notna().any() else "unknown")
            term_by_clinic = (
                curr_df[curr_df["TERMINATION_REASON"].notna()]
                .groupby("REFERRING_CLINIC")["REFERRAL_ID"].count()
                .sort_values(ascending=False)
            )
            all_top = term_by_clinic.index.tolist()
            top = all_top[:3]

            clinics = [_build_visit_clinic(
                df, c,
                f"⚠ {int(term_by_clinic.get(c,0))} terminated referrals — "
                f"{curr_df[curr_df['REFERRING_CLINIC']==c]['TERMINATION_REASON'].notna().mean():.0%} rate",
            ) for c in all_top]

            all_table_rows = []
            for c in all_top:
                sub      = curr_df[curr_df["REFERRING_CLINIC"] == c]
                term_sub = sub[sub["TERMINATION_REASON"].notna()]
                all_table_rows.append({
                    "Clinic":              c,
                    "Key Providers to Visit":  " | ".join(_top_physicians(term_sub)) or "—",
                    "Terminated":          len(term_sub),
                    "Termination Rate":    f"{len(term_sub)/len(sub):.0%}" if len(sub) else "—",
                    "Top Reason":          (term_sub["TERMINATION_REASON"].value_counts().index[0]
                                           if not term_sub.empty else "—"),
                })
            table_rows = all_table_rows

            insights.append(AccountInsight(
                type="termination_spike", sentiment="warning",
                headline=f"Termination rate up {spike:.0%} — providers sending wrong patients",
                detail=f"Rate rose from {prev_tr:.0%} ({prev_lbl}) to {curr_tr:.0%} ({curr_lbl}). Top reason: {top_reason}.",
                visit_action="Re-educate providers on patient fit criteria — too many referrals are being screened out post-intake.",
                clinics=clinics, table_data=table_rows[:3], full_table_data=all_table_rows, priority=7,
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # POSITIVE 1: Volume growth
    # ─────────────────────────────────────────────────────────────────────────
    if (mom_pct is not None and mom_pct >= _TREND_GROWING
            and prev_n >= _MIN_REFS and prev_period):

        curr_c = (curr_df.groupby("REFERRING_CLINIC")["REFERRAL_ID"].count() / c_wdays).rename("curr_rpd")
        prev_c = (prev_df.groupby("REFERRING_CLINIC")["REFERRAL_ID"].count() / p_wdays).rename("prev_rpd")
        rpd_df = pd.concat([curr_c, prev_c], axis=1).fillna(0)
        rpd_df["gain"] = rpd_df["curr_rpd"] - rpd_df["prev_rpd"]
        all_top = rpd_df[rpd_df["gain"] > 0].sort_values("gain", ascending=False).index.tolist()
        top = all_top[:3]

        clinics, all_table_rows = [], []
        for c in all_top:
            cc  = curr_df[curr_df["REFERRING_CLINIC"] == c]
            pc  = prev_df[prev_df["REFERRING_CLINIC"] == c]
            cr  = len(cc) / c_wdays
            pr  = len(pc) / p_wdays if len(pc) > 0 else 0.0
            pct_c   = (cr - pr) / pr if pr > 0 else None
            pct_str = f"{pct_c:+.0%}" if pct_c is not None else "new"
            i_sum = int(cc["intake_started"].sum())
            b_sum = float(cc["visit_booked"].sum())
            clinics.append(_build_visit_clinic(
                df, c, f"⬆ Refs/day {pct_str} vs {prev_lbl} — say thanks",
            ))
            all_table_rows.append({
                "Clinic":              c,
                "Key Providers to Visit":  " | ".join(_top_physicians(cc)) or "—",
                f"Refs ({curr_lbl})":  len(cc),
                f"Refs ({prev_lbl})":  len(pc),
                "Refs/Day Change":     pct_str,
                "Intake→Booked":       f"{b_sum/i_sum:.0%}" if i_sum > 0 else "—",
            })
        table_rows = all_table_rows

        insights.append(AccountInsight(
            type="volume_up", sentiment="positive",
            headline=f"Strong growth — refs/day up {mom_pct:.0%} vs {prev_lbl}",
            detail=f"{prev_n} refs in {prev_lbl} → {curr_n} in {curr_lbl} ({curr_rpd:.1f}/day).",
            visit_action="Visit top growth clinics to thank them and learn what's working — replicate it across the account.",
            clinics=clinics, table_data=table_rows[:3], full_table_data=all_table_rows, priority=5,
        ))

    # ─────────────────────────────────────────────────────────────────────────
    # POSITIVE 2: New clinics
    # ─────────────────────────────────────────────────────────────────────────
    try:
        cutoff = (pd.Period(curr_period, freq="M").start_time if is_monthly
                  else pd.Timestamp(curr_period))
    except Exception:
        cutoff = None

    if cutoff is not None:
        # Use full unfiltered dataset to check true first-ever referral date —
        # avoids falsely flagging clinics whose pre-date-range history is hidden by the filter.
        ref_source  = df_full if df_full is not None else df
        first_ref   = ref_source.groupby("REFERRING_CLINIC")["REFERRAL_DATE"].min()
        new_clinics = first_ref[first_ref >= cutoff].index.tolist()
        # Restrict to clinics actually present in the current account/period slice
        new_clinics = [c for c in new_clinics if c in curr_df["REFERRING_CLINIC"].values]

        if new_clinics:
            clinics = [_build_visit_clinic(df, c, "First-time referrer — visit to welcome and set expectations")
                       for c in new_clinics]
            all_table_rows = []
            for c in new_clinics:  # ALL new clinics
                sub = curr_df[curr_df["REFERRING_CLINIC"] == c]
                i   = int(sub["intake_started"].sum())
                b   = float(sub["visit_booked"].sum())
                all_table_rows.append({
                    "Clinic":          c,
                    "Key Providers to Visit": " | ".join(_top_physicians_any(sub)) or "—",
                    "Refs":            len(sub),
                    "Ref→Intake":      f"{i/len(sub):.0%}" if len(sub) > 0 else "—",
                    "Intake→Booked":   f"{b/i:.0%}" if i > 0 else "—",
                    "First Referral":  sub["REFERRAL_DATE"].min().strftime("%b %d") if not sub.empty else "—",
                })
            table_rows = all_table_rows

            insights.append(AccountInsight(
                type="new_clinic", sentiment="positive",
                headline=f"{len(new_clinics)} new clinic{'s' if len(new_clinics)>1 else ''} referred for the first time",
                detail=f"First referral{'s' if len(new_clinics)>1 else ''} received in {curr_lbl}.",
                visit_action="Visit new clinics early to build the relationship before it goes cold.",
                clinics=clinics, table_data=table_rows[:3], full_table_data=all_table_rows, priority=4,
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # POSITIVE 3: Champions
    # ─────────────────────────────────────────────────────────────────────────
    if curr_n >= 10:
        agg    = _clinic_agg(curr_df)
        agg    = agg[agg["refs"] >= 3].dropna(subset=["booked_rate"])
        med_r  = agg["refs"].median()
        med_br = agg["booked_rate"].median()
        all_champs = agg[
            (agg["refs"] >= med_r) & (agg["booked_rate"] >= med_br)
        ].sort_values("refs", ascending=False)
        champs = all_champs.head(3)  # top 3 for map/headline count

        if not champs.empty:
            all_top = all_champs.index.tolist()
            clinics = [_build_visit_clinic(df, c,
                        "Champion — above-median volume and booking rate · visit to thank and deepen")
                       for c in all_top]
            all_table_rows = []
            for c in all_top:
                sub = curr_df[curr_df["REFERRING_CLINIC"] == c]
                r   = all_champs.loc[c]
                all_table_rows.append({
                    "Clinic":          c,
                    "Key Providers to Visit": " | ".join(_top_physicians(sub)) or "—",
                    "Refs":            int(r["refs"]),
                    "Ref→Intake":      f"{r['intake_rate']:.0%}",
                    "Intake→Booked":   f"{r['booked_rate']:.0%}",
                    "Last Referral":   f"{_days_since(sub)}d ago" if _days_since(sub) else "—",
                })
            table_rows = all_table_rows

            insights.append(AccountInsight(
                type="champion", sentiment="positive",
                headline=f"{len(all_top)} champion clinic{'s' if len(all_top)>1 else ''} driving volume and conversion",
                detail=f"Above-median referral volume and booking rate in {curr_lbl}.",
                visit_action="Stop by to say thanks — champions who feel recognized refer more.",
                clinics=clinics, table_data=table_rows[:3], full_table_data=all_table_rows, priority=3,
            ))

    insights.sort(key=lambda i: -i.priority)
    return insights[:max_insights]
