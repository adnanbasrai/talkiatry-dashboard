import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from data.transforms import compute_period_metrics, count_unique_providers

# Full color and lighter shade for incomplete period
BAR_COLOR = "#4A90D9"
BAR_COLOR_LIGHT = "#A8CCF0"


def _format_period_labels(series, is_weekly=False):
    """Format period labels. Monthly: 'Jan 2026'. Weekly: 'Mon DD, YYYY' (Monday of that week)."""
    result = []
    for val in series:
        try:
            dt = pd.Timestamp(str(val))
            if is_weekly:
                monday = dt - pd.Timedelta(days=dt.weekday())
                result.append(monday.strftime("%b %d, %Y"))
            else:
                result.append(dt.strftime("%b %Y"))
        except Exception:
            result.append(str(val))
    return result


def _bar_colors(n):
    """Return a list of bar colors: all full blue except the last one is lighter (incomplete period)."""
    if n <= 1:
        return [BAR_COLOR_LIGHT] * n
    return [BAR_COLOR] * (n - 1) + [BAR_COLOR_LIGHT]


def _bar_text_colors(n):
    """White text on full bars, dark text on the light incomplete bar."""
    if n <= 1:
        return ["#333333"] * n
    return ["white"] * (n - 1) + ["#333333"]


def render_trend_chart(df, period_col, group_col=None, key="tc"):
    """Render two side-by-side charts: referral volume bars + unique provider bars,
    plus a conversion rate line chart. Includes a clinic/provider drill-down filter."""
    _k = key  # stable key — must be unique per call site, not per render

    is_weekly = period_col == "week_of"

    # ── Chart entity filter ───────────────────────────────────────────────────
    fcol1, fcol2 = st.columns([2, 3])
    with fcol1:
        chart_filter = st.radio(
            "Filter charts by:",
            ["All", "Clinic", "Provider"],
            horizontal=True,
            key=f"{_k}_chart_filter",
        )

    df_chart = df
    filter_subtitle = ""
    filter_entity_name = ""   # plain name for chart titles

    with fcol2:
        if chart_filter == "Clinic":
            clinic_opts = (
                df["REFERRING_CLINIC"]
                .dropna()
                .pipe(lambda s: s[s.str.strip() != ""])
                .value_counts()
                .index.tolist()
            )
            sel = st.selectbox(
                "Clinic", options=clinic_opts,
                index=None,
                key=f"{_k}_clinic_sel", label_visibility="collapsed",
                placeholder="Search clinics…",
            )
            if sel:
                df_chart = df[df["REFERRING_CLINIC"] == sel]
                filter_subtitle = f"📍 {sel}"
                filter_entity_name = sel
        elif chart_filter == "Provider":
            prov_opts = (
                df["REFERRING_PHYSICIAN"]
                .dropna()
                .pipe(lambda s: s[s.str.strip() != ""])
                .value_counts()
                .index.tolist()
            )
            sel = st.selectbox(
                "Provider", options=prov_opts,
                index=None,
                key=f"{_k}_prov_sel", label_visibility="collapsed",
                placeholder="Search providers…",
            )
            if sel:
                df_chart = df[df["REFERRING_PHYSICIAN"] == sel]
                filter_subtitle = f"👤 {sel}"
                filter_entity_name = sel

    if df_chart.empty:
        st.info("No data for the selected filter.")
        return

    metrics = compute_period_metrics(df_chart, period_col)
    provider_counts = (
        df_chart.groupby(period_col)["provider_id"]
        .apply(count_unique_providers)
        .reset_index()
    )
    provider_counts.columns = [period_col, "providers"]
    provider_counts[period_col] = provider_counts[period_col].astype(str)

    # Build a complete date spine so gaps show as 0
    if len(metrics) >= 2:
        if is_weekly:
            # All Mondays from first to last, but not before Jan of the earliest year in data
            first = pd.Timestamp(metrics[period_col].iloc[0])
            last = pd.Timestamp(metrics[period_col].iloc[-1])
            all_periods = pd.date_range(first, last, freq="W-MON").astype(str).tolist()
        else:
            first = pd.Period(metrics[period_col].iloc[0], freq="M")
            last = pd.Period(metrics[period_col].iloc[-1], freq="M")
            all_periods = [str(p) for p in pd.period_range(first, last, freq="M")]

        spine = pd.DataFrame({period_col: all_periods})
        metrics = spine.merge(metrics, on=period_col, how="left").fillna(0)
        for col in ["referrals"]:
            metrics[col] = metrics[col].astype(int)
        provider_counts = spine.merge(provider_counts, on=period_col, how="left").fillna(0)
        provider_counts["providers"] = provider_counts["providers"].astype(int)

    labels = _format_period_labels(metrics[period_col], is_weekly=is_weekly)
    n = len(labels)
    colors = _bar_colors(n)
    text_colors = _bar_text_colors(n)

    # Find "best ever" for complete periods (exclude last which is partial)
    complete_refs = metrics["referrals"].iloc[:-1] if n > 1 else metrics["referrals"]
    complete_provs = provider_counts["providers"].iloc[:-1] if n > 1 else provider_counts["providers"]
    best_ref_idx = complete_refs.idxmax() if len(complete_refs) > 0 and complete_refs.max() > 0 else None
    best_prov_idx = complete_provs.idxmax() if len(complete_provs) > 0 and complete_provs.max() > 0 else None

    col_left, col_right = st.columns(2)

    # --- Left: Referral Volume ---
    with col_left:
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            x=labels,
            y=metrics["referrals"],
            name="Referrals",
            marker_color=colors,
            text=metrics["referrals"],
            textposition="inside",
            textfont=dict(size=14, color=text_colors),
        ))
        # Star on best period
        period_word = "week" if is_weekly else "month"
        if best_ref_idx is not None:
            fig1.add_annotation(
                x=labels[best_ref_idx],
                y=metrics["referrals"].iloc[best_ref_idx],
                text=f"⭐ Best {period_word} ever",
                showarrow=False,
                font=dict(size=9, color="#555"),
                yshift=14,
            )
        vol_title = "Referral Volume" if not filter_entity_name else f"Referral Volume — {filter_entity_name}"
        fig1.update_layout(
            title=vol_title,
            yaxis=dict(title="Referrals"),
            height=350,
            margin=dict(t=50, b=30),
            showlegend=False,
        )
        st.plotly_chart(fig1, use_container_width=True, key=f"{_k}_vol")

    # --- Right: Unique Providers ---
    with col_right:
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=labels,
            y=provider_counts["providers"],
            name="Unique Providers",
            marker_color=colors,
            text=provider_counts["providers"],
            textposition="inside",
            textfont=dict(size=14, color=text_colors),
        ))
        # Star on best period
        if best_prov_idx is not None:
            fig2.add_annotation(
                x=labels[best_prov_idx],
                y=provider_counts["providers"].iloc[best_prov_idx],
                text=f"⭐ Best {period_word} ever",
                showarrow=False,
                font=dict(size=9, color="#555"),
                yshift=14,
            )
        fig2.update_layout(
            title="Unique Referring Providers",
            yaxis=dict(title="Providers"),
            height=350,
            margin=dict(t=50, b=30),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True, key=f"{_k}_prov")

    # --- Conversion Rate Trends ---
    conv_header = "**Conversion Rates**" if not filter_entity_name else f"**Conversion Rates — {filter_entity_name}**"
    st.markdown(conv_header)

    # Conversion summary right below the title
    if len(metrics) >= 3:
        recent = metrics.tail(3)
        rows = recent.to_dict("records")
        # Last complete = second to last, prior = third to last, current partial = last
        if len(rows) == 3:
            prior, last_complete, current = rows[0], rows[1], rows[2]
            prior_label = prior[period_col]
            last_label = last_complete[period_col]
            curr_label = current[period_col]

            intake_delta = last_complete["pct_intake"] - prior["pct_intake"]
            direction = "up" if intake_delta > 0 else "down"

            parts = []
            parts.append(
                f"<b>Intake start rate</b> went {direction} from {prior['pct_intake']:.0%} ({prior_label}) "
                f"to {last_complete['pct_intake']:.0%} ({last_label}), "
                f"a <b>{abs(intake_delta):.1%}pp</b> {'improvement' if intake_delta > 0 else 'decline'}."
            )

            # Current partial month context
            parts.append(
                f"{curr_label} (in progress) is at {current['pct_intake']:.0%} intake, "
                f"{current['pct_booked']:.0%} booked, {current['pct_completed']:.0%} completed "
                f"— booked and completed rates will rise as appointments are fulfilled."
            )

            st.markdown(
                '<div style="background-color: #f5f7fa; padding: 8px 14px; border-radius: 6px; font-size: 13px;">'
                + " ".join(parts) + "</div>",
                unsafe_allow_html=True,
            )

    # Conversion chart
    fig4 = go.Figure()
    conv_lines = [
        ("pct_intake", "% Intake Started", "#4A90D9"),
        ("pct_booked", "% Visit Booked", "#E8734A"),
        ("pct_completed", "% Visit Completed", "#48B461"),
    ]
    for col, name, color in conv_lines:
        marker_colors = [color] * (n - 1) + [_lighten_hex(color, 0.45)] if n > 1 else [_lighten_hex(color, 0.45)]
        fig4.add_trace(go.Scatter(
            x=labels,
            y=metrics[col],
            name=name,
            mode="lines+markers+text",
            text=[f"{v:.0%}" for v in metrics[col]],
            textposition="top center",
            textfont=dict(size=12),
            line=dict(color=color, width=2),
            marker=dict(size=8, color=marker_colors),
        ))

    fig4.update_layout(
        yaxis=dict(tickformat=".0%"),
        height=350,
        margin=dict(t=20, b=60),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig4, use_container_width=True, key=f"{_k}_conv")


def _lighten_hex(color_str, factor=0.45):
    """Lighten a color by blending toward white. Handles hex (#4A90D9) and rgb(r,g,b) formats."""
    import re
    # Handle rgb() format from plotly color scales
    rgb_match = re.match(r"rgb\((\d+),\s*(\d+),\s*(\d+)\)", color_str)
    if rgb_match:
        r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))
    else:
        hex_color = color_str.lstrip("#")
        r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"
