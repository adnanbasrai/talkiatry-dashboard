import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from data.transforms import compute_period_metrics

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


_chart_counter = {"n": 0}

def render_trend_chart(df, period_col, group_col=None):
    """Render two side-by-side charts: referral volume bars + unique provider bars."""
    # Unique prefix for all charts in this call to avoid duplicate element IDs
    _chart_counter["n"] += 1
    _k = f"tc{_chart_counter['n']}"

    is_weekly = period_col == "week_of"
    metrics = compute_period_metrics(df, period_col)
    provider_counts = (
        df.groupby(period_col)["REFERRING_PHYSICIAN"]
        .nunique()
        .reset_index()
    )
    provider_counts.columns = [period_col, "providers"]
    provider_counts[period_col] = provider_counts[period_col].astype(str)

    labels = _format_period_labels(metrics[period_col], is_weekly=is_weekly)
    n = len(labels)
    colors = _bar_colors(n)
    text_colors = _bar_text_colors(n)

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
        fig1.update_layout(
            title="Referral Volume",
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
        fig2.update_layout(
            title="Unique Referring Providers",
            yaxis=dict(title="Providers"),
            height=350,
            margin=dict(t=50, b=30),
            showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True, key=f"{_k}_prov")

    # --- If grouped, show a stacked bar below for referral breakdown by group ---
    if group_col:
        top_groups = df[group_col].value_counts().head(8).index.tolist()
        sub = df[df[group_col].isin(top_groups)]
        grouped = sub.groupby([period_col, group_col]).agg(
            referrals=("REFERRAL_ID", "count"),
        ).reset_index()
        grouped[period_col] = grouped[period_col].astype(str)
        sorted_periods = sorted(grouped[period_col].unique())
        grouped_labels = _format_period_labels(sorted_periods, is_weekly=is_weekly)
        label_map = dict(zip(sorted_periods, grouped_labels))
        last_period = sorted_periods[-1] if sorted_periods else None
        grouped["period_label"] = grouped[period_col].map(label_map)

        fig3 = go.Figure()
        base_colors = px.colors.qualitative.Set2
        for i, grp in enumerate(top_groups):
            grp_data = grouped[grouped[group_col] == grp].sort_values(period_col)
            base = base_colors[i % len(base_colors)]
            # Lighten the last bar for each group
            grp_colors = [
                base if p != last_period else _lighten_hex(base, 0.45)
                for p in grp_data[period_col]
            ]
            fig3.add_trace(go.Bar(
                x=grp_data["period_label"],
                y=grp_data["referrals"],
                name=grp,
                marker_color=grp_colors,
                text=grp_data["referrals"],
                textposition="auto",
                textfont=dict(size=12),
            ))
        fig3.update_layout(
            barmode="stack",
            title="Referrals by Account",
            yaxis=dict(title="Referrals"),
            height=380,
            margin=dict(t=50, b=30),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig3, use_container_width=True, key=f"{_k}_grp")

    # --- Conversion Rate Trends ---
    fig4 = go.Figure()
    conv_lines = [
        ("pct_intake", "% Intake Started", "#4A90D9"),
        ("pct_booked", "% Visit Booked", "#E8734A"),
        ("pct_completed", "% Visit Completed", "#48B461"),
    ]
    for col, name, color in conv_lines:
        # Lighter marker for the last (incomplete) point
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
        title="Conversion Rates",
        yaxis=dict(tickformat=".0%"),
        height=350,
        margin=dict(t=50, b=60),
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
