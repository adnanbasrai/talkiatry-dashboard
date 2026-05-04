"""
Cluster engine — builds geographic field-day clusters for a PPM.

Two cluster types:
  1. Signal-anchored: an existing referring clinic fired a signal (silent,
     volume drop, intake crash).  The anchor is that clinic.  All chase
     practices and other referral clinics within 3 miles are gathered around it.
  2. Prospect-density: no urgent signal, but a geographic area has enough
     chase-list practices to warrant a dedicated field day.

Clusters are scored, sorted, and assigned P1/P2/P3 priorities.
"""
from __future__ import annotations

import math
from math import radians, sin, cos, sqrt, atan2
from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd
import streamlit as st

from data.transforms import _count_weekdays

RADIUS_MILES = 3.0
MIN_CHASE_FOR_DENSITY = 3   # min chase practices to form a density cluster

# Scoring weights
SCORE_HAS_SIGNAL_ANCHOR   = 5
SCORE_SIGNAL_SILENT       = 3   # added on top of HAS_SIGNAL
SCORE_SIGNAL_VOLUME_CLIFF = 2
SCORE_SIGNAL_INTAKE_CRASH = 2
SCORE_GO_LIVE_PRE_LAUNCH  = 3   # per practice
SCORE_ACTIVE_ENGAGEMENT   = 2   # per practice
SCORE_COLD                = 0.5 # per practice
SCORE_PER_50_PHYSICIANS   = 1.0

# Priority thresholds
P1_THRESHOLD = 8
P2_THRESHOLD = 4


# ─── Haversine ────────────────────────────────────────────────────────────────
def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3959
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


