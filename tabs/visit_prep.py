import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from data.transforms import compute_metrics, compute_entity_table, compute_period_metrics
from components.nearby_map import build_clinic_geo_table, find_nearby_clinics, render_nearby_map, haversine_miles
from components.geo_map import geocode_zips
from components.pdf_export import generate_visit_prep_report
from components.provider_search import search_nppes, render_provider_search_results

PROV_ICON = "&#x1F9D1;&#x200D;&#x2695;&#xFE0F;"
CLINIC_ICON = "&#x1F3E5;"
LINE_STYLE = "margin: 2px 0 2px 12px; font-size: 13px; color: #333;"
SECTION_STYLE = "margin: 12px 0 4px 0; font-size: 15px; font-weight: 700; color: #1a1a2e; border-bottom: 1px solid rgba(0,0,0,0.1); padding-bottom: 3px;"


@st.fragment
def render(df, period_col):
    mode = st.radio("Mode", ["Look up existing clinic", "Prospect new clinics"], horizontal=True, key="vp_top_mode")

    if mode == "Look up existing clinic":
        _render_existing_lookup(df, period_col)
    else:
        _render_prospect_clinics(df, period_col)


def _render_existing_lookup(df, period_col):
    """Original visit prep: search existing clinics or zips."""
    st.subheader("Visit Prep")
    st.caption("Search for a clinic or zip code to get a briefing before your visit.")

    search_mode = st.radio("Search by", ["Clinic", "Zip Code"], horizontal=True, key="vp_mode")

    clinic_geo = build_clinic_geo_table(df)
    all_clinics = sorted(df["REFERRING_CLINIC"].dropna().unique().tolist())

    target_clinic = None
    target_zip = None
    target_lat = None
    target_lng = None

    if search_mode == "Clinic":
        selected = st.selectbox(
            "Clinic", options=all_clinics, index=None,
            placeholder="Type to search...", key="vp_clinic",
        )
        if selected:
            target_clinic = selected
            clinic_rows = clinic_geo[clinic_geo["REFERRING_CLINIC"] == selected]
            if not clinic_rows.empty and pd.notna(clinic_rows.iloc[0].get("lat")):
                target_lat = clinic_rows.iloc[0]["lat"]
                target_lng = clinic_rows.iloc[0]["lng"]
                target_zip = clinic_rows.iloc[0]["REFERRING_CLINIC_ZIP"]
    else:
        all_zips = sorted(df["REFERRING_CLINIC_ZIP"].dropna().unique().tolist())
        selected_zip = st.selectbox(
            "Zip Code", options=all_zips, index=None,
            placeholder="Type to search...", key="vp_zip",
        )
        if selected_zip:
            target_zip = selected_zip
            geo = geocode_zips([selected_zip])
            if not geo.empty:
                target_lat = geo.iloc[0]["lat"]
                target_lng = geo.iloc[0]["lng"]

    if not target_lat or not target_lng:
        if target_clinic or target_zip:
            st.warning("Could not geocode this location.")
        return

    # PDF export at top
    if target_clinic:
        nearby_for_pdf = find_nearby_clinics(build_clinic_geo_table(df), target_lat, target_lng, radius_miles=3, exclude_clinic=target_clinic)
        pdf_bytes = generate_visit_prep_report(df, target_clinic, nearby_for_pdf, period_col)
        if pdf_bytes:
            st.download_button(
                "Export Visit Briefing PDF", pdf_bytes,
                file_name=f"visit_prep_{target_clinic.replace(' ', '_')[:30]}.pdf",
                mime="application/pdf", key="vp_pdf_export",
            )

    if target_clinic:
        _render_clinic_briefing(df, target_clinic, period_col)
        _render_recent_patients(df, target_clinic)

    if search_mode == "Zip Code" and target_zip:
        zip_clinics = df[df["REFERRING_CLINIC_ZIP"] == target_zip]
        if not zip_clinics.empty:
            st.subheader(f"Clinics in {target_zip}")
            from components.entity_table import render_entity_table
            render_entity_table(zip_clinics, "REFERRING_CLINIC", period_col, label="Clinic", include_account=True)

    st.subheader("Nearby Clinics")
    radius = st.radio("Radius", [1, 3, 5], index=1, horizontal=True, key="vp_radius", format_func=lambda x: f"{x} mile{'s' if x > 1 else ''}")
    nearby = find_nearby_clinics(clinic_geo, target_lat, target_lng, radius_miles=radius, exclude_clinic=target_clinic)

    target_name = target_clinic or f"Zip {target_zip}"
    render_nearby_map(target_lat, target_lng, target_name, nearby)

    if not nearby.empty:
        _render_while_nearby(nearby)

    if not nearby.empty:
        nc_title, nc_export = st.columns([4, 1])
        with nc_title:
            st.caption(f"{len(nearby)} clinics within {radius} miles")
        with nc_export:
            csv = nearby[[
                "REFERRING_CLINIC", "PARTNER_ASSIGNMENT", "distance_mi",
                "referrals", "providers", "pct_booked", "days_since",
            ]].copy()
            csv["distance_mi"] = csv["distance_mi"].round(1)
            csv["pct_booked"] = (csv["pct_booked"] * 100).round(1)
            st.download_button("Export CSV", csv.to_csv(index=False), "nearby_clinics.csv", "text/csv", key="vp_nearby_csv")
        display = nearby[[
            "REFERRING_CLINIC", "PARTNER_ASSIGNMENT", "distance_mi",
            "referrals", "providers", "pct_booked", "days_since",
        ]].copy()
        display["distance_mi"] = display["distance_mi"].round(1).astype(str) + " mi"
        display["pct_booked"] = (display["pct_booked"] * 100).round(1).astype(str) + "%"
        display["days_since"] = display["days_since"].apply(lambda x: f"{int(x)}d" if pd.notna(x) else "--")
        display = display.rename(columns={
            "REFERRING_CLINIC": "Clinic", "PARTNER_ASSIGNMENT": "Account",
            "distance_mi": "Distance", "referrals": "Referrals",
            "providers": "Providers", "pct_booked": "% Booked",
            "days_since": "Days Silent",
        })
        st.dataframe(display.reset_index(drop=True), use_container_width=True, hide_index=True)

    # PDF export already at top of page


