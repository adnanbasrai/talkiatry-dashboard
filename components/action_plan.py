"""
action_plan.py
--------------
Insight-driven action plan renderer.

Layout:
  • Compact account pill-toggles (multi-select, all on by default)
  • Left column  — insight cards for each visible account
  • Right column — single combined map of all recommended visit clinics

Map colour coding:
  Red   = negative/warning visit (fix something)
  Green = positive visit (reinforce something)
"""
from __future__ import annotations

import base64
import math
import streamlit as st
import pandas as pd
import pydeck as pdk

from components.account_insights import compute_account_insights, AccountInsight
from components.geo_map import geocode_zips
from data.transforms import compute_entity_table
from components.pdf_export import generate_clinic_status_report, generate_provider_status_report


# Bump this any time PDF generation code changes to invalidate cached PDFs
_PDF_VERSION = 2

@st.cache_data(show_spinner=False)
def _cached_clinic_pdf(df_full, clinic_name, _version=_PDF_VERSION):
    return generate_clinic_status_report(df_full, clinic_name)


@st.cache_data(show_spinner=False)
def _cached_provider_pdf(df_full, provider_name, _version=_PDF_VERSION):
    return generate_provider_status_report(df_full, provider_name)

# ── Sentiment styling ─────────────────────────────────────────────────────────
_SENTIMENT = {
    "negative": {"border": "#dc3545", "bg": "#fff5f5", "icon": "🔴", "badge": "background:#dc3545;color:white;"},
    "warning":  {"border": "#f5a623", "bg": "#fffbf0", "icon": "🟡", "badge": "background:#f5a623;color:white;"},
    "positive": {"border": "#27AE60", "bg": "#f0faf4", "icon": "🟢", "badge": "background:#27AE60;color:white;"},
}

_TYPE_LABEL = {
    # Negative / warning signals
    "refs_declining":    "Refs/Day Declining",
    "intake_low":        "Ref→Intake Low",
    "intake_dropping":   "Ref→Intake Dropping",
    "booked_low":        "Intake→Booked Low",
    "booked_dropping":   "Intake→Booked Dropping",
    "m1_low":            "M1 Retention Low",
    "providers_stopped": "Providers Silent",
    "termination_spike": "Termination Spike",
    # Positive signals
    "volume_up":         "Volume Growth",
    "new_clinic":        "New Clinic",
    "champion":          "Champion",
    # Legacy (kept for backwards compat)
    "volume_drop":       "Volume Drop",
    "conversion_drop":   "Conversion Drop",
}

_MAP_COLOR = {
    "negative": [220, 53,  69,  220],
    "warning":  [245, 166, 35,  220],
    "positive": [39,  174, 96,  220],
}


