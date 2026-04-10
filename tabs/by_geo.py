import streamlit as st
from components.geo_map import render_geo_map
from components.kpi_row import render_kpi_row
from components.entity_table import render_entity_table
from components.category_sections import render_category_sections
from components.trend_chart import render_trend_chart


def render(df, period_col, entity_col, entity_label):
    # Account filter for the map
    accounts = sorted(df["PARTNER_ASSIGNMENT"].unique().tolist())
    selected_accounts = st.multiselect(
        "Filter by account(s)",
        options=accounts,
        default=None,
        placeholder="All accounts — type to search...",
        key="geo_acct_filter",
    )

    if selected_accounts:
        map_df = df[df["PARTNER_ASSIGNMENT"].isin(selected_accounts)]
    else:
        map_df = df

    st.subheader("Referral Map by Zip Code")
    st.caption("Bubble size = referral volume. Color: green = high booking rate, red = low. Hover for partner breakdown.")

    map_data = render_geo_map(map_df)

    # KPIs for the filtered geography
    render_kpi_row(map_df, period_col)

    # Zip code filter
    zips = sorted(map_df["REFERRING_CLINIC_ZIP"].dropna().unique().tolist())
    selected_zips = st.multiselect("Filter by zip code(s)", zips, key="geo_zips")

    if selected_zips:
        filtered = map_df[map_df["REFERRING_CLINIC_ZIP"].isin(selected_zips)]
    else:
        filtered = map_df

    # Trend charts for selected geography
    render_trend_chart(filtered, period_col)

    # Entity table and categories
    suffix = ""
    if selected_zips:
        suffix = f" in {', '.join(selected_zips[:3])}{'...' if len(selected_zips) > 3 else ''}"
    if selected_accounts:
        suffix += f" ({', '.join(selected_accounts[:2])}{'...' if len(selected_accounts) > 2 else ''})"

    geo_multi_acct = not selected_accounts or len(selected_accounts) > 1
    st.subheader(f"Top {entity_label}s{suffix}")
    render_entity_table(filtered, entity_col, period_col, label=entity_label, include_account=geo_multi_acct)

    st.subheader(f"{entity_label} Categories{suffix}")
    render_category_sections(filtered, entity_col, period_col, label=entity_label, key_prefix="geo", include_account=geo_multi_acct)
