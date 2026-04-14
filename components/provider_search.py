import streamlit as st
import pandas as pd
import json
import urllib.request
import urllib.parse


@st.cache_data(ttl=3600)
def search_nppes(clinic_name=None, zip_code=None, limit=50):
    """Search the NPI Registry (NPPES) for providers by clinic name and/or zip code.
    Returns a DataFrame of individual providers found."""
    params = {"version": "2.1", "enumeration_type": "NPI-1", "limit": str(limit)}
    if zip_code:
        params["postal_code"] = str(zip_code)[:5]

    # Search for common primary care specialties
    results_all = []
    specialties = [
        "Internal Medicine", "Family Medicine", "General Practice",
        "Nurse Practitioner", "Physician Assistant",
    ]

    for spec in specialties:
        p = {**params, "taxonomy_description": spec}
        url = f"https://npiregistry.cms.hhs.gov/api/?{urllib.parse.urlencode(p)}"
        try:
            resp = urllib.request.urlopen(url, timeout=10)
            data = json.loads(resp.read())
            if data.get("results"):
                for r in data["results"]:
                    basic = r.get("basic", {})
                    addrs = r.get("addresses", [{}])
                    taxonomies = r.get("taxonomies", [{}])
                    addr = addrs[0] if addrs else {}
                    results_all.append({
                        "npi": r.get("number", ""),
                        "first_name": basic.get("first_name", ""),
                        "last_name": basic.get("last_name", ""),
                        "specialty": taxonomies[0].get("desc", ""),
                        "address": addr.get("address_1", ""),
                        "city": addr.get("city", ""),
                        "state": addr.get("state", ""),
                        "zip": str(addr.get("postal_code", ""))[:5],
                        "phone": addr.get("telephone_number", ""),
                    })
        except Exception:
            continue

    if not results_all:
        return pd.DataFrame()

    df = pd.DataFrame(results_all).drop_duplicates(subset=["npi"])
    df["name"] = df["first_name"] + " " + df["last_name"]

    # If clinic name provided, try to match by address similarity
    if clinic_name:
        clinic_words = set(clinic_name.lower().split())
        df["addr_match"] = df["address"].apply(
            lambda a: len(clinic_words & set(str(a).lower().split())) > 0 if pd.notna(a) else False
        )
        # Sort: address matches first, then by name
        df = df.sort_values(["addr_match", "last_name"], ascending=[False, True])

    return df[["npi", "name", "specialty", "address", "city", "state", "zip", "phone"]]


def search_hubspot_contacts(clinic_name):
    """Search HubSpot for contacts matching a clinic name. Returns results or empty."""
    try:
        from mcp__77db18e3_b3ff_4107_9ade_fee0218b6388__search_crm_objects import search_crm_objects
    except ImportError:
        pass

    # We'll use st.session_state to store results from HubSpot MCP calls
    # The actual MCP call happens in the tab, not here
    return None


def render_provider_search_results(npi_results, hubspot_results=None, clinic_name=""):
    """Render provider search results from NPI and HubSpot."""
    has_npi = npi_results is not None and not npi_results.empty
    has_hs = hubspot_results is not None and not hubspot_results.empty

    if not has_npi and not has_hs:
        st.caption("No providers found in NPI registry for this location.")
        return

    if has_npi:
        # Deduplicate and show
        display = npi_results[["name", "specialty", "address", "phone"]].head(15).copy()
        display = display.rename(columns={
            "name": "Provider", "specialty": "Specialty",
            "address": "Address", "phone": "Phone",
        })
        # Format phone
        display["Phone"] = display["Phone"].apply(
            lambda p: f"({p[:3]}) {p[3:6]}-{p[6:]}" if pd.notna(p) and len(str(p)) == 10 else str(p) if pd.notna(p) else ""
        )
        st.dataframe(display.reset_index(drop=True), use_container_width=True, hide_index=True)

    if has_hs:
        st.caption("HubSpot contacts:")
        st.dataframe(hubspot_results.reset_index(drop=True), use_container_width=True, hide_index=True)
