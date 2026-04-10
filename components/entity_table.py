import streamlit as st
import pandas as pd
from data.transforms import compute_entity_table


def render_entity_table(df, entity_col, period_col="month_of", label="Entity", include_account=False):
    """Render a sortable entity ranking table. Includes Account column when multi-account."""
    table = compute_entity_table(df, entity_col, period_col, include_account=include_account)
    if table.empty:
        st.info("No data for this selection.")
        return

    # If listing accounts (entity_col IS PARTNER_ASSIGNMENT), add TEAM_TYPE
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
    cols += ["referrals", "pct_intake", "pct_booked", "pct_completed", "trend"]

    display = table[cols].copy()
    rename_map = {
        entity_col: label,
        "referrals": "Referrals",
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
        display[col] = (display[col] * 100).round(1).astype(str) + "%"
    display["Trend"] = display["Trend"].apply(
        lambda x: f"{x:+.0%}" if pd.notna(x) else "--"
    )

    st.dataframe(display.reset_index(drop=True), use_container_width=True, hide_index=True)