def _render_prospect_clinics(df, period_col):
    """Import new/prospect clinics and generate intel briefings."""
    st.subheader("Prospect New Clinics")
    st.caption("Import clinics you're planning to visit. We'll find nearby referring clinics and providers within 3 miles.")

    import_mode = st.radio("Import method", ["Paste a list", "Upload CSV"], horizontal=True, key="vp_import_mode")

    prospect_df = None

    if import_mode == "Upload CSV":
        st.caption("CSV should have columns: `name`, `zip` (required). Optional: `address`, `phone`.")
        uploaded = st.file_uploader("Upload CSV", type=["csv"], key="vp_csv_upload")
        if uploaded:
            try:
                prospect_df = pd.read_csv(uploaded)
                # Normalize column names
                prospect_df.columns = [c.strip().lower().replace(" ", "_") for c in prospect_df.columns]
                if "name" not in prospect_df.columns or "zip" not in prospect_df.columns:
                    st.error("CSV must have `name` and `zip` columns.")
                    prospect_df = None
            except Exception as e:
                st.error(f"Error reading CSV: {e}")
    else:
        st.caption("One clinic per line: `Name, Zip, Address (optional), Phone (optional)`")
        text = st.text_area(
            "Paste clinics here",
            placeholder="Acme Primary Care, 10016, 123 Main St, 212-555-1234\nBrooklyn Health, 11201",
            height=150, key="vp_paste",
        )
        if text and text.strip():
            rows = []
            for line in text.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    row = {"name": parts[0], "zip": parts[1]}
                    if len(parts) >= 3:
                        row["address"] = parts[2]
                    if len(parts) >= 4:
                        row["phone"] = parts[3]
                    rows.append(row)
            if rows:
                prospect_df = pd.DataFrame(rows)

    if prospect_df is None or prospect_df.empty:
        return

    # Clean zips
    prospect_df["zip"] = prospect_df["zip"].astype(str).str.strip().str.split("-").str[0].str.zfill(5)

    st.success(f"{len(prospect_df)} clinics imported")

    # Geocode all prospect zips
    unique_zips = prospect_df["zip"].unique().tolist()
    geo = geocode_zips(unique_zips)
    if geo.empty:
        st.warning("Could not geocode any zip codes.")
        return

    prospect_df = prospect_df.merge(geo, left_on="zip", right_on="zip", how="left")
    clinic_geo = build_clinic_geo_table(df)

    # Generate briefing for each prospect
    for idx, row in prospect_df.iterrows():
        name = row["name"]
        zip_code = row["zip"]
        address = row.get("address", "")
        phone = row.get("phone", "")
        lat = row.get("lat")
        lng = row.get("lng")

        subtitle_parts = [zip_code]
        if address:
            subtitle_parts.insert(0, str(address))
        if phone:
            subtitle_parts.append(str(phone))

        st.markdown(f"### {CLINIC_ICON} {name}")
        st.caption(" · ".join(subtitle_parts))

        if pd.isna(lat) or pd.isna(lng):
            st.warning(f"Could not geocode zip {zip_code}")
            st.divider()
            continue

        # Check if this clinic already exists in our data
        existing = df[df["REFERRING_CLINIC"].str.contains(name, case=False, na=False)]
        if not existing.empty:
            m = compute_metrics(existing)
            st.markdown(
                f'<div style="background-color: #d4edda; padding: 8px 12px; border-radius: 6px; font-size: 13px;">'
                f'This clinic has referred before: {m["referrals"]:,} referrals, '
                f'{m["unique_providers"]:,} providers, {m["pct_intake"]:.0%} intake started</div>',
                unsafe_allow_html=True,
            )

        # Find nearby referring clinics
        nearby = find_nearby_clinics(clinic_geo, lat, lng, radius_miles=3)
        nearby_count = len(nearby)
        nearby_refs = int(nearby["referrals"].sum()) if not nearby.empty else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Nearby Clinics (3mi)", f"{nearby_count}")
        col2.metric("Nearby Referrals", f"{nearby_refs:,}")
        col3.metric("Top Nearby Account", nearby.iloc[0]["PARTNER_ASSIGNMENT"] if not nearby.empty else "None")

        # --- NPI Registry: providers AT this clinic ---
        with st.expander(f"Providers at {name} (NPI Registry)", expanded=True):
            npi_results = search_nppes(clinic_name=name, zip_code=zip_code, limit=50)
            if not npi_results.empty:
                st.caption(f"{len(npi_results)} primary care providers found in zip {zip_code}")
                render_provider_search_results(npi_results)
            else:
                st.caption(f"No primary care providers found in NPI registry for zip {zip_code}")

        # --- HubSpot: contacts matching this clinic ---
        _render_hubspot_contacts(name)

        if not nearby.empty:
            # Map
            render_nearby_map(lat, lng, name, nearby)

            # Top 5 nearby clinics table
            top5 = nearby.head(5)[[
                "REFERRING_CLINIC", "PARTNER_ASSIGNMENT", "distance_mi",
                "referrals", "providers", "pct_booked",
            ]].copy()
            top5["distance_mi"] = top5["distance_mi"].round(1).astype(str) + " mi"
            top5["pct_booked"] = (top5["pct_booked"] * 100).round(1).astype(str) + "%"
            top5 = top5.rename(columns={
                "REFERRING_CLINIC": "Nearby Clinic", "PARTNER_ASSIGNMENT": "Account",
                "distance_mi": "Dist", "referrals": "Refs",
                "providers": "Provs", "pct_booked": "% Booked",
            })
            st.dataframe(top5.reset_index(drop=True), use_container_width=True, hide_index=True)

            # Top referring providers in the area (from Talkiatry data)
            nearby_zips = set(nearby["REFERRING_CLINIC_ZIP"].dropna())
            area_providers = df[df["REFERRING_CLINIC_ZIP"].isin(nearby_zips)]
            if not area_providers.empty:
                prov_agg = area_providers.groupby(["provider_id", "REFERRING_PHYSICIAN", "REFERRING_CLINIC"]).agg(
                    referrals=("REFERRAL_ID", "count"),
                ).reset_index().sort_values("referrals", ascending=False).head(5)
                if not prov_agg.empty:
                    with st.expander(f"Top referring providers within 3 miles ({len(prov_agg)})"):
                        prov_display = prov_agg[["REFERRING_PHYSICIAN", "REFERRING_CLINIC", "referrals"]].rename(columns={
                            "REFERRING_PHYSICIAN": "Provider", "REFERRING_CLINIC": "Clinic", "referrals": "Referrals",
                        })
                        st.dataframe(prov_display.reset_index(drop=True), use_container_width=True, hide_index=True)
        else:
            st.caption("No referring clinics found within 3 miles.")

        st.divider()