# ─── Signal computation (extracted from action_plan.py logic) ─────────────────
def compute_clinic_signals(df: pd.DataFrame, period_col: str) -> List[Dict]:
    """
    Score every clinic in df for visit-worthiness.
    Returns a list of dicts sorted by score desc, each containing:
      clinic, account, zip, score, sentiment, signal_tags, reasons,
      curr_refs, paced_refs, prev_refs, lat (None until geocoded), lng (None)
    """
    if df.empty:
        return []

    periods = sorted(df[period_col].dropna().unique())
    if len(periods) < 2:
        return []

    is_weekly = period_col == "week_of"
    curr_p = periods[-1]
    prev_p = periods[-2]

    try:
        dt_curr = pd.Timestamp(str(curr_p))
        dt_prev = pd.Timestamp(str(prev_p))
        if is_weekly:
            curr_label = f"week of {(dt_curr - pd.Timedelta(days=dt_curr.weekday())).strftime('%b %d')}"
            prev_label = f"week of {(dt_prev - pd.Timedelta(days=dt_prev.weekday())).strftime('%b %d')}"
        else:
            curr_label = dt_curr.strftime("%b %Y")
            prev_label = dt_prev.strftime("%b %Y")
    except Exception:
        curr_label = str(curr_p)
        prev_label = str(prev_p)

    curr     = df[df[period_col] == curr_p]
    prev     = df[df[period_col] == prev_p]
    all_prior = df[df[period_col] < curr_p]

    # Pacing factor
    today = pd.Timestamp.now().normalize()
    if not is_weekly:
        p_start = pd.Period(curr_p, freq="M").start_time
        p_end   = pd.Period(curr_p, freq="M").end_time + pd.Timedelta(days=1)
    else:
        p_start = pd.Timestamp(curr_p)
        p_end   = p_start + pd.Timedelta(days=5)
    wd_elapsed = max(_count_weekdays(p_start, today), 1)
    wd_total   = max(_count_weekdays(p_start, p_end), 1)
    pace = wd_total / wd_elapsed

    prev_agg = prev.groupby("REFERRING_CLINIC").agg(
        prev_refs=("REFERRAL_ID", "count"),
        prev_intake=("intake_started", "sum"),
    ).reset_index()
    prev_agg["prev_pct_intake"] = prev_agg["prev_intake"] / prev_agg["prev_refs"]

    curr_agg = curr.groupby("REFERRING_CLINIC").agg(
        curr_refs=("REFERRAL_ID", "count"),
        curr_intake=("intake_started", "sum"),
    ).reset_index()
    curr_agg["curr_pct_intake"] = curr_agg["curr_intake"] / curr_agg["curr_refs"]
    curr_agg["paced_refs"] = (curr_agg["curr_refs"] * pace).round(0).astype(int)

    prior_clinics = set(all_prior["REFERRING_CLINIC"].dropna())
    curr_agg["is_new_clinic"] = ~curr_agg["REFERRING_CLINIC"].isin(prior_clinics)

    prior_provs = set(all_prior["provider_id"].dropna())
    new_prov_counts = []
    for clinic in curr["REFERRING_CLINIC"].dropna().unique():
        c_df = curr[curr["REFERRING_CLINIC"] == clinic]
        c_provs = set(c_df["provider_id"].dropna())
        new_prov_counts.append({"REFERRING_CLINIC": clinic, "new_provs": len(c_provs - prior_provs)})
    new_prov_df = pd.DataFrame(new_prov_counts) if new_prov_counts else pd.DataFrame(columns=["REFERRING_CLINIC", "new_provs"])

    signals = curr_agg.merge(prev_agg, on="REFERRING_CLINIC", how="outer")
    signals = signals.merge(new_prov_df, on="REFERRING_CLINIC", how="left")
    for col in ["curr_refs", "prev_refs", "paced_refs", "new_provs"]:
        signals[col] = signals[col].fillna(0).astype(int)

    signals["vol_pct"] = np.where(
        signals["prev_refs"] > 0,
        (signals["paced_refs"] - signals["prev_refs"]) / signals["prev_refs"],
        0,
    )
    signals["intake_pp"] = signals["curr_pct_intake"].fillna(0) - signals["prev_pct_intake"].fillna(0)
    signals["is_silent"] = (signals["prev_refs"] >= 5) & (signals["curr_refs"] == 0)

    acct_map = df.groupby("REFERRING_CLINIC")["PARTNER_ASSIGNMENT"].first().to_dict()
    zip_map  = df.groupby("REFERRING_CLINIC")["REFERRING_CLINIC_ZIP"].first().to_dict()
    signals["account"] = signals["REFERRING_CLINIC"].map(acct_map)
    signals["zip"]     = signals["REFERRING_CLINIC"].map(zip_map)

    scored = []
    for _, r in signals.iterrows():
        clinic   = r["REFERRING_CLINIC"]
        reasons  = []
        score    = 0
        sentiment = "neutral"
        signal_tags = []

        # ── positive signals ──
        if r["is_new_clinic"] and r["curr_refs"] >= 3:
            reasons.append(f"New clinic, {int(r['curr_refs'])} refs in {curr_label}")
            score += 3; sentiment = "green"

        if r["vol_pct"] > 0.5 and r["prev_refs"] >= 5:
            reasons.append(f"Volume surging {r['vol_pct']:+.0%} vs {prev_label}")
            score += 3; sentiment = "green"

        if r.get("new_provs", 0) >= 3:
            reasons.append(f"{int(r['new_provs'])} new providers in {curr_label}")
            score += 2; sentiment = "green"

        curr_intake = r.get("curr_pct_intake") or 0
        if curr_intake >= 0.55 and r["curr_refs"] >= 5:
            reasons.append(f"High intake ({curr_intake:.0%}) in {curr_label}")
            score += 2; sentiment = "green"

        if r["vol_pct"] > 1.0 and r["prev_refs"] >= 3 and sentiment != "red":
            reasons.append(f"Volume 2x+ vs {prev_label}")
            score += 2; sentiment = "green"

        # ── negative signals ──
        if r["is_silent"]:
            reasons.append(f"Silent — {int(r['prev_refs'])} refs in {prev_label}, 0 now")
            signal_tags.append("silent")
            score += 4; sentiment = "red"

        if r["vol_pct"] < -0.5 and r["prev_refs"] >= 5 and not r["is_silent"]:
            reasons.append(f"Volume dropped {r['vol_pct']:+.0%} vs {prev_label}")
            signal_tags.append("volume_cliff")
            score += 3; sentiment = "red"

        if r["intake_pp"] < -0.15 and r["curr_refs"] >= 5:
            reasons.append(f"Intake dropped {r['intake_pp']:+.0%}pp vs {prev_label}")
            signal_tags.append("intake_crash")
            score += 3; sentiment = "red"

        prev_intake = r.get("prev_pct_intake") or 0
        if curr_intake < 0.35 and prev_intake < 0.35 and r["curr_refs"] >= 5 and r["prev_refs"] >= 5:
            reasons.append(f"Persistently low intake — {curr_intake:.0%} now, {prev_intake:.0%} prior")
            score += 2; sentiment = "red"

        if reasons:
            scored.append({
                "clinic":      clinic,
                "account":     r.get("account", ""),
                "zip":         r.get("zip", ""),
                "score":       score,
                "sentiment":   sentiment,
                "signal_tags": signal_tags,
                "reasons":     reasons,
                "curr_refs":   int(r["curr_refs"]),
                "paced_refs":  int(r["paced_refs"]),
                "prev_refs":   int(r["prev_refs"]),
                "lat":         None,
                "lng":         None,
            })

    return sorted(scored, key=lambda x: -x["score"])


