import streamlit as st
import pandas as pd
import pydeck as pdk
from math import radians, sin, cos, sqrt, atan2
from components.geo_map import geocode_zips
from data.transforms import count_unique_providers


def haversine_miles(lat1, lon1, lat2, lon2):
    """Distance between two lat/lng pairs in miles."""
    R = 3959
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


@st.cache_data
def build_clinic_geo_table(df):
    """Build a geocoded clinic table with metrics. Cached for performance."""
    clinic_agg = df.groupby(["REFERRING_CLINIC", "REFERRING_CLINIC_ZIP", "PARTNER_ASSIGNMENT"]).agg(
        referrals=("REFERRAL_ID", "count"),
        intake_started=("intake_started", "sum"),
        visit_booked=("visit_booked", "sum"),
        visit_completed=("visit_completed", "sum"),
        last_referral=("REFERRAL_DATE", "max"),
    ).reset_index()
    # Provider count with null-as-1 logic
    prov_counts = (
        df.groupby(["REFERRING_CLINIC", "REFERRING_CLINIC_ZIP", "PARTNER_ASSIGNMENT"])["provider_id"]
        .apply(count_unique_providers)
        .reset_index(name="providers")
    )
    clinic_agg = clinic_agg.merge(prov_counts, on=["REFERRING_CLINIC", "REFERRING_CLINIC_ZIP", "PARTNER_ASSIGNMENT"], how="left")
    clinic_agg["pct_booked"] = (clinic_agg["visit_booked"] / clinic_agg["referrals"]).fillna(0)
    clinic_agg["pct_completed"] = (clinic_agg["visit_completed"] / clinic_agg["referrals"]).fillna(0)
    clinic_agg["days_since"] = (pd.Timestamp.now().normalize() - clinic_agg["last_referral"]).dt.days

    # Geocode all unique zips
    zips = clinic_agg["REFERRING_CLINIC_ZIP"].dropna().unique().tolist()
    geo = geocode_zips(zips)
    if geo.empty:
        return clinic_agg
    clinic_agg = clinic_agg.merge(geo, left_on="REFERRING_CLINIC_ZIP", right_on="zip", how="left")
    return clinic_agg


def find_nearby_clinics(clinic_geo_df, target_lat, target_lng, radius_miles=3.0, exclude_clinic=None):
    """Find clinics within radius_miles of a target lat/lng."""
    has_coords = clinic_geo_df["lat"].notna() & clinic_geo_df["lng"].notna()
    nearby = clinic_geo_df[has_coords].copy()
    nearby["distance_mi"] = nearby.apply(
        lambda r: haversine_miles(target_lat, target_lng, r["lat"], r["lng"]), axis=1
    )
    nearby = nearby[nearby["distance_mi"] <= radius_miles]
    if exclude_clinic:
        nearby = nearby[nearby["REFERRING_CLINIC"] != exclude_clinic]
    return nearby.sort_values("referrals", ascending=False)


def render_nearby_map(target_lat, target_lng, target_name, nearby_df):
    """Render a pydeck map with target marker + nearby clinic bubbles."""
    if nearby_df.empty:
        st.info("No nearby clinics found within the selected radius.")
        return

    has_coords = nearby_df["lat"].notna() & nearby_df["lng"].notna()
    plot_df = nearby_df[has_coords].copy()

    # Color by category-like logic: high volume = bigger, high conversion = greener
    plot_df["color_r"] = ((1 - plot_df["pct_booked"]) * 220).clip(0, 255).astype(int)
    plot_df["color_g"] = (plot_df["pct_booked"] * 180).clip(0, 255).astype(int)
    plot_df["color_b"] = 80
    max_refs = max(plot_df["referrals"].max(), 1)
    plot_df["radius"] = (plot_df["referrals"] / max_refs * 300).clip(40, 400)

    # Tooltip
    plot_df["pct_booked_display"] = (plot_df["pct_booked"] * 100).round(1).astype(str) + "%"
    plot_df["distance_display"] = plot_df["distance_mi"].round(1).astype(str) + " mi"
    plot_df["days_display"] = plot_df["days_since"].astype(str) + "d ago"

    # Nearby clinics layer
    nearby_layer = pdk.Layer(
        "ScatterplotLayer",
        data=plot_df,
        get_position=["lng", "lat"],
        get_radius="radius",
        get_fill_color=["color_r", "color_g", "color_b", 180],
        pickable=True,
        radius_min_pixels=5,
        radius_max_pixels=30,
    )

    # Target marker — larger, distinct color
    target_layer = pdk.Layer(
        "ScatterplotLayer",
        data=pd.DataFrame([{
            "lat": target_lat, "lng": target_lng,
            "REFERRING_CLINIC": target_name,
            "PARTNER_ASSIGNMENT": "Target",
            "referrals": "",
            "pct_booked_display": "",
            "distance_display": "0 mi",
            "days_display": "",
        }]),
        get_position=["lng", "lat"],
        get_radius=80,
        get_fill_color=[220, 50, 50, 220],
        pickable=True,
        radius_min_pixels=12,
        radius_max_pixels=20,
    )

    view = pdk.ViewState(latitude=target_lat, longitude=target_lng, zoom=13, pitch=0)
    tooltip = {
        "html": (
            "<b>{REFERRING_CLINIC}</b><br>"
            "{PARTNER_ASSIGNMENT}<br>"
            "<b>{referrals}</b> referrals · {pct_booked_display} booked<br>"
            "{distance_display} away · last referral {days_display}"
        ),
        "style": {
            "backgroundColor": "white", "color": "#1A1A2E",
            "border": "1px solid #ddd", "borderRadius": "6px",
            "padding": "8px", "fontSize": "12px",
        },
    }

    deck = pdk.Deck(
        layers=[nearby_layer, target_layer],
        initial_view_state=view,
        tooltip=tooltip,
        map_style="light",
    )
    st.pydeck_chart(deck)
