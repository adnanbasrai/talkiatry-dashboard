import io
import pandas as pd
from fpdf import FPDF
from data.transforms import compute_metrics, compute_entity_table, compute_velocity


def _safe(text):
    """Sanitize text for latin-1 PDF encoding."""
    return str(text).encode("latin-1", errors="replace").decode("latin-1")


class ReportPDF(FPDF):
    def __init__(self, title="Northeast Beast's Control Tower"):
        super().__init__()
        self.report_title = title

    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 8, self.report_title, ln=True, align="L")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, f"Generated {pd.Timestamp.now().strftime('%b %d, %Y %I:%M %p')}", ln=True)
        self.set_text_color(0, 0, 0)
        self.ln(3)

    def section(self, title):
        self.set_font("Helvetica", "B", 12)
        self.set_fill_color(232, 244, 253)
        self.cell(0, 8, f"  {_safe(title)}", ln=True, fill=True)
        self.ln(2)

    def kv(self, key, value):
        self.set_font("Helvetica", "B", 9)
        self.cell(50, 5, _safe(key), ln=False)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, _safe(value), ln=True)

    def table(self, headers, rows, col_widths=None):
        if col_widths is None:
            available = self.w - 2 * self.l_margin
            col_widths = [available / len(headers)] * len(headers)

        # Header
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(74, 144, 217)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, _safe(h), border=1, fill=True, align="C")
        self.ln()

        # Rows
        self.set_font("Helvetica", "", 8)
        self.set_text_color(0, 0, 0)
        for row in rows:
            if self.get_y() > 270:
                self.add_page()
            for i, val in enumerate(row):
                self.cell(col_widths[i], 5, _safe(str(val)[:30]), border=1, align="C")
            self.ln()
        self.ln(3)

    def action_item(self, icon, text, color=(0, 0, 0)):
        self.set_text_color(*color)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, _safe(f"  {icon}  {text}"), ln=True)
        self.set_text_color(0, 0, 0)


