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
    """Color Days Silent red when overdue."""
    if not isinstance(val, str) or val == "--":
        return ""
    try:
        days = int(val.replace("d", ""))
    except (ValueError, TypeError):
        return ""
    if days >= 14:
        return "color: #dc3545; font-weight: bold"
    elif days >= 7:
        return "color: #dc3545"
    return ""


def render_entity_table(df, entity_col, period_col="month_of", label="Entity", include_account=False):
    """Render a consolidated entity table with colored category badges, Days Silent alarm, and export."""
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

    # Build column list
    cols = [entity_col]
    if include_account:
        cols.append("PARTNER_ASSIGNMENT")
    if show_team_type:
        cols.append("TEAM_TYPE")
    cols.append("category")
    cols += ["referrals", "days_since_last", "pct_intake", "pct_booked", "pct_completed", "trend"]

    display = table[[c for c in cols if c in table.columns]].copy()
    rename_map = {
        entity_col: label,
        "referrals": "Referrals",
        "category": "Status",
        "days_since_last": "Days Silent",
        "pct_intake": "% Intake",
        "pct_booked": "% Booked",
        "pct_completed": "% Completed",
        "trend": "Trend",
    }
    if include_account:
        rename_map["PARTNER_ASSIGNMENT"] = "Account"
    if show_team_type:
        rename_map["TEAM_TYPE"] = "Team Type"
    display = display.rename(columns=rename_map)

    # Format
    for col in ["% Intake", "% Booked", "% Completed"]:
        if col in display.columns:
            display[col] = (display[col] * 100).round(1).astype(str) + "%"
    if "Trend" in display.columns:
        display["Trend"] = display["Trend"].apply(
            lambda x: f"{x:+.0%}" if pd.notna(x) else "--"
        )
    if "Days Silent" in display.columns:
        display["Days Silent"] = display["Days Silent"].apply(
            lambda x: f"{int(x)}d" if pd.notna(x) else "--"
        )
    # #4: Colored category badges
    if "Status" in display.columns:
        display["Status"] = display["Status"].map(lambda x: CATEGORY_BADGES.get(x, ""))

    # #6: Style Days Silent with red alarm
    styled = display.reset_index(drop=True).style.applymap(_style_days_silent, subset=["Days Silent"] if "Days Silent" in display.columns else [])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Export button
    _export_counter["n"] += 1
    csv = display.to_csv(index=False)
    st.download_button(
        "Export CSV", csv, file_name=f"{label.lower()}_rankings.csv",
        mime="text/csv", key=f"export_{_export_counter['n']}",
    )
