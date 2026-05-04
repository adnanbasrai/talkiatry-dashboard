import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd


@st.fragment
def render(df, period_col):
    # Inline entity toggle for drill-downs
    entity_focus = st.radio("Drill down by", ["Clinics", "Providers"], horizontal=True, key="conv_entity_toggle")
    entity_col = "REFERRING_CLINIC" if entity_focus == "Clinics" else "REFERRING_PHYSICIAN"
    entity_label = "Clinic" if entity_focus == "Clinics" else "Provider"

    # --- Scope filters ---
    col1, col2 = st.columns(2)
    with col1:
        accounts = sorted(df["PARTNER_ASSIGNMENT"].unique().tolist())
        acct = st.selectbox("Account", accounts, index=None, placeholder="All accounts — type to search...", key="conv_acct")
    with col2:
        ppms = sorted(df["PPM"].unique().tolist())
        ppm = st.selectbox("PPM", ppms, index=None, placeholder="All PPMs — type to search...", key="conv_ppm")

    filtered = df.copy()
    if acct:
        filtered = filtered[filtered["PARTNER_ASSIGNMENT"] == acct]
    if ppm:
        filtered = filtered[filtered["PPM"] == ppm]

    n = len(filtered)
    if n == 0:
        st.warning("No data for this selection.")
        return

    # --- Funnel ---
    intake_started = filtered["intake_started"].sum()
    visit_booked = filtered["visit_booked"].sum()
    visit_completed = filtered["visit_completed"].sum()

    fig = go.Figure(go.Funnel(
        y=["Referrals", "Intake Started", "Visit Booked", "Visit Completed"],
        x=[n, intake_started, visit_booked, visit_completed],
        textinfo="value+percent initial",
        marker=dict(color=["#4A90D9", "#5BA8C8", "#7BC8A4", "#48B461"]),
    ))
    fig.update_layout(height=280, margin=dict(t=20, b=10, l=10, r=10))
    st.plotly_chart(fig, use_container_width=True, key="conv_funnel")

    # --- Stage selectors ---
    stage = st.radio(
        "Drill into stage",
        ["Stage 1: Referral to Intake", "Stage 2: Intake to Booked", "Stage 3: Booked to Completed"],
        horizontal=True, key="conv_stage"
    )

    drill_by = st.radio(
        "Drill down by", [entity_label, "Clinic", "Provider", "Zip Code"],
        horizontal=True, key="conv_drill"
    )
    drill_col_map = {
        "Clinic": "REFERRING_CLINIC",
        "Provider": "REFERRING_PHYSICIAN",
        "Zip Code": "REFERRING_CLINIC_ZIP",
    }
    drill_col = drill_col_map.get(drill_by, entity_col)

    if stage == "Stage 1: Referral to Intake":
        _render_stage1(filtered, drill_col, drill_by)
    elif stage == "Stage 2: Intake to Booked":
        _render_stage2(filtered, drill_col, drill_by)
    else:
        _render_stage3(filtered, drill_col, drill_by)


def _render_stage1(df, drill_col, drill_label):
    """Referral -> Intake Start drop-off analysis."""
    non_starters = df[df["intake_started"] == 0]
    n_non = len(non_starters)
    n_total = len(df)

    st.markdown(f"**{n_non:,}** of **{n_total:,}** referrals never started intake ({n_non/n_total:.0%})")

    # Root cause breakdown
    outreach_counts = non_starters["outreach_status"].value_counts()
    no_contact = ((~non_starters["has_email"]) & (~non_starters["has_phone"])).sum()

    breakdown = pd.DataFrame({
        "Reason": list(outreach_counts.index) + ["Missing contact info (no email + no phone)"],
        "Count": list(outreach_counts.values) + [no_contact],
    }).sort_values("Count", ascending=False)

    col1, col2 = st.columns([1, 1])
    with col1:
        fig = px.bar(breakdown, x="Count", y="Reason", orientation="h",
                     color_discrete_sequence=["#4A90D9"])
        fig.update_layout(height=250, margin=dict(t=10, b=10), yaxis_title="")
        st.plotly_chart(fig, use_container_width=True, key="conv_s1_outreach")

    with col2:
        # Drill-down table: which entities have the worst intake start rate?
        entity_agg = df.groupby(drill_col).agg(
            referrals=("REFERRAL_ID", "count"),
            intake_started=("intake_started", "sum"),
        ).reset_index()
        entity_agg["pct_intake"] = entity_agg["intake_started"] / entity_agg["referrals"]
        entity_agg["not_started"] = entity_agg["referrals"] - entity_agg["intake_started"]
        entity_agg = entity_agg[entity_agg["referrals"] >= 3].sort_values("pct_intake")
        display = entity_agg[[drill_col, "referrals", "not_started", "pct_intake"]].head(20).copy()
        display["pct_intake"] = (display["pct_intake"] * 100).round(1).astype(str) + "%"
        display = display.rename(columns={
            drill_col: drill_label, "referrals": "Referrals",
            "not_started": "Not Started", "pct_intake": "% Intake Started"
        })
        st.caption(f"Worst {drill_label}s by intake start rate (min 3 referrals)")
        st.dataframe(display.reset_index(drop=True), use_container_width=True, hide_index=True)


