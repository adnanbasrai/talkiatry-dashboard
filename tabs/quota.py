import streamlit as st
import pandas as pd
from data.transforms import count_unique_providers, wdays as _wdays
from data.quotas import QUOTA_PERIODS, ACTIVE_QUOTA_PERIOD

# ── Load active quota period config ───────────────────────────────────────────
period_cfg = QUOTA_PERIODS[ACTIVE_QUOTA_PERIOD]
Q2_START   = period_cfg["start"]
Q2_END     = period_cfg["end"]
Q2_MONTHS  = list(pd.period_range(Q2_START, Q2_END, freq="M"))
Q2_QUOTAS  = period_cfg["targets"]

MONTH_LABELS = {m: m.strftime("%B") + f" (M{i+1})" for i, m in enumerate(Q2_MONTHS)}


@st.cache_data
def _quarter_wday_fractions() -> dict:
    """
    Returns a dict with:
      total_wdays  : int   — total Q2 working days
      month_wdays  : dict  — {Period → int}
      month_frac   : dict  — {Period → float}  (fraction of Q2 working days)
    """
    q_wdays = _wdays(Q2_START, Q2_END)
    mw, mf = {}, {}
    for m in Q2_MONTHS:
        m_start = m.start_time
        m_end   = m.end_time.normalize()
        w = _wdays(m_start, m_end)
        mw[m] = w
        mf[m] = w / q_wdays
    return {"total_wdays": q_wdays, "month_wdays": mw, "month_frac": mf}


# ── Colour helpers ─────────────────────────────────────────────────────────────

def _pct_color(pct: float) -> str:
    if pct >= 1.0:
        return "#2E7D32"
    if pct >= 0.75:
        return "#F57F17"
    return "#C62828"


def _fmt_cell(actual: int, quota: int, pct: float) -> str:
    color = _pct_color(pct)
    return (
        f'<span style="font-weight:600;">{actual:,}</span>'
        f'<span style="color:#888;font-size:11px;"> / {quota:,}</span>'
        f' <span style="color:{color};font-weight:700;">{pct:.0%}</span>'
    )


# ── Main render ────────────────────────────────────────────────────────────────