# ── Public entry point ────────────────────────────────────────────────────────
def render_action_plan(df: pd.DataFrame, period_col: str, chase_df=None, df_full=None):
    if df.empty:
        st.info("No referral data available.")
        return

    acct_volumes = (
        df.groupby("PARTNER_ASSIGNMENT")["REFERRAL_ID"]
        .count()
        .sort_values(ascending=False)
    )
    all_accounts = acct_volumes.index.tolist()

    st.markdown("### Account Insights & Visit Recommendations")
    st.caption(
        "2–4 key signals per account. Negative/warning signals shown first. "
        "Volume comparisons are pacing-adjusted for in-flight periods."
    )

    # ── Compact account pill toggles ──────────────────────────────────────────
    ppm_key = df["PPM"].iloc[0] if "PPM" in df.columns and not df.empty else "all"
    pills_key = f"acct_pills_{ppm_key}"

    selected_accounts = st.pills(
        "Show accounts",
        options=all_accounts,
        selection_mode="multi",
        default=all_accounts,
        key=pills_key,
        label_visibility="collapsed",
    )

    if not selected_accounts:
        st.caption("No accounts selected — click a pill above to show insights.")
        return

    # ── Pre-compute insights for all selected accounts ────────────────────────
    account_insights: dict[str, list[AccountInsight]] = {}
    for acct in selected_accounts:
        acct_df = df[df["PARTNER_ASSIGNMENT"] == acct]
        account_insights[acct] = compute_account_insights(acct_df, period_col, max_insights=4)

    # ── List / Map view toggle ────────────────────────────────────────────────
    view_key = f"insight_view_{ppm_key}"
    if view_key not in st.session_state:
        st.session_state[view_key] = "List View"

    toggle_col, _ = st.columns([1, 3])
    with toggle_col:
        view_mode = st.segmented_control(
            "View",
            options=["List View", "Map View"],
            key=view_key,
            label_visibility="collapsed",
        )

    # ── List View ─────────────────────────────────────────────────────────────
    if view_mode == "List View":
        rendered_any = False
        for acct in selected_accounts:
            insights   = account_insights[acct]
            if not insights:
                continue
            total_refs = acct_volumes[acct]
            n_neg = sum(1 for i in insights if i.sentiment in ("negative", "warning"))
            n_pos = sum(1 for i in insights if i.sentiment == "positive")

            with st.container(border=True):
                st.markdown(
                    f'<div style="font-size:14px;font-weight:700;margin-bottom:1px;">{acct}</div>'
                    f'<div style="font-size:11px;color:#888;margin-bottom:6px;">'
                    f'{total_refs:,} referrals'
                    + (f' · <span style="color:#dc3545;font-weight:600">{n_neg} action needed</span>' if n_neg else "")
                    + (f' · <span style="color:#27AE60;font-weight:600">{n_pos} positive</span>'       if n_pos else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
                _render_insight_cards(insights, idx=list(selected_accounts).index(acct), df_full=df_full)
            rendered_any = True

        if not rendered_any:
            st.caption("No accounts with enough data to generate insights.")

    # ── Map View ──────────────────────────────────────────────────────────────
    else:
        total_insights = sum(len(v) for v in account_insights.values())
        map_height = max(600, total_insights * 60 + len(selected_accounts) * 40)
        _render_combined_map(account_insights, height=map_height)


# ── HTML table with embedded <a download> links ───────────────────────────────
def _render_insight_table_html(display_data: list[dict], ins, df_full):
    """Render insight rows as an HTML table so <a download> links work in-cell."""
    if not display_data:
        return

    _safe_fn = lambda s: str(s).replace(" ", "_").replace("/", "-")[:40]
    col_names = list(display_data[0].keys())

    # Pre-generate PDFs for every row up front
    row_pdfs = []
    for row in display_data:
        clinic   = row.get("Clinic", "")
        raw_prov = row.get("Provider to Visit") or row.get("Key Providers to Visit", "")
        provider = raw_prov.split(",")[0].strip() if raw_prov else ""
        c_b64, p_b64 = "", ""
        if df_full is not None:
            if clinic:
                pdf = _cached_clinic_pdf(df_full, clinic)
                if pdf:
                    c_b64 = base64.b64encode(pdf).decode()
            if provider:
                pdf = _cached_provider_pdf(df_full, provider)
                if pdf:
                    p_b64 = base64.b64encode(pdf).decode()
        row_pdfs.append((clinic, provider, c_b64, p_b64))

    # Build HTML
    th = "padding:6px 10px;text-align:left;font-size:13px;font-weight:700;color:#555;border-bottom:2px solid #dee2e6;background:#f8f9fa;white-space:nowrap;"
    th_dl = "padding:6px 10px;text-align:left;font-size:13px;font-weight:700;color:#555;border-bottom:2px solid #dee2e6;background:#f8f9fa;white-space:normal;width:90px;"
    td = "padding:5px 10px;font-size:13px;color:#1A1A2E;border-bottom:1px solid #f0f0f0;vertical-align:middle;"
    td_dl = "padding:5px 8px;border-bottom:1px solid #f0f0f0;vertical-align:middle;text-align:center;white-space:nowrap;"
    link_style = ("display:inline-block;font-size:14px;text-decoration:none;"
                  "padding:2px 6px;border-radius:4px;border:1px solid #dee2e6;"
                  "background:#fff;margin:0 2px;line-height:1.4;")

    rows_html = ""
    for row, (clinic, provider, c_b64, p_b64) in zip(display_data, row_pdfs):
        cells = "".join(
            f'<td style="{td}">{row.get(c, "")}</td>' for c in col_names
        )
        c_link = (f'<a href="data:application/pdf;base64,{c_b64}" '
                  f'download="{_safe_fn(clinic)}_clinic_report.pdf" '
                  f'title="Clinic Report: {clinic}" style="{link_style}">🏥</a>'
                  if c_b64 else "")
        p_link = (f'<a href="data:application/pdf;base64,{p_b64}" '
                  f'download="{_safe_fn(provider)}_provider_report.pdf" '
                  f'title="Provider Report: {provider}" style="{link_style}">👤</a>'
                  if p_b64 else "")
        rows_html += f'<tr>{cells}<td style="{td_dl}">{c_link}{p_link}</td></tr>'

    headers = "".join(f'<th style="{th}">{c}</th>' for c in col_names)
    headers += f'<th style="{th_dl}">Download Referral Status Reports</th>'

    html = (
        '<div style="overflow-x:auto;">'
        '<table style="border-collapse:collapse;width:100%;font-size:11px;">'
        f'<thead><tr>{headers}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        '</table></div>'
    )
    st.markdown(html, unsafe_allow_html=True)


# ── Insight cards ─────────────────────────────────────────────────────────────
def _render_insight_cards(insights: list[AccountInsight], idx: int = 0, df_full=None):
    for idx, ins in enumerate(insights):
        style   = _SENTIMENT[ins.sentiment]
        border  = style["border"]
        bg      = style["bg"]
        icon    = style["icon"]
        badge_s = style["badge"]
        label   = _TYPE_LABEL.get(ins.type, ins.type.replace("_", " ").title())

        st.markdown(
            f'<div style="background:{bg};border-left:4px solid {border};'
            f'border-radius:6px;padding:10px 14px;margin-bottom:4px;">'
            f'<span style="{badge_s}padding:2px 7px;border-radius:3px;'
            f'font-size:10px;font-weight:700;letter-spacing:.05em;">{label}</span>'
            f'<div style="font-size:13px;font-weight:600;margin:5px 0 2px;">{icon} {ins.headline}</div>'
            f'<div style="font-size:11px;color:#555;margin-bottom:5px;">{ins.detail}</div>'
            f'<div style="font-size:11px;font-weight:600;color:{border};">📋 {ins.visit_action}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if ins.table_data:
            full_data = ins.full_table_data if ins.full_table_data else ins.table_data
            preview_data = ins.table_data  # top 3
            n_preview_clinics = len({r.get("Clinic", "") for r in preview_data})
            n_total_clinics   = len({r.get("Clinic", "") for r in full_data})

            expander_label = f"View {n_preview_clinics} clinic{'s' if n_preview_clinics != 1 else ''}"
            if n_total_clinics > n_preview_clinics:
                expander_label = f"View top {n_preview_clinics} of {n_total_clinics} clinics"

            with st.expander(expander_label, expanded=False):
                # Unique session state key per insight instance
                expand_key = f"_show_all_{ins.type}_{idx}"
                show_all = st.session_state.get(expand_key, False)

                display_data = full_data if show_all else preview_data
                _render_insight_table_html(display_data, ins, df_full)

                if n_total_clinics > n_preview_clinics:
                    if not show_all:
                        if st.button(
                            f"View all {n_total_clinics} clinics",
                            key=f"btn_{expand_key}",
                            use_container_width=True,
                        ):
                            st.session_state[expand_key] = True
                            st.rerun()
                    else:
                        if st.button(
                            f"Show top {n_preview_clinics} only",
                            key=f"btn_{expand_key}",
                            use_container_width=True,
                        ):
                            st.session_state[expand_key] = False
                            st.rerun()


# ── Clinic signals ────────────────────────────────────────────────────────────

_SIGNAL_META = {
    "Stopped":        {"icon": "🔴", "label": "Stopped",         "priority": 4, "color": "#dc3545"},
    "Low Converting": {"icon": "🟡", "label": "Low Converting",  "priority": 3, "color": "#f5a623"},
    "New":            {"icon": "🔵", "label": "New This Period",  "priority": 2, "color": "#4A90D9"},
    "Champion":       {"icon": "🟢", "label": "Champion",        "priority": 1, "color": "#27AE60"},
}


def _render_clinic_signals(df: pd.DataFrame, period_col: str):
    st.markdown("#### Clinic Signals")
    st.caption(
        "Clinic-level signals across all selected accounts, sorted by urgency. "
        "Stopped = referred last period, silent this period. "
        "Low Converting = bottom-quartile booking rate (≥5 refs). "
        "Champion = above-median volume and booking rate."
    )

    if df.empty:
        st.info("No data.")
        return

    table = compute_entity_table(df, "REFERRING_CLINIC", period_col, include_account=True)

    # Keep only clinics with a recognised signal
    signals = table[table["category"].isin(_SIGNAL_META)].copy()
    if signals.empty:
        st.caption("No clinic-level signals detected for the selected accounts.")
        return

    # Sort by signal priority, then volume
    signals["_priority"] = signals["category"].map(lambda c: _SIGNAL_META[c]["priority"])
    signals = signals.sort_values(["_priority", "referrals"], ascending=[False, False])

    # Build display dataframe
    periods = sorted(df[period_col].dropna().unique())
    curr_period = periods[-1] if periods else None
    prev_period = periods[-2] if len(periods) >= 2 else None

    rows = []
    for _, r in signals.iterrows():
        meta = _SIGNAL_META[r["category"]]
        clinic_df  = df[df["REFERRING_CLINIC"] == r["REFERRING_CLINIC"]]

        # Top physicians by referral count
        phys = ""
        if "REFERRING_PHYSICIAN" in clinic_df.columns:
            top = (
                clinic_df["REFERRING_PHYSICIAN"].dropna()
                .loc[lambda s: s.str.strip() != ""]
                .value_counts().head(3).index.tolist()
            )
            phys = ", ".join(top)

        # Current-period refs (for Stopped, show prior-period refs)
        if r["category"] == "Stopped" and prev_period:
            period_refs = len(df[(df["REFERRING_CLINIC"] == r["REFERRING_CLINIC"]) &
                                  (df[period_col] == prev_period)])
            refs_label = f"{period_refs} last period → 0"
        elif curr_period:
            period_refs = len(df[(df["REFERRING_CLINIC"] == r["REFERRING_CLINIC"]) &
                                  (df[period_col] == curr_period)])
            refs_label = str(period_refs)
        else:
            refs_label = str(r["referrals"])

        trend_str = ""
        if pd.notna(r.get("trend")):
            trend_str = f"{r['trend']:+.0%}"

        days = int(r["days_since_last"]) if pd.notna(r.get("days_since_last")) else None
        days_str = f"{days}d ago" if days is not None else "—"

        rows.append({
            "Signal":          f"{meta['icon']} {meta['label']}",
            "Clinic":          r["REFERRING_CLINIC"],
            "Account":         r.get("PARTNER_ASSIGNMENT", ""),
            "Provider(s)":     phys or "—",
            "Refs":            refs_label,
            "vs Prior":        trend_str or "—",
            "% Booked":        f"{r['pct_booked']:.0%}" if r.get("pct_booked") else "—",
            "Last referral":   days_str,
        })

    display_df = pd.DataFrame(rows)

    # Signal filter pills
    all_signals = list(_SIGNAL_META.keys())
    present_signals = [s for s in all_signals if any(
        f"{_SIGNAL_META[s]['icon']} {_SIGNAL_META[s]['label']}" in r["Signal"] for r in rows
    )]

    sig_filter = st.pills(
        "Filter signals",
        options=present_signals,
        selection_mode="multi",
        default=present_signals,
        key=f"clinic_sig_filter_{period_col}",
        label_visibility="collapsed",
    )

    if sig_filter:
        keep_labels = {f"{_SIGNAL_META[s]['icon']} {_SIGNAL_META[s]['label']}" for s in sig_filter}
        display_df = display_df[display_df["Signal"].isin(keep_labels)]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Signal":        st.column_config.TextColumn("Signal",       width="small"),
            "Clinic":        st.column_config.TextColumn("Clinic",       width="medium"),
            "Account":       st.column_config.TextColumn("Account",      width="medium"),
            "Provider(s)":   st.column_config.TextColumn("Provider(s)",  width="large"),
            "Refs":          st.column_config.TextColumn("Refs",         width="small"),
            "vs Prior":      st.column_config.TextColumn("vs Prior",     width="small"),
            "% Booked":      st.column_config.TextColumn("% Booked",     width="small"),
            "Last referral": st.column_config.TextColumn("Last referral",width="small"),
        },
        height=min(60 + len(display_df) * 35, 500),
    )

    st.caption(f"{len(display_df)} clinic signal{'s' if len(display_df) != 1 else ''} shown.")


# ── Combined visit map ────────────────────────────────────────────────────────
def _render_combined_map(account_insights: dict[str, list[AccountInsight]], height: int = 520):
    """Single map with all recommended visit clinics across all accounts."""

    clinic_rows = []
    seen = set()
    for acct, insights in account_insights.items():
        for ins in insights:
            color = _MAP_COLOR[ins.sentiment]
            for vc in ins.clinics:
                if not vc.zip_code:
                    continue
                key = (vc.clinic, vc.zip_code)
                if key in seen:
                    continue
                seen.add(key)
                clinic_rows.append({
                    "clinic":  vc.clinic,
                    "account": acct,
                    "zip":     vc.zip_code,
                    "reason":  vc.reason,
                    "refs":    vc.refs,
                    "pct":     f"{vc.pct_booked:.0%}",
                    "days":    f"{vc.days_since}d ago" if vc.days_since is not None else "",
                    "type":    _TYPE_LABEL.get(ins.type, ins.type),
                    "r": color[0], "g": color[1], "b": color[2], "a": color[3],
                })

    if not clinic_rows:
        st.caption("No clinic locations to map.")
        return

    unique_zips = list({r["zip"] for r in clinic_rows})
    geo_df = geocode_zips(tuple(unique_zips))

    if geo_df.empty:
        st.caption("Could not geocode clinic locations.")
        return

    geo_map = geo_df.set_index("zip")[["lat", "lng"]].to_dict("index")
    map_rows = []
    for r in clinic_rows:
        geo = geo_map.get(r["zip"])
        if geo:
            map_rows.append({**r, "lat": geo["lat"], "lng": geo["lng"]})

    if not map_rows:
        st.caption("No mappable clinic locations found.")
        return

    lats = [r["lat"] for r in map_rows]
    lngs = [r["lng"] for r in map_rows]
    center_lat = sum(lats) / len(lats)
    center_lng = sum(lngs) / len(lngs)
    lat_range  = max(max(lats) - min(lats), 0.01)
    lng_range  = max(max(lngs) - min(lngs), 0.01)
    # Fit zoom tightly around the surfaced pins (max 14 for street-level)
    zoom = max(5, min(14, 9 - math.log2(max(lat_range, lng_range) / 0.3)))

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=map_rows,
        get_position=["lng", "lat"],
        get_fill_color=["r", "g", "b", "a"],
        get_radius=700,
        radius_min_pixels=7,
        radius_max_pixels=20,
        pickable=True,
    )

    tooltip = {
        "html": (
            "<b>{clinic}</b><br>"
            "<span style='color:#666;font-size:11px'>{account}</span><br>"
            "<span style='color:#888;font-size:11px'>{type}</span><br>"
            "{reason}<br>"
            "<span style='color:#aaa;font-size:11px'>{refs} refs · {pct} booked · {days}</span>"
        ),
        "style": {
            "backgroundColor": "white",
            "color": "#1A1A2E",
            "border": "1px solid #ddd",
            "borderRadius": "6px",
            "padding": "8px",
            "fontSize": "12px",
            "maxWidth": "260px",
        },
    }

    st.markdown(
        '<span style="font-size:11px;color:#888;">'
        '<span style="color:#dc3545">●</span> Negative/warning visit &nbsp;·&nbsp;'
        '<span style="color:#f5a623">●</span> Warning &nbsp;·&nbsp;'
        '<span style="color:#27AE60">●</span> Positive visit</span>',
        unsafe_allow_html=True,
    )
    st.pydeck_chart(
        pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(
                latitude=center_lat, longitude=center_lng,
                zoom=zoom, pitch=0,
            ),
            tooltip=tooltip,
            map_style="light",
        ),
        height=height,
    )
    st.caption(f"{len(map_rows)} clinic{'s' if len(map_rows) != 1 else ''} across {len(account_insights)} account{'s' if len(account_insights) != 1 else ''}")
