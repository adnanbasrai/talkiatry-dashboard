import streamlit as st
import pandas as pd
import numpy as np
from data.transforms import count_unique_providers, _count_weekdays

CLINIC_ICON = "&#x1F3E5;"
LINE = "margin: 2px 0 2px 8px; font-size: 13px; color: #333;"
SECTION = "margin: 10px 0 4px 0; font-size: 14px; font-weight: 700; color: #1a1a2e; border-bottom: 1px solid rgba(0,0,0,0.1); padding-bottom: 3px;"


def render_action_plan(df, period_col):
    """Render prioritized clinic visit plan: P1, P2, P3."""
    periods = sorted(df[period_col].dropna().unique())
    if len(periods) < 2:
        st.info("Not enough data to generate an action plan.")
        return

    is_weekly = period_col == "week_of"
    curr_p = periods[-1]
    prev_p = periods[-2]

    curr = df[df[period_col] == curr_p]
    prev = df[df[period_col] == prev_p]
    all_prior = df[df[period_col] < curr_p]

    # Pacing factor for partial month/week
    today = pd.Timestamp.now().normalize()
    if not is_weekly:
        p_start = pd.Period(curr_p, freq="M").start_time
        p_end = pd.Period(curr_p, freq="M").end_time + pd.Timedelta(days=1)
    else:
        p_start = pd.Timestamp(curr_p)
        p_end = p_start + pd.Timedelta(days=5)
    wd_elapsed = max(_count_weekdays(p_start, today), 1)
    wd_total = max(_count_weekdays(p_start, p_end), 1)
    pace = wd_total / wd_elapsed

    # --- Build clinic signal table ---
    prev_agg = prev.groupby("REFERRING_CLINIC").agg(
        prev_refs=("REFERRAL_ID", "count"),
        prev_intake=("intake_started", "sum"),
        prev_provs=("provider_id", "nunique"),
    ).reset_index()
    prev_agg["prev_pct_intake"] = prev_agg["prev_intake"] / prev_agg["prev_refs"]

    curr_agg = curr.groupby("REFERRING_CLINIC").agg(
        curr_refs=("REFERRAL_ID", "count"),
        curr_intake=("intake_started", "sum"),
        curr_provs=("provider_id", "nunique"),
    ).reset_index()
    curr_agg["curr_pct_intake"] = curr_agg["curr_intake"] / curr_agg["curr_refs"]
    curr_agg["paced_refs"] = (curr_agg["curr_refs"] * pace).round(0).astype(int)

    # New clinics (never in prior data)
    prior_clinics = set(all_prior["REFERRING_CLINIC"].dropna())
    curr_agg["is_new_clinic"] = ~curr_agg["REFERRING_CLINIC"].isin(prior_clinics)

    # New provider clustering
    prior_provs = set(all_prior["provider_id"].dropna())
    new_prov_counts = []
    for clinic in curr["REFERRING_CLINIC"].dropna().unique():
        c_df = curr[curr["REFERRING_CLINIC"] == clinic]
        c_provs = set(c_df["provider_id"].dropna())
        new_prov_counts.append({"REFERRING_CLINIC": clinic, "new_provs": len(c_provs - prior_provs)})
    new_prov_df = pd.DataFrame(new_prov_counts) if new_prov_counts else pd.DataFrame(columns=["REFERRING_CLINIC", "new_provs"])

    # Provider concentration risk
    prov_conc = []
    for clinic in curr["REFERRING_CLINIC"].dropna().unique():
        c_df = curr[curr["REFERRING_CLINIC"] == clinic]
        if len(c_df) >= 5:
            top_prov_refs = c_df.groupby("provider_id")["REFERRAL_ID"].count().max()
            conc = top_prov_refs / len(c_df)
            prov_conc.append({"REFERRING_CLINIC": clinic, "concentration": conc})
    conc_df = pd.DataFrame(prov_conc) if prov_conc else pd.DataFrame(columns=["REFERRING_CLINIC", "concentration"])

    # Merge signals
    signals = curr_agg.merge(prev_agg, on="REFERRING_CLINIC", how="outer")
    signals = signals.merge(new_prov_df, on="REFERRING_CLINIC", how="left")
    signals = signals.merge(conc_df, on="REFERRING_CLINIC", how="left")
    for col in ["curr_refs", "prev_refs", "paced_refs", "new_provs"]:
        signals[col] = signals[col].fillna(0).astype(int)
    signals["concentration"] = signals["concentration"].fillna(0)

    # Volume change (paced)
    signals["vol_pct"] = np.where(
        signals["prev_refs"] > 0,
        (signals["paced_refs"] - signals["prev_refs"]) / signals["prev_refs"],
        0,
    )

    # Intake change (pp)
    signals["intake_pp"] = signals["curr_pct_intake"].fillna(0) - signals["prev_pct_intake"].fillna(0)

    # Silent (referred prev, zero now)
    signals["is_silent"] = (signals["prev_refs"] >= 5) & (signals["curr_refs"] == 0)

    # Get account and zip for each clinic
    acct_map = df.groupby("REFERRING_CLINIC")["PARTNER_ASSIGNMENT"].first().to_dict()
    zip_map = df.groupby("REFERRING_CLINIC")["REFERRING_CLINIC_ZIP"].first().to_dict()
    signals["account"] = signals["REFERRING_CLINIC"].map(acct_map)
    signals["zip"] = signals["REFERRING_CLINIC"].map(zip_map)

    # --- Score and prioritize ---
    scored = []
    for _, r in signals.iterrows():
        clinic = r["REFERRING_CLINIC"]
        reasons = []
        score = 0
        sentiment = "neutral"

        # POSITIVE signals
        if r["is_new_clinic"] and r["curr_refs"] >= 3:
            reasons.append(f"New clinic, {int(r['curr_refs'])} refs so far")
            score += 3
            sentiment = "green"

        if r["vol_pct"] > 0.5 and r["prev_refs"] >= 5:
            reasons.append(f"Volume surging {r['vol_pct']:+.0%} vs prior")
            score += 3
            sentiment = "green"

        if r["new_provs"] >= 3:
            reasons.append(f"{int(r['new_provs'])} new providers activating")
            score += 2
            sentiment = "green"

        # High-converting clinic — learn what's working
        curr_intake = r.get("curr_pct_intake", 0) or 0
        if curr_intake >= 0.55 and r["curr_refs"] >= 5:
            reasons.append(f"High intake conversion ({curr_intake:.0%}) — learn what they're doing right")
            score += 2
            sentiment = "green"

        # NEGATIVE signals
        if r["is_silent"]:
            reasons.append(f"Silent — had {int(r['prev_refs'])} refs last period, zero now")
            score += 4
            sentiment = "red"

        if r["vol_pct"] < -0.5 and r["prev_refs"] >= 5 and not r["is_silent"]:
            reasons.append(f"Volume dropped {r['vol_pct']:+.0%} vs prior")
            score += 3
            sentiment = "red"

        if r["intake_pp"] < -0.15 and r["curr_refs"] >= 5:
            reasons.append(f"Intake rate dropped {r['intake_pp']:+.0%}pp")
            score += 3
            sentiment = "red"

        # Chronically low intake — below 35% for both current and prior, min 5 refs both
        curr_intake = r.get("curr_pct_intake", 0) or 0
        prev_intake = r.get("prev_pct_intake", 0) or 0
        if curr_intake < 0.35 and prev_intake < 0.35 and r["curr_refs"] >= 5 and r["prev_refs"] >= 5:
            reasons.append(f"Persistently low intake — {curr_intake:.0%} this period, {prev_intake:.0%} last period")
            score += 2
            sentiment = "red"

        if r["concentration"] >= 0.8 and r["curr_refs"] >= 5:
            reasons.append(f"Single provider drives {r['concentration']:.0%} of refs — concentration risk")
            score += 1
            if sentiment == "neutral":
                sentiment = "red"

        if r["vol_pct"] > 1.0 and r["prev_refs"] >= 3:
            if sentiment != "red":
                reasons.append(f"Volume 2x+ vs prior")
                score += 2
                sentiment = "green"

        if reasons:
            scored.append({
                "clinic": clinic,
                "account": r.get("account", ""),
                "zip": r.get("zip", ""),
                "curr_refs": int(r["curr_refs"]),
                "paced_refs": int(r["paced_refs"]),
                "prev_refs": int(r["prev_refs"]),
                "reasons": reasons,
                "score": score,
                "sentiment": sentiment,
            })

    if not scored:
        st.info("No clinics flagged for visits this period.")
        return

    scored_df = pd.DataFrame(scored).sort_values("score", ascending=False)

    # Assign priorities
    p1 = scored_df[scored_df["score"] >= 4].head(3)
    remaining = scored_df[~scored_df.index.isin(p1.index)]
    p2 = remaining[remaining["score"] >= 2].head(3)
    remaining2 = remaining[~remaining.index.isin(p2.index)]
    p3 = remaining2.head(3)

    all_priority = pd.concat([
        p1.assign(priority="P1"),
        p2.assign(priority="P2"),
        p3.assign(priority="P3"),
    ])

    # --- Render ---
    st.markdown("### Clinic Visit Plan")

    for priority, label, items in [("P1", "Priority 1 — Visit This Week", p1),
                                    ("P2", "Priority 2 — Visit This Month", p2),
                                    ("P3", "Priority 3 — Monitor / Schedule", p3)]:
        if items.empty:
            continue

        lines = [f'<p style="{SECTION}">{label}</p>']
        for _, item in items.iterrows():
            color = "#155724" if item["sentiment"] == "green" else "#721c24"
            bg = "#d4edda" if item["sentiment"] == "green" else "#f8d7da"
            reason_text = " · ".join(item["reasons"])
            lines.append(
                f'<div style="background:{bg}; padding:6px 10px; border-radius:5px; margin:3px 0; font-size:13px;">'
                f'{CLINIC_ICON} <b style="color:{color}">{item["clinic"]}</b>'
                f' <span style="color:#666;">({item["account"]})</span>'
                f' — {item["curr_refs"]} refs (paced {item["paced_refs"]}), was {item["prev_refs"]} last period'
                f'<br><span style="color:{color}; font-size:12px;">{reason_text}</span>'
                f'</div>'
            )

        st.markdown("\n".join(lines), unsafe_allow_html=True)

    # --- Map of priority clinics ---
    _render_priority_map(all_priority)

    st.divider()