@st.fragment
def render(df):
    st.subheader(f"{period_cfg['label']} Quota Attainment")

    fracs = _quarter_wday_fractions()
    q_wdays = fracs["total_wdays"]
    month_wdays = fracs["month_wdays"]
    month_frac  = fracs["month_frac"]

    # ── Period selector ────────────────────────────────────────────────────────
    month_options = [MONTH_LABELS[m] for m in Q2_MONTHS]
    options = ["Full Quarter"] + month_options
    period_sel = st.segmented_control(
        "View period",
        options=options,
        default="Full Quarter",
        key="quota_period_sel",
        label_visibility="collapsed",
    )
    if period_sel is None:
        period_sel = "Full Quarter"

    # Map selection → month period (None = full quarter)
    label_to_month = {MONTH_LABELS[m]: m for m in Q2_MONTHS}
    sel_month = label_to_month.get(period_sel, None)

    # ── Quota scaling note ─────────────────────────────────────────────────────
    label = period_cfg["label"]
    if sel_month is not None:
        frac   = month_frac[sel_month]
        m_wday = month_wdays[sel_month]
        note = (
            f"Monthly quota = full-quarter quota × ({m_wday} working days in {sel_month.strftime('%B')} "
            f"÷ {q_wdays} {label} working days) = <b>{frac:.1%}</b> of {label} quota."
        )
    else:
        note = (
            f"Full {label} quota. {label} has <b>{q_wdays} working days</b>. "
            "Switch to a monthly view to see proportional targets."
        )

    st.markdown(
        f'<div style="background-color:#e8f4fd;padding:8px 14px;border-radius:6px;'
        f'font-size:13px;border-left:4px solid #4A90D9;margin-bottom:10px;">'
        f'{note}</div>',
        unsafe_allow_html=True,
    )

    # ── Filter data ────────────────────────────────────────────────────────────
    q2 = df[(df["REFERRAL_DATE"] >= Q2_START) & (df["REFERRAL_DATE"] <= Q2_END)]
    if q2.empty:
        st.warning(f"No {label} data available yet.")
        return

    region_ppms = set(df["PPM"].dropna().unique())

    rows = []
    for ppm, targets in Q2_QUOTAS.items():
        if ppm not in region_ppms:
            continue

        ppm_q2  = q2[q2["PPM"] == ppm]

        if sel_month is not None:
            # ── Single month view ──────────────────────────────────────────────
            ppm_df = ppm_q2[ppm_q2["month_of"] == sel_month]
            frac   = month_frac[sel_month]

            ref_quota   = round(targets["referrals"] * frac)
            prov_quota  = round(targets["providers"] * frac)
            visit_quota = round(targets["visits"]    * frac)

            actual_refs   = len(ppm_df)
            actual_provs  = count_unique_providers(ppm_df["provider_id"]) if not ppm_df.empty else 0
            actual_visits = int(ppm_df["visit_booked"].sum())
        else:
            # ── Full quarter view ──────────────────────────────────────────────
            ppm_df = ppm_q2

            ref_quota   = targets["referrals"]
            prov_quota  = targets["providers"]
            visit_quota = targets["visits"]

            actual_refs = len(ppm_df)
            actual_provs = 0
            for m in Q2_MONTHS:
                month_df = ppm_df[ppm_df["month_of"] == m]
                if not month_df.empty:
                    actual_provs += count_unique_providers(month_df["provider_id"])
            actual_visits = int(ppm_df["visit_booked"].sum())

        rows.append({
            "PPM":          ppm,
            "Refs Actual":  actual_refs,
            "Refs Quota":   ref_quota,
            "Refs %":       actual_refs  / ref_quota   if ref_quota   > 0 else 0,
            "Provs Actual": actual_provs,
            "Provs Quota":  prov_quota,
            "Provs %":      actual_provs / prov_quota  if prov_quota  > 0 else 0,
            "Visits Actual":actual_visits,
            "Visits Quota": visit_quota,
            "Visits %":     actual_visits/ visit_quota if visit_quota > 0 else 0,
        })

    if not rows:
        st.info("No PPMs found for this region.")
        return

    result = pd.DataFrame(rows)

    # ── Display ────────────────────────────────────────────────────────────────
    display = result.copy()
    display["Providers"] = display.apply(
        lambda r: f"{int(r['Provs Actual']):,} / {int(r['Provs Quota']):,} ({r['Provs %']:.0%})", axis=1)
    display["Referrals"] = display.apply(
        lambda r: f"{int(r['Refs Actual']):,} / {int(r['Refs Quota']):,} ({r['Refs %']:.0%})", axis=1)
    display["Visits"] = display.apply(
        lambda r: f"{int(r['Visits Actual']):,} / {int(r['Visits Quota']):,} ({r['Visits %']:.0%})", axis=1)

    def _style_pct(val, raw_col):
        pct = result.loc[result["PPM"] == val.name, raw_col].values
        if len(pct) == 0:
            return ""
        return f"color: {_pct_color(float(pct[0]))}; font-weight: 700;"

    # ── Determine whether the selected period is fully complete ──────────────
    today = pd.Timestamp.now().normalize()
    if sel_month is not None:
        # Complete if today is past the last day of that month
        is_complete = today > sel_month.end_time.normalize()
    else:
        # Full quarter is complete only after June 30
        is_complete = today > Q2_END

    # Build styled dataframe
    show = display[["PPM", "Providers", "Referrals", "Visits"]].reset_index(drop=True)

    def _style_row(row):
        if not is_complete:
            return [""] * len(row)
        styles = [""] * len(row)
        ppm = row["PPM"]
        r = result[result["PPM"] == ppm]
        if r.empty:
            return styles
        for i, pct_col in enumerate(["Provs %", "Refs %", "Visits %"], start=1):
            pct = float(r[pct_col].iloc[0])
            styles[i] = f"color: {_pct_color(pct)}; font-weight: 600;"
        return styles

    styled = show.style.apply(_style_row, axis=1)

    st.dataframe(styled, use_container_width=True, hide_index=True)

    if sel_month is None:
        st.caption(
            f"Full {label} progress. Unique providers are counted monthly "
            f"(a provider referring in multiple months counts once per month). "
            f"{label} ends {Q2_END.strftime('%B %-d, %Y')}."
        )
    else:
        st.caption(
            f"{sel_month.strftime('%B %Y')} actuals vs proportional monthly target "
            f"({month_wdays[sel_month]} of {q_wdays} {label} working days = "
            f"{month_frac[sel_month]:.1%} of {label} quota)."
        )