# ─── Main cluster builder ──────────────────────────────────────────────────────
def build_clusters(
    df: pd.DataFrame,
    period_col: str,
    chase_df: pd.DataFrame,
    ppm: Optional[str] = None,
) -> List[Dict]:
    """
    Build and score geographic clusters for a PPM.

    Args:
        df:         Referral data (already filtered to the PPM if desired, or full region).
        period_col: "month_of" | "week_of"
        chase_df:   Loaded chase list (from data.chase_list.load_chase_list())
        ppm:        If given, filter both df and chase_df to this PPM.

    Returns:
        List of cluster dicts, sorted by score desc, with priority assigned.
    """
    from components.geo_map import geocode_zips

    if ppm:
        df       = df[df["PPM"] == ppm]
        chase_df = chase_df[chase_df["ppm"] == ppm] if not chase_df.empty else chase_df

    if df.empty:
        return []

    # ── Geocode all relevant zips ──────────────────────────────────────────────
    ref_zips   = df["REFERRING_CLINIC_ZIP"].dropna().unique().tolist()
    chase_zips = chase_df["zip"].dropna().unique().tolist() if not chase_df.empty else []
    all_zips   = list(set(ref_zips + chase_zips))

    geo = geocode_zips(all_zips) if all_zips else pd.DataFrame(columns=["zip", "lat", "lng"])
    zip_to_latlon = dict(zip(geo["zip"], zip(geo["lat"], geo["lng"]))) if not geo.empty else {}

    def _latlon(zip_code):
        tup = zip_to_latlon.get(str(zip_code))
        return (float(tup[0]), float(tup[1])) if tup and tup[0] is not None else (None, None)

    # ── Signal clinics ─────────────────────────────────────────────────────────
    signal_clinics = compute_clinic_signals(df, period_col)
    for sc in signal_clinics:
        lat, lng = _latlon(sc["zip"])
        sc["lat"] = lat
        sc["lng"] = lng

    # ── Geocode chase practices ────────────────────────────────────────────────
    if not chase_df.empty:
        ch = chase_df.copy()
        ch["lat"] = ch["zip"].apply(lambda z: _latlon(z)[0])
        ch["lng"] = ch["zip"].apply(lambda z: _latlon(z)[1])
        ch = ch[ch["lat"].notna() & ch["lng"].notna()].reset_index(drop=True)
        ch["claimed"] = False
    else:
        ch = pd.DataFrame(columns=["practice_name", "lifecycle_stage", "lifecycle_rank",
                                   "zip", "lat", "lng", "address", "city", "state",
                                   "num_physicians", "partner_label", "ppm",
                                   "color", "claimed"])

    # ── Geocode referral clinics for "nearby existing partner" lists ───────────
    ref_clinic_agg = (
        df.groupby(["REFERRING_CLINIC", "REFERRING_CLINIC_ZIP", "PARTNER_ASSIGNMENT"])
        .agg(
            refs=("REFERRAL_ID", "count"),
            booked=("visit_booked", "sum"),
            days_since=("REFERRAL_DATE", lambda x: (pd.Timestamp.now().normalize() - x.max()).days),
        )
        .reset_index()
    )
    ref_clinic_agg["pct_booked"] = (ref_clinic_agg["booked"] / ref_clinic_agg["refs"]).fillna(0)
    ref_clinic_agg["lat"] = ref_clinic_agg["REFERRING_CLINIC_ZIP"].apply(lambda z: _latlon(z)[0])
    ref_clinic_agg["lng"] = ref_clinic_agg["REFERRING_CLINIC_ZIP"].apply(lambda z: _latlon(z)[1])
    ref_with_coords = ref_clinic_agg[ref_clinic_agg["lat"].notna() & ref_clinic_agg["lng"].notna()]

    clusters: List[Dict] = []

    # ── Phase 1 — Signal-anchored clusters ────────────────────────────────────
    for sc in signal_clinics:
        if sc["lat"] is None:
            continue

        # Chase practices within radius
        nearby_chase = _find_nearby_chase(ch[~ch["claimed"]], sc["lat"], sc["lng"])
        for nc in nearby_chase:
            ch.loc[nc["idx"], "claimed"] = True

        # Existing referral clinics within radius (excluding anchor itself)
        nearby_ref = _find_nearby_ref_clinics(
            ref_with_coords, sc["lat"], sc["lng"],
            exclude_clinic=sc["clinic"],
        )

        cluster = _make_cluster(
            cluster_type="signal_anchored",
            anchor=sc,
            chase_practices=nearby_chase,
            nearby_ref_clinics=nearby_ref,
            center_lat=sc["lat"],
            center_lng=sc["lng"],
        )
        clusters.append(cluster)

    # ── Phase 2 — Prospect-density clusters ────────────────────────────────────
    remaining_ch = ch[~ch["claimed"]].copy()

    while True:
        if remaining_ch.empty:
            break

        # Find the practice with the most neighbors in radius
        best_idx       = None
        best_neighbors: List[Dict] = []
        best_count     = 0

        for idx, row in remaining_ch.iterrows():
            neighbors = _find_nearby_chase(
                remaining_ch.drop(index=idx),
                row["lat"], row["lng"],
            )
            total = len(neighbors) + 1   # +1 for center itself
            if total >= MIN_CHASE_FOR_DENSITY and total > best_count:
                best_idx       = idx
                best_neighbors = neighbors
                best_count     = total

        if best_idx is None:
            break

        center_row     = remaining_ch.loc[best_idx]
        all_members    = [_chase_row_to_dict(center_row, 0.0)] + best_neighbors
        claimed_idxs   = [best_idx] + [n["idx"] for n in best_neighbors]
        ch.loc[claimed_idxs, "claimed"] = True
        remaining_ch = remaining_ch[~remaining_ch.index.isin(claimed_idxs)]

        center_lat, center_lng = float(center_row["lat"]), float(center_row["lng"])
        nearby_ref = _find_nearby_ref_clinics(ref_with_coords, center_lat, center_lng)

        cluster = _make_cluster(
            cluster_type="prospect_dense",
            anchor=None,
            chase_practices=all_members,
            nearby_ref_clinics=nearby_ref,
            center_lat=center_lat,
            center_lng=center_lng,
        )
        clusters.append(cluster)

    # ── Score, sort, assign priority ──────────────────────────────────────────
    for c in clusters:
        c["score"] = _score_cluster(c)

    clusters.sort(key=lambda x: -x["score"])

    for c in clusters:
        if c["score"] >= P1_THRESHOLD:
            c["priority"] = "P1"
        elif c["score"] >= P2_THRESHOLD:
            c["priority"] = "P2"
        else:
            c["priority"] = "P3"

    # Drop clusters too small to be useful
    valid = [
        c for c in clusters
        if c["anchor"] is not None or len(c["chase_practices"]) >= MIN_CHASE_FOR_DENSITY
    ]
    return valid


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _find_nearby_chase(ch_df: pd.DataFrame, lat: float, lng: float) -> List[Dict]:
    result = []
    for idx, row in ch_df.iterrows():
        d = haversine_miles(lat, lng, float(row["lat"]), float(row["lng"]))
        if d <= RADIUS_MILES:
            result.append({**_chase_row_to_dict(row, d), "idx": idx})
    # Sort by lifecycle priority desc, then distance
    result.sort(key=lambda x: (-x["lifecycle_rank"], x["distance_mi"]))
    return result


