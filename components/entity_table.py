import streamlit as st
import pandas as pd
from data.transforms import compute_entity_table

_export_counter = {"n": 0}

CATEGORY_BADGES = {
    "Champion": "🟢 Champion",
    "Low Converting": "🔴 Low Converting",
    "New": "🔵 New",
    "Stopped": "⚫ Stopped",
}


def _style_days_silent(val):
    """Placeholder — actual smart styling is done row-by-row below."""
    return ""


def render_entity_table(df, entity_col, period_col="month_of", label="Entity", include_account=False, title=None):
    """Render a consolidated entity table with title + export on same line."""
    table = compute_entity_table(df, entity_col, period_col, include_account=include_account)
    if table.empty:
        st.info("No data for this selection.")
        return

    # If listing accounts, add TEAM_TYPE
    show_team_type = entity_col == "PARTNER_ASSIGNMENT" and "TEAM_TYPE" in df.columns
    if show_team_type:
        team_map = (
            df.groupby("PARTNER_ASSIGNMENT")["TEAM_TYPE"]
            .agg(lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else "")
            .reset_index()
        )
        team_map.columns = ["PARTNER_ASSIGNMENT", "TEAM_TYPE"]
        table = table.merge(team_map, on="PARTNER_ASSIGNMENT", how="left")

    cols = [entity_col]
    if include_account:
        cols.append("PARTNER_ASSIGNMENT")
    if show_team_type:
        cols.append("TEAM_TYPE")
    cols.append("category")
    cols += ["referrals", "days_since_last", "pct_intake", "pct_booked", "pct_completed", "trend"]

    display = table[[c for c in cols if c in table.columns]].copy()
    rename_map = {
        entity_col: label, "referrals": "Referrals", "category": "Status",
        "days_since_last": "Days Silent", "pct_intake": "% Intake",
        "pct_booked": "% Booked", "pct_completed": "% Completed", "trend": "Trend",
    }
    if include_account:
        rename_map["PARTNER_ASSIGNMENT"] = "Account"
    if show_team_type:
        rename_map["TEAM_TYPE"] = "Team Type"
    display = display.rename(columns=rename_map)

    for col in ["% Intake", "% Booked", "% Completed"]:
        if col in display.columns:
            display[col] = (display[col] * 100).round(1).astype(str) + "%"
    if "Trend" in display.columns:
        display["Trend"] = display["Trend"].apply(lambda x: f"{x:+.0%}" if pd.notna(x) else "--")
    # Keep avg_days_between for smart styling, format Days Silent
    avg_freq = table["avg_days_between"] if "avg_days_between" in table.columns else None
    if "Days Silent" in display.columns:
        display["Days Silent"] = display["Days Silent"].apply(lambda x: f"{int(x)}d" if pd.notna(x) else "--")
    if "Status" in display.columns:
        display["Status"] = display["Status"].map(lambda x: CATEGORY_BADGES.get(x, ""))

    # Title + Export on same line
    _export_counter["n"] += 1
    csv = display.to_csv(index=False)

    if title:
        tcol, ecol = st.columns([5, 1])
        with tcol:
            st.subheader(title)
        with ecol:
            st.markdown("<div style='margin-top: 12px;'>", unsafe_allow_html=True)
            st.download_button(
                "Export CSV", csv, file_name=f"{label.lower()}_rankings.csv",
                mime="text/csv", key=f"export_{_export_counter['n']}",
            )
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.download_button(
            "Export CSV", csv, file_name=f"{label.lower()}_rankings.csv",
            mime="text/csv", key=f"export_{_export_counter['n']}",
        )

    # Date range indicator
    if "REFERRAL_DATE" in df.columns and not df.empty:
        d_min = df["REFERRAL_DATE"].min()
        d_max = df["REFERRAL_DATE"].max()
        if pd.notna(d_min) and pd.notna(d_max):
            st.markdown(
                f'<span style="font-size:10px; color:#999;">Data range: {d_min.strftime("%b %d, %Y")} — {d_max.strftime("%b %d, %Y")}</span>',
                unsafe_allow_html=True,
            )

    # Smart Days Silent styling: red if silent for 2x+ their normal referral frequency
    final = display.reset_index(drop=True)
    if "Days Silent" in final.columns and avg_freq is not None:
        def _smart_days_style(row_idx):
            val = final.loc[row_idx, "Days Silent"] if row_idx < len(final) else "--"
            if not isinstance(val, str) or val == "--":
                return [""] * len(final.columns)
            try:
                days = int(val.replace("d", ""))
            except (ValueError, TypeError):
                return [""] * len(final.columns)

            freq = avg_freq.iloc[row_idx] if row_idx < len(avg_freq) else 999
            threshold = max(freq * 2, 7)  # at least 7 days, or 2x their normal gap

            styles = [""] * len(final.columns)
            ds_col_idx = final.columns.get_loc("Days Silent")
            if days >= threshold * 2:
                styles[ds_col_idx] = "color: #dc3545; font-weight: bold"
            elif days >= threshold:
                styles[ds_col_idx] = "color: #dc3545"
            return styles

        styled = final.style.apply(lambda x: _smart_days_style(x.name), axis=1)
        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.dataframe(final, use_container_width=True, hide_index=True)

    # Legend
    footnotes = []
    if "Status" in display.columns:
        footnotes.append(
            '🟢 Champion = high volume + intake above median &nbsp;·&nbsp; '
            '🔴 Low Converting = intake in bottom 25%, min 5 refs &nbsp;·&nbsp; '
            '🔵 New = first referral in the most recent period &nbsp;·&nbsp; '
            '⚫ Stopped = referred last period, zero this period'
        )
    if "Days Silent" in display.columns:
        footnotes.append(
            'Days Silent in <span style="color:#dc3545;">red</span> = silent for 2x+ their normal referral frequency (min 7 days). '
            '<span style="color:#dc3545; font-weight:bold;">Bold red</span> = 4x+ their normal frequency.'
        )
    if footnotes:
        st.markdown(
            '<span style="font-size:10px; color:#999;">' + "<br>".join(footnotes) + '</span>',
            unsafe_allow_html=True,
        )