def _render_priority_map(priority_df):
    """Render a map showing all priority clinics color-coded by sentiment."""
    import pydeck as pdk
    from components.geo_map import geocode_zips

    if priority_df.empty:
        return

    zips = priority_df["zip"].dropna().unique().tolist()
    zips = [z for z in zips if z and str(z).strip()]
    if not zips:
        return

    geo = geocode_zips(zips)
    if geo.empty:
        return

    plot = priority_df.merge(geo, left_on="zip", right_on="zip", how="inner")
    if plot.empty:
        return

    # Offset clinics in the same zip so circles don't stack
    import math
    offset_distance = 0.003  # ~0.2 miles at NYC latitude
    zip_counts = plot.groupby("zip").cumcount()
    zip_totals = plot.groupby("zip")["zip"].transform("count")
    for idx in plot.index:
        n = int(zip_totals.loc[idx])
        if n > 1:
            i = int(zip_counts.loc[idx])
            angle = 2 * math.pi * i / n
            plot.loc[idx, "lat"] = plot.loc[idx, "lat"] + offset_distance * math.sin(angle)
            plot.loc[idx, "lng"] = plot.loc[idx, "lng"] + offset_distance * math.cos(angle)

    # Colors: green = positive, red = negative, size by priority
    plot["color_r"] = plot["sentiment"].map({"green": 40, "red": 200}).fillna(100).astype(int)
    plot["color_g"] = plot["sentiment"].map({"green": 167, "red": 50}).fillna(100).astype(int)
    plot["color_b"] = plot["sentiment"].map({"green": 70, "red": 50}).fillna(100).astype(int)
    plot["radius"] = plot["priority"].map({"P1": 500, "P2": 350, "P3": 250}).fillna(250).astype(int)
    plot["reason_text"] = plot["reasons"].apply(lambda r: " | ".join(r) if isinstance(r, list) else str(r))

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=plot,
        get_position=["lng", "lat"],
        get_radius="radius",
        get_fill_color=["color_r", "color_g", "color_b", 200],
        pickable=True,
        radius_min_pixels=8,
        radius_max_pixels=25,
    )

    center_lat = plot["lat"].mean()
    center_lng = plot["lng"].mean()
    view = pdk.ViewState(latitude=center_lat, longitude=center_lng, zoom=9, pitch=0)

    tooltip = {
        "html": (
            "<b>{clinic}</b> ({priority})<br>"
            "{account}<br>"
            "{curr_refs} refs (paced {paced_refs}), was {prev_refs}<br>"
            "{reason_text}"
        ),
        "style": {
            "backgroundColor": "white", "color": "#1A1A2E",
            "border": "1px solid #ddd", "borderRadius": "6px",
            "padding": "8px", "fontSize": "12px",
        },
    }

    deck = pdk.Deck(layers=[layer], initial_view_state=view, tooltip=tooltip, map_style="light")
    st.pydeck_chart(deck)