def _render_hubspot_contacts(clinic_name):
    """Search HubSpot for contacts matching a clinic name."""
    try:
        from mcp__77db18e3_b3ff_4107_9ade_fee0218b6388 import search_crm_objects
        # This would be called via MCP tools at runtime
        # For now, show a placeholder that can be wired up
    except ImportError:
        pass

    # Use session state to avoid redundant searches
    key = f"hs_search_{clinic_name}"
    if key not in st.session_state:
        st.session_state[key] = None

    with st.expander(f"HubSpot contacts for {clinic_name}"):
        st.caption("Search HubSpot for existing contacts at this clinic.")
        if st.button(f"Search HubSpot", key=f"hs_btn_{hash(clinic_name)}"):
            st.session_state[key] = "searching"

        if st.session_state.get(key) == "searching":
            st.info(
                "HubSpot search requires the MCP connector. "
                "Use the HubSpot search tool in your CLI to query: "
                f"`company name contains '{clinic_name}'` and look for associated contacts."
            )


def _get_referral_status(row):
    """Map a referral row to a clear status with termination reason where applicable."""
    # Terminal states first
    if row.get("visit_completed") == 1:
        return "Visit Completed"
    if row.get("visit_booked") == 1:
        return "Visit Booked"

    # Rejected / terminated — show why
    action = row.get("INTAKE_ACTION_STATUS", "")
    termination = row.get("TERMINATION_REASON", "")
    if action == "Rejected":
        if pd.notna(termination) and termination:
            tr = str(termination)
            if "OON" in tr or "OutOfNetwork" in tr or "InsurancePlan" in tr or "Payor" in tr:
                return "Rejected — Insurance OON"
            elif "Minor" in tr:
                return "Rejected — Minor"
            elif "Inpatient" in tr:
                return "Rejected — Recently Inpatient"
            elif "Emergency" in tr:
                return "Rejected — Emergency"
            elif "Schizo" in tr:
                return "Rejected — Clinical"
            else:
                return f"Rejected — {tr[:30]}"
        return "Rejected"

    # Intake completed but not booked
    is_completed = row.get("IS_INTAKE_COMPLETED")
    if is_completed == 1 and action == "NonResponsive":
        return "Intake Done — Non-Responsive"
    if is_completed == 1 and action in ("New", "Called", "CalledSecondTime", "CalledThirdTime"):
        return "Intake Done — Awaiting Booking"
    if is_completed == 1:
        return "Intake Completed"

    # In-progress states
    if action == "NonResponsive":
        return "Non-Responsive"
    if action == "New":
        return "Intake In Progress"
    if action in ("Called", "CalledSecondTime", "CalledThirdTime"):
        return "Outreach In Progress"

    if row.get("intake_started") == 1:
        return "Intake Started"

    return "Not Started"