def _chase_row_to_dict(row, distance_mi: float) -> Dict:
    return {
        "name":            row.get("practice_name", ""),
        "lifecycle":       row.get("lifecycle_stage", ""),
        "lifecycle_rank":  float(row.get("lifecycle_rank", 0)),
        "distance_mi":     round(float(distance_mi), 2),
        "lat":             float(row["lat"]),
        "lng":             float(row["lng"]),
        "zip":             row.get("zip", ""),
        "address":         row.get("address", ""),
        "city":            row.get("city", ""),
        "state":           row.get("state", ""),
        "num_physicians":  row.get("num_physicians"),
        "partner_label":   row.get("partner_label", ""),
        "ppm":             row.get("ppm", ""),
        "color":           row.get("color", [150, 150, 150]),
    }


def _find_nearby_ref_clinics(
    ref_df: pd.DataFrame,
    lat: float, lng: float,
    exclude_clinic: Optional[str] = None,
) -> List[Dict]:
    result = []
    for _, row in ref_df.iterrows():
        if exclude_clinic and row["REFERRING_CLINIC"] == exclude_clinic:
            continue
        d = haversine_miles(lat, lng, float(row["lat"]), float(row["lng"]))
        if d <= RADIUS_MILES:
            result.append({
                "clinic":      row["REFERRING_CLINIC"],
                "account":     row["PARTNER_ASSIGNMENT"],
                "distance_mi": round(d, 2),
                "refs":        int(row["refs"]),
                "pct_booked":  float(row["pct_booked"]),
                "days_since":  int(row["days_since"]),
            })
    result.sort(key=lambda x: x["distance_mi"])
    return result


