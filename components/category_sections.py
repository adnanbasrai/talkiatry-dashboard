import streamlit as st
import pandas as pd
from data.transforms import classify_entities


def _get_top_providers_for_entity(df, entity_col, entity_name, limit=5):
    """Get top referring providers for a given clinic/entity."""
    sub = df[df[entity_col] == entity_name]
    if sub.empty:
        return pd.DataFrame()
    prov_agg = sub.groupby("REFERRING_PHYSICIAN").agg(
        referrals=("REFERRAL_ID", "count"),
        visit_booked=("visit_booked", "sum"),
    ).reset_index()
    prov_agg["pct_booked"] = (prov_agg["visit_booked"] / prov_agg["referrals"]).fillna(0)
    return prov_agg.sort_values("referrals", ascending=False).head(limit)


def _format_category_table(cat_df, entity_col, label, include_account):
    """Format a category DataFrame for display."""
    cols = [entity_col]
    if include_account and "PARTNER_ASSIGNMENT" in cat_df.columns:
        cols.append("PARTNER_ASSIGNMENT")
    cols += ["referrals", "pct_intake", "pct_booked", "pct_completed"]

    disp = cat_df[cols].copy()
    disp["pct_intake"] = (disp["pct_intake"] * 100).round(1).astype(str) + "%"
    disp["pct_booked"] = (disp["pct_booked"] * 100).round(1).astype(str) + "%"
    disp["pct_completed"] = (disp["pct_completed"] * 100).round(1).astype(str) + "%"

    rename = {entity_col: label, "referrals": "Referrals",
              "pct_intake": "% Intake", "pct_booked": "% Booked", "pct_completed": "% Completed"}
    if include_account and "PARTNER_ASSIGNMENT" in cat_df.columns:
        rename["PARTNER_ASSIGNMENT"] = "Account"
    return disp.rename(columns=rename)


def render_category_sections(df, entity_col, period_col="month_of", label="Entity",
                             key_prefix="default", include_account=False):
    """Render the 4 provider/clinic category expanders."""
    cats = classify_entities(df, entity_col, period_col, include_account=include_account)

    with st.expander(f"Champions ({len(cats['champions'])})", expanded=False):
        if cats["champions"].empty:
            st.caption("Not enough data to identify champions.")
        else:
            disp = _format_category_table(cats["champions"], entity_col, label, include_account)
            st.dataframe(disp.reset_index(drop=True), use_container_width=True, hide_index=True)

            if entity_col == "REFERRING_CLINIC":
                champion_name = st.selectbox(
                    "View top providers for:",
                    cats["champions"][entity_col].tolist(),
                    index=None,
                    placeholder="Select a clinic...",
                    key=f"{key_prefix}_champion_provider_drill",
                )
                if champion_name:
                    top_provs = _get_top_providers_for_entity(df, entity_col, champion_name)
                    if not top_provs.empty:
                        top_provs["pct_booked"] = (top_provs["pct_booked"] * 100).round(1).astype(str) + "%"
                        top_provs = top_provs.rename(columns={
                            "REFERRING_PHYSICIAN": "Provider", "referrals": "Referrals", "pct_booked": "% Booked",
                        })
                        st.dataframe(
                            top_provs[["Provider", "Referrals", "% Booked"]].reset_index(drop=True),
                            use_container_width=True, hide_index=True,
                        )

    with st.expander(f"Lowest Converting ({len(cats['lowest_converting'])})", expanded=False):
        if cats["lowest_converting"].empty:
            st.caption("Not enough data.")
        else:
            disp = _format_category_table(cats["lowest_converting"], entity_col, label, include_account)
            st.dataframe(disp.reset_index(drop=True), use_container_width=True, hide_index=True)

            if entity_col == "REFERRING_CLINIC":
                lc_name = st.selectbox(
                    "View top providers for:",
                    cats["lowest_converting"][entity_col].tolist(),
                    index=None,
                    placeholder="Select a clinic...",
                    key=f"{key_prefix}_lowest_provider_drill",
                )
                if lc_name:
                    top_provs = _get_top_providers_for_entity(df, entity_col, lc_name)
                    if not top_provs.empty:
                        top_provs["pct_booked"] = (top_provs["pct_booked"] * 100).round(1).astype(str) + "%"
                        top_provs = top_provs.rename(columns={
                            "REFERRING_PHYSICIAN": "Provider", "referrals": "Referrals", "pct_booked": "% Booked",
                        })
                        st.dataframe(
                            top_provs[["Provider", "Referrals", "% Booked"]].reset_index(drop=True),
                            use_container_width=True, hide_index=True,
                        )

    with st.expander(f"Stopped Referring ({len(cats['stopped_referring'])})", expanded=False):
        if cats["stopped_referring"].empty:
            st.caption("No entities stopped referring between the last two periods.")
        else:
            stopped = cats["stopped_referring"].copy()
            cols = [entity_col]
            if include_account and "PARTNER_ASSIGNMENT" in stopped.columns:
                cols.append("PARTNER_ASSIGNMENT")
            cols.append("prior_referrals")
            rename = {entity_col: label, "prior_referrals": "Prior Period Referrals"}
            if include_account and "PARTNER_ASSIGNMENT" in stopped.columns:
                rename["PARTNER_ASSIGNMENT"] = "Account"
            disp = stopped[cols].rename(columns=rename)
            st.dataframe(disp.reset_index(drop=True), use_container_width=True, hide_index=True)

    with st.expander(f"First-Time Referrers ({len(cats['first_time'])})", expanded=False):
        if cats["first_time"].empty:
            st.caption("No new referrers in the most recent period.")
        else:
            ft = cats["first_time"].copy()
            ft["first_referral_date"] = ft["first_referral_date"].dt.strftime("%Y-%m-%d")
            cols = [entity_col]
            if include_account and "PARTNER_ASSIGNMENT" in ft.columns:
                cols.append("PARTNER_ASSIGNMENT")
            cols.append("first_referral_date")
            rename = {entity_col: label, "first_referral_date": "First Referral"}
            if include_account and "PARTNER_ASSIGNMENT" in ft.columns:
                rename["PARTNER_ASSIGNMENT"] = "Account"
            disp = ft[cols].rename(columns=rename)
            st.dataframe(disp.reset_index(drop=True), use_container_width=True, hide_index=True)