def _status_color(status):
    """Return a background color for a referral status."""
    if "Completed" in status or "Visit" in status:
        return "#d4edda"
    if "Booked" in status:
        return "#cce5ff"
    if "Progress" in status or "Awaiting" in status:
        return "#fff3cd"
    if "Rejected" in status:
        return "#f8d7da"
    if "Non-Responsive" in status:
        return "#f8d7da"
    if "Not Started" in status:
        return "#fce4ec"
    return "#f5f7fa"


def _render_recent_patients(df, clinic_name):
    """Show recent patient referrals for a clinic — last 14 days."""
    today = pd.Timestamp.now().normalize()
    cutoff = today - pd.Timedelta(days=14)

    clinic_df = df[(df["REFERRING_CLINIC"] == clinic_name) & (df["REFERRAL_DATE"] >= cutoff)]
    if clinic_df.empty:
        st.caption("No referrals from this clinic in the last 14 days.")
        return

    clinic_df = clinic_df.sort_values("REFERRAL_DATE", ascending=False).copy()
    clinic_df["status"] = clinic_df.apply(_get_referral_status, axis=1)
    clinic_df["ref_date"] = clinic_df["REFERRAL_DATE"].dt.strftime("%Y-%m-%d")

    # Format DOB if available, fallback to age
    if "PATIENT_DOB" in clinic_df.columns:
        clinic_df["dob_display"] = clinic_df["PATIENT_DOB"].dt.strftime("%m/%d/%Y")
        dob_col = "dob_display"
        dob_label = "DOB"
    elif "PATIENT_AGE" in clinic_df.columns:
        dob_col = "PATIENT_AGE"
        dob_label = "Age"
    else:
        dob_col = None
        dob_label = None

    display_cols = ["ref_date", "REFERRING_PHYSICIAN", "patient_name"]
    if dob_col:
        display_cols.append(dob_col)
    display_cols.append("status")
    display_cols = [c for c in display_cols if c in clinic_df.columns]
    display = clinic_df[display_cols].copy()

    rename = {
        "ref_date": "Referral Date",
        "REFERRING_PHYSICIAN": "Referring Physician",
        "patient_name": "Patient",
        "dob_display": "DOB",
        "PATIENT_AGE": "Age",
        "status": "Status",
    }
    display = display.rename(columns={k: v for k, v in rename.items() if k in display.columns})

    st.subheader(f"Recent Referrals — Last 14 Days ({len(display)})")
    st.markdown(
        f'<span style="font-size:10px; color:#999;">Data range: {cutoff.strftime("%b %d, %Y")} — {today.strftime("%b %d, %Y")}</span>',
        unsafe_allow_html=True,
    )

    # Style status column with colors
    def _style_status(val):
        bg = _status_color(val)
        return f"background-color: {bg}; border-radius: 3px; padding: 2px 6px;"

    styled = display.reset_index(drop=True).style.applymap(
        _style_status, subset=["Status"] if "Status" in display.columns else []
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # Summary counts
    status_counts = display["Status"].value_counts() if "Status" in display.columns else pd.Series()
    if not status_counts.empty:
        summary_parts = [f"{count} {status}" for status, count in status_counts.items()]
        st.caption(" · ".join(summary_parts))


def _render_clinic_briefing(df, clinic_name, period_col):
    """Render the clinic briefing card."""
    clinic_df = df[df["REFERRING_CLINIC"] == clinic_name]
    if clinic_df.empty:
        return

    m = compute_metrics(clinic_df)
    accounts = ", ".join(clinic_df["PARTNER_ASSIGNMENT"].unique()[:3])
    zip_code = clinic_df["REFERRING_CLINIC_ZIP"].mode().iloc[0] if not clinic_df["REFERRING_CLINIC_ZIP"].mode().empty else "N/A"
    last_ref = clinic_df["REFERRAL_DATE"].max()
    days_since = (pd.Timestamp.now().normalize() - last_ref).days if pd.notna(last_ref) else None

    entity_table = compute_entity_table(df, "REFERRING_CLINIC", period_col)
    cat_row = entity_table[entity_table["REFERRING_CLINIC"] == clinic_name]
    category = cat_row["category"].iloc[0] if not cat_row.empty and "category" in cat_row.columns else ""

    cat_badge = ""
    if category == "Champion":
        cat_badge = '<span style="background:#28a745;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">Champion</span>'
    elif category == "Low Converting":
        cat_badge = '<span style="background:#dc3545;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">Low Converting</span>'
    elif category == "New":
        cat_badge = '<span style="background:#007bff;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">New</span>'
    elif category == "Stopped":
        cat_badge = '<span style="background:#6c757d;color:white;padding:2px 8px;border-radius:4px;font-size:12px;">Stopped</span>'

    days_str = f" · Last referral <b>{days_since}d ago</b>" if days_since is not None else ""
    d_min = clinic_df["REFERRAL_DATE"].min()
    d_max = clinic_df["REFERRAL_DATE"].max()
    st.markdown(f"### {CLINIC_ICON} {clinic_name} {cat_badge}", unsafe_allow_html=True)
    st.markdown(f"<span style='font-size:13px;color:#666;'>{accounts} · {zip_code}{days_str}</span>", unsafe_allow_html=True)
    if pd.notna(d_min) and pd.notna(d_max):
        st.markdown(
            f'<span style="font-size:10px; color:#999;">Data range: {d_min.strftime("%b %d, %Y")} — {d_max.strftime("%b %d, %Y")}</span>',
            unsafe_allow_html=True,
        )

    cols = st.columns(5)
    kpis = [
        ("Referrals", f"{m['referrals']:,}"),
        ("Providers", f"{m['unique_providers']:,}"),
        ("% Intake", f"{m['pct_intake']:.1%}"),
        ("% Booked", f"{m['pct_booked']:.1%}"),
        ("% Completed", f"{m['pct_completed']:.1%}"),
    ]
    for col, (label, val) in zip(cols, kpis):
        col.metric(label, val)

    st.markdown(f"**Top Providers**")
    prov_agg = clinic_df.groupby(["provider_id", "REFERRING_PHYSICIAN"]).agg(
        referrals=("REFERRAL_ID", "count"),
        visit_booked=("visit_booked", "sum"),
        last_ref=("REFERRAL_DATE", "max"),
    ).reset_index()
    prov_agg["pct_booked"] = (prov_agg["visit_booked"] / prov_agg["referrals"]).fillna(0)
    prov_agg = prov_agg.sort_values("referrals", ascending=False).head(10)

    prov_display = prov_agg[["REFERRING_PHYSICIAN", "referrals", "pct_booked", "last_ref"]].copy()
    prov_display["pct_booked"] = (prov_display["pct_booked"] * 100).round(1).astype(str) + "%"
    prov_display["last_ref"] = prov_display["last_ref"].dt.strftime("%Y-%m-%d")
    prov_display = prov_display.rename(columns={
        "REFERRING_PHYSICIAN": "Provider", "referrals": "Referrals",
        "pct_booked": "% Booked", "last_ref": "Last Referral",
    })
    st.dataframe(prov_display.reset_index(drop=True), use_container_width=True, hide_index=True)

    period_data = compute_period_metrics(clinic_df, period_col)
    if len(period_data) > 1:
        labels = period_data[period_col].tolist()
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=labels, y=period_data["referrals"],
            marker_color="#4A90D9",
            text=period_data["referrals"], textposition="auto",
            textfont=dict(size=12, color="white"),
        ))
        fig.update_layout(
            height=200, margin=dict(t=10, b=20, l=40, r=10),
            yaxis=dict(title=""), showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True, key="vp_trend")

    st.divider()


