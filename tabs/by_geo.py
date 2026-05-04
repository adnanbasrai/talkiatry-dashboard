import streamlit as st
from components.geo_map import render_geo_map
from components.kpi_row import render_kpi_row
from components.entity_table import render_entity_table
from components.trend_chart import render_trend_chart


@st.fragment
def render(df, period_col):
    accounts = sorted(df["PARTNER_ASSIGNMENT"].unique().tolist())
    selected_accounts = st.multiselect(
        "Filter by account(s)", options=accounts, default=None,
        placeholder="All accounts — type to search...", key="geo_acct_filter",
    )
    map_df = df[df["PARTNER_ASSIGNMENT"].isin(selected_accounts)] if selected_accounts else df

    st.subheader("Referral Map by Zip Code")
    color_mode = st.radio("Color by", ["Conversion rate", "Account"], horizontal=True, key="geo_color_mode")
    color_by_account = color_mode == "Account"
    caption = "Bubble size = referral volume. Color: by dominant account." if color_by_account else "Bubble size = referral volume. Color: green = high booking rate, red = low."
    st.caption(caption + " Hover for partner breakdown.")
    render_geo_map(map_df, color_by_account=color_by_account)

    render_kpi_row(map_df, period_col)

    zips = sorted(map_df["REFERRING_CLINIC_ZIP"].dropna().unique().tolist())
    selected_zips = st.multiselect("Filter by zip code(s)", zips, key="geo_zips")
    filtered = map_df[map_df["REFERRING_CLINIC_ZIP"].isin(selected_zips)] if selected_zips else map_df

    render_trend_chart(filtered, period_col, key="geo")

    # Inline entity toggle
    entity_focus = st.radio("View by", ["Clinics", "Providers"], horizontal=True, key="geo_entity_toggle")
    entity_col = "REFERRING_CLINIC" if entity_focus == "Clinics" else "REFERRING_PHYSICIAN"
    entity_label = "Clinic" if entity_focus == "Clinics" else "Provider"

    geo_multi_acct = not selected_accounts or len(selected_accounts) > 1
    suffix = f" in {', '.join(selected_zips[:3])}{'...' if len(selected_zips) > 3 else ''}" if selected_zips else ""
    render_entity_table(filtered, entity_col, period_col, label=entity_label, include_account=geo_multi_acct, title=f"{entity_label} Rankings{suffix}")
