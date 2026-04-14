import streamlit as st
import pandas as pd
import pydeck as pdk

try:
    import pgeocode
    PGEOCODE_AVAILABLE = True
except ImportError:
    PGEOCODE_AVAILABLE = False


@st.cache_data
def geocode_zips(zips):
    """Convert zip codes to lat/lng using pgeocode."""
    if not PGEOCODE_AVAILABLE:
        return pd.DataFrame()
    nomi = pgeocode.Nominatim("us")
    results = []
    for z in zips:
        try:
            info = nomi.query_postal_code(z)
            if pd.notna(info.latitude):
                results.append({"zip": z, "lat": info.latitude, "lng": info.longitude})
        except Exception:
            continue
    return pd.DataFrame(results)


def render_geo_map(df, color_by_account=False):
    """Render a pydeck map of referral volume by zip code with partner breakdown tooltip."""
    # Aggregate by zip
    zip_agg = df.groupby("REFERRING_CLINIC_ZIP").agg(
        referrals=("REFERRAL_ID", "count"),
        visit_booked=("visit_booked", "sum"),
        visit_completed=("visit_completed", "sum"),
    ).reset_index()
    zip_agg["pct_booked"] = (zip_agg["visit_booked"] / zip_agg["referrals"]).fillna(0)
    zip_agg = zip_agg[zip_agg["REFERRING_CLINIC_ZIP"].notna()]

    # Build partner breakdown per zip for tooltip
    partner_by_zip = (
        df.groupby(["REFERRING_CLINIC_ZIP", "PARTNER_ASSIGNMENT"])["REFERRAL_ID"]
        .count()
        .reset_index()
    )
    partner_by_zip.columns = ["REFERRING_CLINIC_ZIP", "partner", "count"]
    # Only partners with > 0 referrals, build HTML string
    def build_partner_html(zip_code):
        sub = partner_by_zip[partner_by_zip["REFERRING_CLINIC_ZIP"] == zip_code].sort_values("count", ascending=False)
        lines = [f"{row['partner']}: {row['count']}" for _, row in sub.iterrows() if row["count"] > 0]
        return "<br>".join(lines)

    zip_agg["partner_breakdown"] = zip_agg["REFERRING_CLINIC_ZIP"].apply(build_partner_html)
    zip_agg["pct_booked_display"] = (zip_agg["pct_booked"] * 100).round(1).astype(str) + "%"

    geo = geocode_zips(zip_agg["REFERRING_CLINIC_ZIP"].unique().tolist())
    if geo.empty:
        st.warning("Could not geocode zip codes. Ensure pgeocode is installed.")
        return None

    merged = zip_agg.merge(geo, left_on="REFERRING_CLINIC_ZIP", right_on="zip", how="inner")
    if merged.empty:
        st.warning("No geocoded zip codes found.")
        return None

    # Color by top account in each zip, or by conversion rate
    if color_by_account:
        # Assign color based on the dominant account in each zip
        top_partner = (
            partner_by_zip.sort_values("count", ascending=False)
            .drop_duplicates("REFERRING_CLINIC_ZIP")
            .set_index("REFERRING_CLINIC_ZIP")["partner"]
        )
        merged["top_partner"] = merged["REFERRING_CLINIC_ZIP"].map(top_partner)
        unique_partners = merged["top_partner"].unique().tolist()
        import plotly.express as px
        palette = px.colors.qualitative.Set2
        partner_colors = {}
        for i, p in enumerate(unique_partners):
            hex_c = palette[i % len(palette)].lstrip("rgb(").rstrip(")")
            if hex_c.startswith("#"):
                r, g, b = int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)
            else:
                parts = [x.strip() for x in hex_c.split(",")]
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            partner_colors[p] = (r, g, b)
        merged["color_r"] = merged["top_partner"].map(lambda p: partner_colors.get(p, (74, 144, 217))[0])
        merged["color_g"] = merged["top_partner"].map(lambda p: partner_colors.get(p, (74, 144, 217))[1])
        merged["color_b"] = merged["top_partner"].map(lambda p: partner_colors.get(p, (74, 144, 217))[2])
    else:
        # Default: green (high conversion) to red (low)
        merged["color_r"] = ((1 - merged["pct_booked"]) * 220).clip(0, 255).astype(int)
        merged["color_g"] = (merged["pct_booked"] * 180).clip(0, 255).astype(int)
        merged["color_b"] = 80

    # Size: proportional to volume
    max_refs = merged["referrals"].max()
    merged["radius"] = (merged["referrals"] / max_refs * 3000).clip(300, 5000)

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=merged,
        get_position=["lng", "lat"],
        get_radius="radius",
        get_fill_color=["color_r", "color_g", "color_b", 180],
        pickable=True,
    )

    view = pdk.ViewState(latitude=40.7, longitude=-74.0, zoom=7, pitch=0)
    tooltip = {
        "html": (
            "<b>Zip:</b> {REFERRING_CLINIC_ZIP}<br>"
            "<b>Total Referrals:</b> {referrals}<br>"
            "<b>% Booked:</b> {pct_booked_display}<br>"
            "<hr style='margin:4px 0'>"
            "{partner_breakdown}"
        ),
        "style": {
            "backgroundColor": "white",
            "color": "#1A1A2E",
            "border": "1px solid #ddd",
            "borderRadius": "6px",
            "padding": "8px",
            "fontSize": "12px",
        },
    }

    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=view,
        tooltip=tooltip,
        map_style="light",
    )
    st.pydeck_chart(deck)

    return merged