def generate_ppm_report(df, ppm_name, period_col):
    """Generate a PDF report for a specific PPM."""
    ppm_df = df[df["PPM"] == ppm_name]
    if ppm_df.empty:
        return None

    periods = sorted(ppm_df[period_col].dropna().unique())
    curr_period = periods[-2] if len(periods) >= 2 else periods[-1] if periods else None
    prev_period = periods[-3] if len(periods) >= 3 else None

    pdf = ReportPDF(f"PPM Report: {ppm_name}")
    pdf.add_page()

    # KPIs
    if curr_period:
        curr_df = ppm_df[ppm_df[period_col] == curr_period]
        m = compute_metrics(curr_df)
        pdf.section("Key Metrics - Last Complete Period")
        pdf.kv("Referrals", f"{m['referrals']:,}")
        pdf.kv("Unique Providers", f"{m['unique_providers']:,}")
        pdf.kv("% Intake Started", f"{m['pct_intake']:.1%}")
        pdf.kv("% Visit Booked", f"{m['pct_booked']:.1%}")
        pdf.kv("% Visit Completed", f"{m['pct_completed']:.1%}")
        pdf.ln(3)

    # Account portfolio
    acct_table = compute_entity_table(ppm_df, "PARTNER_ASSIGNMENT", period_col)
    if not acct_table.empty:
        pdf.section("Account Portfolio")
        headers = ["Account", "Referrals", "% Booked", "Days Silent", "Status"]
        rows = []
        for _, r in acct_table.head(15).iterrows():
            rows.append([
                r["PARTNER_ASSIGNMENT"][:25],
                int(r["referrals"]),
                f"{r['pct_booked']:.1%}",
                f"{int(r['days_since_last'])}d" if pd.notna(r.get("days_since_last")) else "--",
                r.get("category", ""),
            ])
        pdf.table(headers, rows, col_widths=[55, 25, 25, 25, 30])

    # Action items
    if len(periods) >= 2:
        curr_df = ppm_df[ppm_df[period_col] == periods[-1]]
        prev_df = ppm_df[ppm_df[period_col] == periods[-2]]
        all_prior = ppm_df[ppm_df[period_col] < periods[-1]]

        curr_provs = set(curr_df["provider_id"].dropna())
        prev_provs = set(prev_df["provider_id"].dropna())
        all_prior_provs = set(all_prior["provider_id"].dropna())

        # New providers
        first_ever = curr_provs - all_prior_provs
        if first_ever:
            fp = curr_df[curr_df["provider_id"].isin(first_ever)]
            top_new = fp.groupby("REFERRING_PHYSICIAN").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Say Thank You to New Providers")
            for _, r in top_new.iterrows():
                pdf.action_item("+", f"{r['REFERRING_PHYSICIAN']} — {int(r['refs'])} referrals, first time", (40, 140, 70))

        # Dropped providers
        dropped = prev_provs - curr_provs
        if dropped:
            dp = prev_df[prev_df["provider_id"].isin(dropped)]
            top_dropped = dp.groupby("REFERRING_PHYSICIAN").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Re-engage Providers Who Stopped")
            for _, r in top_dropped.iterrows():
                pdf.action_item("!", f"{r['REFERRING_PHYSICIAN']} — {int(r['refs'])} referrals last period, zero now", (200, 50, 50))

    # Top clinics
    clinic_table = compute_entity_table(ppm_df, "REFERRING_CLINIC", period_col, include_account=True)
    if not clinic_table.empty:
        pdf.section("Top Clinics")
        headers = ["Clinic", "Account", "Referrals", "% Booked", "Status"]
        rows = []
        for _, r in clinic_table.head(15).iterrows():
            rows.append([
                r["REFERRING_CLINIC"][:25],
                r["PARTNER_ASSIGNMENT"][:20],
                int(r["referrals"]),
                f"{r['pct_booked']:.1%}",
                r.get("category", ""),
            ])
        pdf.table(headers, rows, col_widths=[50, 40, 22, 22, 26])

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def generate_account_report(df, account_names, period_col):
    """Generate a PDF report for one or more accounts."""
    filtered = df[df["PARTNER_ASSIGNMENT"].isin(account_names)]
    if filtered.empty:
        return None

    title = account_names[0] if len(account_names) == 1 else f"{len(account_names)} Accounts"
    pdf = ReportPDF(f"Account Report: {title}")
    pdf.add_page()

    periods = sorted(filtered[period_col].dropna().unique())
    curr_period = periods[-2] if len(periods) >= 2 else periods[-1] if periods else None

    if curr_period:
        curr_df = filtered[filtered[period_col] == curr_period]
        m = compute_metrics(curr_df)
        pdf.section("Key Metrics - Last Complete Period")
        pdf.kv("Referrals", f"{m['referrals']:,}")
        pdf.kv("Unique Providers", f"{m['unique_providers']:,}")
        pdf.kv("% Intake Started", f"{m['pct_intake']:.1%}")
        pdf.kv("% Visit Booked", f"{m['pct_booked']:.1%}")
        pdf.kv("% Visit Completed", f"{m['pct_completed']:.1%}")
        pdf.ln(3)

    # Action plan
    if len(periods) >= 2:
        curr_df = filtered[filtered[period_col] == periods[-1]]
        prev_df = filtered[filtered[period_col] == periods[-2]]
        all_prior = filtered[filtered[period_col] < periods[-1]]

        curr_provs = set(curr_df["provider_id"].dropna())
        prev_provs = set(prev_df["provider_id"].dropna())
        all_prior_provs = set(all_prior["provider_id"].dropna())
        curr_clinics = set(curr_df["REFERRING_CLINIC"].dropna())
        prev_clinics = set(prev_df["REFERRING_CLINIC"].dropna())
        all_prior_clinics = set(all_prior["REFERRING_CLINIC"].dropna())

        # New providers (first time ever)
        first_ever = curr_provs - all_prior_provs
        if first_ever:
            fp = curr_df[curr_df["provider_id"].isin(first_ever)]
            top_new = fp.groupby("REFERRING_PHYSICIAN").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Say Thank You to New Providers")
            for _, r in top_new.iterrows():
                pdf.action_item("+", _safe(f"{r['REFERRING_PHYSICIAN']} - {int(r['refs'])} referrals, first time ever"), (40, 140, 70))

        # New clinics (first time ever)
        first_clinics = curr_clinics - all_prior_clinics
        if first_clinics:
            fc = curr_df[curr_df["REFERRING_CLINIC"].isin(first_clinics)]
            top_new_c = fc.groupby("REFERRING_CLINIC").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Welcome New Clinics")
            for _, r in top_new_c.iterrows():
                pdf.action_item("+", _safe(f"{r['REFERRING_CLINIC']} - {int(r['refs'])} referrals, first time ever"), (40, 140, 70))

        # Dropped providers
        dropped = prev_provs - curr_provs
        if dropped:
            dp = prev_df[prev_df["provider_id"].isin(dropped)]
            top_dropped = dp.groupby("REFERRING_PHYSICIAN").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Re-engage Providers Who Stopped")
            for _, r in top_dropped.iterrows():
                pdf.action_item("!", _safe(f"{r['REFERRING_PHYSICIAN']} - {int(r['refs'])} referrals last period, zero now"), (200, 50, 50))

        # Dropped clinics
        dropped_c = prev_clinics - curr_clinics
        if dropped_c:
            dc = prev_df[prev_df["REFERRING_CLINIC"].isin(dropped_c)]
            top_dropped_c = dc.groupby("REFERRING_CLINIC").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Follow Up With Clinics That Went Silent")
            for _, r in top_dropped_c.iterrows():
                pdf.action_item("!", _safe(f"{r['REFERRING_CLINIC']} - {int(r['refs'])} referrals last period, zero now"), (200, 50, 50))

        # Low-converting clinics
        clinic_conv = curr_df.groupby("REFERRING_CLINIC").agg(
            refs=("REFERRAL_ID", "count"), intake=("intake_started", "sum"),
        ).reset_index()
        clinic_conv["pct"] = clinic_conv["intake"] / clinic_conv["refs"]
        qualified = clinic_conv[clinic_conv["refs"] >= 5]
        if len(qualified) >= 2:
            median_intake = qualified["pct"].median()
            low = qualified[qualified["pct"] <= median_intake].sort_values("pct").head(3)
            if not low.empty:
                pdf.section("Action: Investigate Low Intake Start Clinics")
                for _, r in low.iterrows():
                    pdf.action_item("?", _safe(f"{r['REFERRING_CLINIC']} - {r['pct']:.0%} intake started, {int(r['refs'])} referrals"), (200, 130, 50))

    # Top clinics
    clinic_table = compute_entity_table(filtered, "REFERRING_CLINIC", period_col, include_account=len(account_names) > 1)
    if not clinic_table.empty:
        pdf.section("Top Clinics")
        if len(account_names) > 1:
            headers = ["Clinic", "Account", "Referrals", "% Booked", "Days Silent", "Status"]
            rows = []
            for _, r in clinic_table.head(20).iterrows():
                rows.append([
                    r["REFERRING_CLINIC"][:22], r["PARTNER_ASSIGNMENT"][:18],
                    int(r["referrals"]), f"{r['pct_booked']:.1%}",
                    f"{int(r['days_since_last'])}d" if pd.notna(r.get("days_since_last")) else "--",
                    r.get("category", ""),
                ])
            pdf.table(headers, rows, col_widths=[40, 35, 20, 20, 22, 23])
        else:
            headers = ["Clinic", "Referrals", "% Booked", "Days Silent", "Status"]
            rows = []
            for _, r in clinic_table.head(20).iterrows():
                rows.append([
                    r["REFERRING_CLINIC"][:28], int(r["referrals"]),
                    f"{r['pct_booked']:.1%}",
                    f"{int(r['days_since_last'])}d" if pd.notna(r.get("days_since_last")) else "--",
                    r.get("category", ""),
                ])
            pdf.table(headers, rows, col_widths=[55, 25, 25, 25, 30])

    # Top providers
    prov_table = compute_entity_table(filtered, "REFERRING_PHYSICIAN", period_col)
    if not prov_table.empty:
        pdf.section("Top Providers")
        headers = ["Provider", "Referrals", "% Booked", "Days Silent", "Status"]
        rows = []
        for _, r in prov_table.head(20).iterrows():
            rows.append([
                str(r["REFERRING_PHYSICIAN"])[:28], int(r["referrals"]),
                f"{r['pct_booked']:.1%}",
                f"{int(r['days_since_last'])}d" if pd.notna(r.get("days_since_last")) else "--",
                r.get("category", ""),
            ])
        pdf.table(headers, rows, col_widths=[55, 25, 25, 25, 30])

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def generate_visit_prep_report(df, clinic_name, nearby_df, period_col):
    """Generate a PDF briefing for a clinic visit."""
    clinic_df = df[df["REFERRING_CLINIC"] == clinic_name]
    if clinic_df.empty:
        return None

    m = compute_metrics(clinic_df)
    accounts = ", ".join(clinic_df["PARTNER_ASSIGNMENT"].unique()[:3])
    zip_code = clinic_df["REFERRING_CLINIC_ZIP"].mode().iloc[0] if not clinic_df["REFERRING_CLINIC_ZIP"].mode().empty else "N/A"

    pdf = ReportPDF(f"Visit Prep: {clinic_name}")
    pdf.add_page()

    # Clinic overview
    pdf.section("Clinic Overview")
    pdf.kv("Clinic", clinic_name)
    pdf.kv("Account", accounts)
    pdf.kv("Zip Code", zip_code)
    pdf.kv("Total Referrals", f"{m['referrals']:,}")
    pdf.kv("Unique Providers", f"{m['unique_providers']:,}")
    pdf.kv("% Intake Started", f"{m['pct_intake']:.1%}")
    pdf.kv("% Visit Booked", f"{m['pct_booked']:.1%}")
    pdf.kv("% Visit Completed", f"{m['pct_completed']:.1%}")

    last_ref = clinic_df["REFERRAL_DATE"].max()
    if pd.notna(last_ref):
        days_since = (pd.Timestamp.now().normalize() - last_ref).days
        pdf.kv("Last Referral", f"{last_ref.strftime('%Y-%m-%d')} ({days_since}d ago)")
    pdf.ln(3)

    # Top providers
    prov_agg = clinic_df.groupby("REFERRING_PHYSICIAN").agg(
        referrals=("REFERRAL_ID", "count"),
        visit_booked=("visit_booked", "sum"),
        last_ref=("REFERRAL_DATE", "max"),
    ).reset_index()
    prov_agg["pct_booked"] = (prov_agg["visit_booked"] / prov_agg["referrals"]).fillna(0)
    prov_agg = prov_agg.sort_values("referrals", ascending=False).head(10)

    if not prov_agg.empty:
        pdf.section("Top Providers at This Clinic")
        headers = ["Provider", "Referrals", "% Booked", "Last Referral"]
        rows = []
        for _, r in prov_agg.iterrows():
            rows.append([
                str(r["REFERRING_PHYSICIAN"])[:25],
                int(r["referrals"]),
                f"{r['pct_booked']:.1%}",
                r["last_ref"].strftime("%Y-%m-%d") if pd.notna(r["last_ref"]) else "--",
            ])
        pdf.table(headers, rows, col_widths=[50, 25, 25, 35])

    # Nearby clinics
    if nearby_df is not None and not nearby_df.empty:
        pdf.section("Nearby Clinics")
        headers = ["Clinic", "Account", "Distance", "Referrals", "% Booked"]
        rows = []
        for _, r in nearby_df.head(15).iterrows():
            rows.append([
                r["REFERRING_CLINIC"][:25],
                r["PARTNER_ASSIGNMENT"][:20],
                f"{r['distance_mi']:.1f} mi",
                int(r["referrals"]),
                f"{r['pct_booked']:.1%}",
            ])
        pdf.table(headers, rows, col_widths=[50, 40, 20, 22, 22])

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