def _render_stage2(df, drill_col, drill_label):
    """Intake Start -> Visit Booked drop-off analysis."""
    started = df[df["intake_started"] == 1]
    not_booked = started[started["visit_booked"] == 0]
    n_drop = len(not_booked)
    n_started = len(started)

    st.markdown(f"**{n_drop:,}** of **{n_started:,}** who started intake didn't book ({n_drop/n_started:.0%})" if n_started > 0 else "No intake starters.")

    if n_drop == 0:
        return

    # Root cause: intake action status + termination
    action_counts = not_booked["INTAKE_ACTION_STATUS"].fillna("Unknown").value_counts()
    col1, col2 = st.columns([1, 1])

    with col1:
        st.caption("By Intake Status")
        breakdown = action_counts.reset_index()
        breakdown.columns = ["Status", "Count"]
        fig = px.bar(breakdown, x="Count", y="Status", orientation="h",
                     color_discrete_sequence=["#E8734A"])
        fig.update_layout(height=250, margin=dict(t=10, b=10), yaxis_title="")
        st.plotly_chart(fig, use_container_width=True, key="conv_s2_status")

    with col2:
        # Termination reasons (for those who were rejected/terminated)
        terminated = not_booked[not_booked["termination_category"] != "None"]
        if len(terminated) > 0:
            st.caption("Termination Reasons")
            term_counts = terminated["termination_category"].value_counts().reset_index()
            term_counts.columns = ["Reason", "Count"]
            fig2 = px.bar(term_counts, x="Count", y="Reason", orientation="h",
                          color_discrete_sequence=["#D94A4A"])
            fig2.update_layout(height=250, margin=dict(t=10, b=10), yaxis_title="")
            st.plotly_chart(fig2, use_container_width=True, key="conv_s2_termination")

    # Insurance OON drill-down
    oon = not_booked[not_booked["termination_category"] == "Insurance OON"]
    if len(oon) > 0:
        with st.expander(f"Insurance OON Detail ({len(oon)} patients)"):
            ins_counts = oon["PATIENT_INSURANCE_NAME"].value_counts().head(15).reset_index()
            ins_counts.columns = ["Insurance", "OON Count"]
            st.dataframe(ins_counts, use_container_width=True, hide_index=True)

    # Drill-down table
    entity_agg = started.groupby(drill_col).agg(
        started=("REFERRAL_ID", "count"),
        booked=("visit_booked", "sum"),
    ).reset_index()
    entity_agg["pct_booked"] = entity_agg["booked"] / entity_agg["started"]
    entity_agg["not_booked"] = entity_agg["started"] - entity_agg["booked"]
    entity_agg = entity_agg[entity_agg["started"] >= 3].sort_values("pct_booked")
    display = entity_agg[[drill_col, "started", "not_booked", "pct_booked"]].head(20).copy()
    display["pct_booked"] = (display["pct_booked"] * 100).round(1).astype(str) + "%"
    display = display.rename(columns={
        drill_col: drill_label, "started": "Intake Started",
        "not_booked": "Not Booked", "pct_booked": "% Booked"
    })
    st.caption(f"Worst {drill_label}s by booking rate (min 3 starters)")
    st.dataframe(display.reset_index(drop=True), use_container_width=True, hide_index=True)


def _render_stage3(df, drill_col, drill_label):
    """Visit Booked -> Visit Completed drop-off analysis."""
    booked = df[df["visit_booked"] == 1]
    not_completed = booked[booked["visit_completed"] == 0]
    n_drop = len(not_completed)
    n_booked = len(booked)

    st.markdown(f"**{n_drop:,}** of **{n_booked:,}** booked visits not completed ({n_drop/n_booked:.0%})" if n_booked > 0 else "No booked visits.")

    if n_drop == 0:
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        # By intake action status
        action_counts = not_completed["INTAKE_ACTION_STATUS"].fillna("Unknown").value_counts().reset_index()
        action_counts.columns = ["Status", "Count"]
        fig = px.bar(action_counts, x="Count", y="Status", orientation="h",
                     color_discrete_sequence=["#9B59B6"])
        fig.update_layout(height=250, margin=dict(t=10, b=10), yaxis_title="", title="By Intake Status")
        st.plotly_chart(fig, use_container_width=True, key="conv_s3_status")

    with col2:
        # By appointment source
        src_counts = not_completed["APPOINTMENT_SOURCE_FIRST_SCHEDULED"].fillna("Unknown").value_counts().reset_index()
        src_counts.columns = ["Source", "Count"]
        fig2 = px.bar(src_counts, x="Count", y="Source", orientation="h",
                      color_discrete_sequence=["#F39C12"])
        fig2.update_layout(height=250, margin=dict(t=10, b=10), yaxis_title="", title="By Booking Source")
        st.plotly_chart(fig2, use_container_width=True, key="conv_s3_source")

    # Drill-down table
    entity_agg = booked.groupby(drill_col).agg(
        booked=("REFERRAL_ID", "count"),
        completed=("visit_completed", "sum"),
    ).reset_index()
    entity_agg["pct_completed"] = entity_agg["completed"] / entity_agg["booked"]
    entity_agg["not_completed"] = entity_agg["booked"] - entity_agg["completed"]
    entity_agg = entity_agg[entity_agg["booked"] >= 3].sort_values("pct_completed")
    display = entity_agg[[drill_col, "booked", "not_completed", "pct_completed"]].head(20).copy()
    display["pct_completed"] = (display["pct_completed"] * 100).round(1).astype(str) + "%"
    display = display.rename(columns={
        drill_col: drill_label, "booked": "Booked",
        "not_completed": "Not Completed", "pct_completed": "% Completed"
    })
    st.caption(f"Worst {drill_label}s by completion rate (min 3 booked)")
    st.dataframe(display.reset_index(drop=True), use_container_width=True, hide_index=True)