def _make_cluster(
    cluster_type: str,
    anchor: Optional[Dict],
    chase_practices: List[Dict],
    nearby_ref_clinics: List[Dict],
    center_lat: float,
    center_lng: float,
) -> Dict:
    """Assemble a cluster dict (before scoring)."""
    # Derive area name from most common city in chase practices
    cities = [p.get("city", "") for p in chase_practices if p.get("city")]
    area_name = max(set(cities), key=cities.count) if cities else ""
    if anchor:
        # Prefer anchor clinic city/area
        anchor_city = ""
        area_name = f"{anchor['account']}" if not area_name else f"{area_name}"

    # Physician upside
    total_physicians = int(sum(
        p["num_physicians"] for p in chase_practices
        if p.get("num_physicians") and not math.isnan(float(p["num_physicians"]))
    ))

    active_engagement_count  = sum(1 for p in chase_practices if p["lifecycle"] == "Active Engagement")
    cold_count               = sum(1 for p in chase_practices if p["lifecycle"] == "Cold")
    go_live_pre_launch_count = sum(1 for p in chase_practices if p["lifecycle"] in ("Go-Live", "Pre-Launch", "Active Partner"))

    return {
        "type":                  cluster_type,
        "anchor":                anchor,
        "chase_practices":       chase_practices,
        "nearby_ref_clinics":    nearby_ref_clinics,
        "center_lat":            center_lat,
        "center_lng":            center_lng,
        "area_name":             area_name,
        "total_physicians":      total_physicians,
        "active_engagement_count":  active_engagement_count,
        "cold_count":               cold_count,
        "go_live_pre_launch_count": go_live_pre_launch_count,
        "score":                 0,      # filled in later
        "priority":              "P3",   # filled in later
    }


def _score_cluster(cluster: Dict) -> float:
    score = 0.0
    anchor = cluster["anchor"]

    if anchor:
        score += SCORE_HAS_SIGNAL_ANCHOR
        tags = anchor.get("signal_tags", [])
        if "silent" in tags:
            score += SCORE_SIGNAL_SILENT
        if "volume_cliff" in tags:
            score += SCORE_SIGNAL_VOLUME_CLIFF
        if "intake_crash" in tags:
            score += SCORE_SIGNAL_INTAKE_CRASH

    score += cluster["go_live_pre_launch_count"] * SCORE_GO_LIVE_PRE_LAUNCH
    score += cluster["active_engagement_count"]  * SCORE_ACTIVE_ENGAGEMENT
    score += cluster["cold_count"]               * SCORE_COLD
    score += (cluster["total_physicians"] / 50)  * SCORE_PER_50_PHYSICIANS

    return round(score, 1)