def _render_while_nearby(nearby):
    """Render the 'While you're in the area' actionable callout."""
    lines = []

    champions = nearby[nearby.get("pct_booked", 0) > nearby["pct_booked"].median()]
    if not champions.empty:
        top = champions.iloc[0]
        lines.append(
            f'<p style="{LINE_STYLE}">{CLINIC_ICON} <b>Say thanks</b> to '
            f'<b>{top["REFERRING_CLINIC"]}</b> — {int(top["referrals"])} referrals, '
            f'{top["pct_booked"]:.0%} booked, {top["distance_mi"]:.1f} mi away ({top["PARTNER_ASSIGNMENT"]})</p>'
        )

    silent = nearby[nearby["days_since"] >= 14].sort_values("referrals", ascending=False)
    if not silent.empty:
        s = silent.iloc[0]
        lines.append(
            f'<p style="{LINE_STYLE}">{CLINIC_ICON} <b>Re-engage</b> '
            f'<b>{s["REFERRING_CLINIC"]}</b> — {int(s["referrals"])} referrals, '
            f'silent {int(s["days_since"])}d, {s["distance_mi"]:.1f} mi away ({s["PARTNER_ASSIGNMENT"]})</p>'
        )

    high_vol = nearby[nearby["referrals"] >= nearby["referrals"].quantile(0.75)] if len(nearby) >= 4 else nearby.head(1)
    used = set()
    if not champions.empty:
        used.add(champions.iloc[0]["REFERRING_CLINIC"])
    if not silent.empty:
        used.add(silent.iloc[0]["REFERRING_CLINIC"])
    high_vol = high_vol[~high_vol["REFERRING_CLINIC"].isin(used)]
    if not high_vol.empty:
        h = high_vol.iloc[0]
        lines.append(
            f'<p style="{LINE_STYLE}">{CLINIC_ICON} <b>Drop by</b> '
            f'<b>{h["REFERRING_CLINIC"]}</b> — {int(h["referrals"])} referrals, '
            f'{h["pct_booked"]:.0%} booked, {h["distance_mi"]:.1f} mi away ({h["PARTNER_ASSIGNMENT"]})</p>'
        )

    if lines:
        html = (
            '<div style="background-color: #e8f4fd; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #4A90D9; margin: 8px 0;">'
            f'<p style="{SECTION_STYLE}">While you\'re in the area</p>'
            + "\n".join(lines)
            + "</div>"
        )
        st.markdown(html, unsafe_allow_html=True)
