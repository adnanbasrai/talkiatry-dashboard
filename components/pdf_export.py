import io
import os
import pandas as pd
from fpdf import FPDF
from data.transforms import compute_metrics, compute_entity_table, count_unique_providers

_ASSETS_DIR  = os.path.join(os.path.dirname(__file__), '..', 'assets')
_LOGO_PATH   = os.path.join(_ASSETS_DIR, 'logo.png')
_BRAND_YELLOW = (245, 185, 45)

# ── Brand palette (matches the colourful-lines brand element) ─────────────────
_BRAND_CURVES = [
    (222, 134,  96),   # terracotta / orange
    ( 52,  89, 115),   # dark teal
    (145, 190, 175),   # sage green
    (245, 185,  45),   # brand yellow
    (130, 190, 225),   # sky blue
    (175,  95, 110),   # mauve / pink
]

# ── Decoration PNG (generated once, cached in-process) ────────────────────────
_deco_cache = None  # type: io.BytesIO


def _bezier_pts(p0, p1, p2, p3, n=200):
    pts = []
    for i in range(n + 1):
        t = i / n; mt = 1 - t
        x = mt**3*p0[0] + 3*mt**2*t*p1[0] + 3*mt*t**2*p2[0] + t**3*p3[0]
        y = mt**3*p0[1] + 3*mt**2*t*p1[1] + 3*mt*t**2*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts


def _make_decoration_png() -> io.BytesIO:
    """Render the Talkiatry curved-lines brand element as a transparent PNG."""
    global _deco_cache
    if _deco_cache is not None:
        _deco_cache.seek(0)
        return _deco_cache

    from PIL import Image, ImageDraw

    # Draw at 2× then downsample for smooth antialiasing
    DW, DH = 600, 540
    img  = Image.new("RGBA", (DW, DH), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    LW = 20   # line width at 2×

    # Control points as fractions of (DW, DH).
    # Three long curves sweep in from the top edge, arc right, exit at bottom.
    # Three short curves begin from the right edge mid-page and exit at bottom.
    curve_defs = [
        (_BRAND_CURVES[0], [(0.22, 0), (1.22, 0.02), (1.22, 0.58), (0.60, 1.02)]),  # terracotta – longest
        (_BRAND_CURVES[1], [(0.33, 0), (1.12, 0.02), (1.12, 0.58), (0.48, 1.02)]),  # dark teal
        (_BRAND_CURVES[2], [(0.45, 0), (1.00, 0.02), (1.00, 0.58), (0.36, 1.02)]),  # sage green
        (_BRAND_CURVES[3], [(1.02, 0.40), (1.12, 0.58), (0.90, 0.78), (0.52, 1.02)]),  # brand yellow
        (_BRAND_CURVES[4], [(1.02, 0.52), (1.10, 0.68), (0.90, 0.86), (0.63, 1.02)]),  # sky blue
        (_BRAND_CURVES[5], [(1.02, 0.63), (1.07, 0.74), (0.93, 0.88), (0.74, 1.02)]),  # mauve
    ]

    for color, ctrl in curve_defs:
        pts = _bezier_pts(
            (ctrl[0][0]*DW, ctrl[0][1]*DH),
            (ctrl[1][0]*DW, ctrl[1][1]*DH),
            (ctrl[2][0]*DW, ctrl[2][1]*DH),
            (ctrl[3][0]*DW, ctrl[3][1]*DH),
        )
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i+1]], fill=(*color, 210), width=LW)

    img = img.resize((300, 270), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    _deco_cache = buf
    buf.seek(0)
    return buf

STATUS_COLORS = {
    "Visit Completed": (212, 237, 218),
    "Visit Booked": (204, 229, 255),
    "Intake Completed": (212, 237, 218),
    "Intake Done": (255, 243, 205),
    "Intake In Progress": (255, 243, 205),
    "Outreach In Progress": (255, 243, 205),
    "Intake Started": (226, 227, 229),
    "Rejected": (248, 215, 218),
    "Non-Responsive": (248, 215, 218),
    "Not Started": (252, 228, 236),
}


def _get_status_color(status):
    for key, color in STATUS_COLORS.items():
        if key in str(status):
            return color
    return None


def _safe(text):
    return str(text).encode("latin-1", errors="replace").decode("latin-1")


def _date_range_str(df):
    """Return a formatted date range string from a DataFrame."""
    if "REFERRAL_DATE" not in df.columns or df.empty:
        return ""
    d_min = df["REFERRAL_DATE"].min()
    d_max = df["REFERRAL_DATE"].max()
    if pd.notna(d_min) and pd.notna(d_max):
        return f"Data range: {d_min.strftime('%b %d, %Y')} - {d_max.strftime('%b %d, %Y')}"
    return ""


def _derive_status(r) -> str:
    """Derive a human-readable referral status string from a DataFrame row."""
    if r.get("visit_completed") == 1:
        return "Visit Completed"
    if r.get("visit_booked") == 1:
        return "Visit Booked"
    action = r.get("INTAKE_ACTION_STATUS", "")
    termination = r.get("TERMINATION_REASON", "")
    if action == "Rejected":
        if pd.notna(termination) and termination:
            tr = str(termination)
            if "OON" in tr or "OutOfNetwork" in tr or "InsurancePlan" in tr or "Payor" in tr:
                return "Rejected - OON"
            if "Minor" in tr:
                return "Rejected - Minor"
        return "Rejected"
    if r.get("IS_INTAKE_COMPLETED") == 1 and action == "NonResponsive":
        return "Intake Done - No Response"
    if r.get("IS_INTAKE_COMPLETED") == 1:
        return "Intake Completed"
    if action == "NonResponsive":
        return "Non-Responsive"
    if action == "New":
        return "Intake In Progress"
    if action in ("Called", "CalledSecondTime", "CalledThirdTime"):
        return "Outreach In Progress"
    if r.get("intake_started") == 1:
        return "Intake Started"
    return "Not Started"


class ReportPDF(FPDF):
    def __init__(self, title="Mindshare Control Tower"):
        super().__init__()
        self.report_title = title
        self.set_margins(left=10, top=36, right=10)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        # ── "Talkiatry" wordmark in brand yellow ──────────────────────────────
        self.set_xy(10, 8)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*_BRAND_YELLOW)
        self.cell(55, 10, "Talkiatry", ln=False)

        # ── Generated timestamp at right ──────────────────────────────────────
        self.set_font("Helvetica", "", 7)
        self.set_text_color(170, 170, 170)
        self.set_xy(80, 10)
        self.cell(0, 6, f"Generated {pd.Timestamp.now().strftime('%b %d, %Y  %I:%M %p')}", align="R")

        # ── Report title on second row ────────────────────────────────────────
        self.set_xy(10, 20)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(30, 30, 30)
        self.cell(0, 7, _safe(self.report_title), ln=True)

        # ── Thin rule ─────────────────────────────────────────────────────────
        self.set_draw_color(210, 210, 210)
        self.set_line_width(0.3)
        self.line(10, 29, self.w - 10, 29)
        self.set_text_color(0, 0, 0)
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.2)
        self.ln(4)

    def footer(self):
        # ── Page number ───────────────────────────────────────────────────────
        self.set_y(-13)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(170, 170, 170)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)

    def section(self, title):
        self.set_font("Helvetica", "B", 12)
        self.set_fill_color(232, 244, 253)
        self.cell(0, 8, f"  {_safe(title)}", ln=True, fill=True)
        self.ln(2)

    def date_note(self, text):
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 4, _safe(text), ln=True)
        self.set_text_color(0, 0, 0)

    def kv(self, key, value):
        self.set_font("Helvetica", "B", 9)
        self.cell(50, 5, _safe(key), ln=False)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, _safe(value), ln=True)

    def table(self, headers, rows, col_widths=None, row_colors=None):
        if col_widths is None:
            available = self.w - 2 * self.l_margin
            col_widths = [available / len(headers)] * len(headers)
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(74, 144, 217)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 6, _safe(h), border=1, fill=True, align="C")
        self.ln()
        self.set_font("Helvetica", "", 8)
        self.set_text_color(0, 0, 0)
        for ri, row in enumerate(rows):
            if self.get_y() > self.h - 28:
                self.add_page()
            has_color = row_colors and ri < len(row_colors) and row_colors[ri]
            if has_color:
                self.set_fill_color(*row_colors[ri])
            for i, val in enumerate(row):
                val_str = str(val)
                max_chars = max(8, int(col_widths[i] / 2.1))  # ~2.1mm per char at 8pt
                if len(val_str) > max_chars:
                    val_str = val_str[:max_chars - 3] + "..."
                self.cell(col_widths[i], 5, _safe(val_str), border=1, fill=has_color, align="C")
            self.ln()
        self.ln(3)

    def action_item(self, icon, text, color=(0, 0, 0)):
        self.set_text_color(*color)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, _safe(f"  {icon}  {text}"), ln=True)
        self.set_text_color(0, 0, 0)

    def priority_label(self, label, color):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*color)
        self.cell(0, 6, _safe(label), ln=True)
        self.set_text_color(0, 0, 0)

    def priority_clinic(self, clinic, account, refs, paced, prev, reasons, sentiment):
        bg = (212, 237, 218) if sentiment == "green" else (248, 215, 218)
        text_color = (21, 87, 36) if sentiment == "green" else (114, 28, 36)
        self.set_fill_color(*bg)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*text_color)
        line = f"  {clinic} ({account}) - {refs} refs (paced {paced}), was {prev}"
        self.cell(0, 5, _safe(line), ln=True, fill=True)
        self.set_font("Helvetica", "", 7)
        reason_text = " | ".join(reasons)
        self.cell(0, 4, _safe(f"    {reason_text}"), ln=True, fill=True)
        self.set_text_color(0, 0, 0)


def generate_ppm_report(df, ppm_name, period_col):
    """Generate a PDF report for a specific PPM."""
    ppm_df = df[df["PPM"] == ppm_name]
    if ppm_df.empty:
        return None

    is_weekly = period_col == "week_of"
    date_range = _date_range_str(ppm_df)

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
        pdf.date_note(date_range)
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
        pdf.date_note(date_range)
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
                pdf.action_item("+", _safe(f"{r['REFERRING_PHYSICIAN']}: {int(r['refs'])} referrals, first time"), (40, 140, 70))

        # Dropped providers
        dropped = prev_provs - curr_provs
        if dropped:
            dp = prev_df[prev_df["provider_id"].isin(dropped)]
            top_dropped = dp.groupby("REFERRING_PHYSICIAN").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Re-engage Providers Who Stopped")
            for _, r in top_dropped.iterrows():
                pdf.action_item("!", _safe(f"{r['REFERRING_PHYSICIAN']}: {int(r['refs'])} referrals last period, zero now"), (200, 50, 50))

    # Priority clinics with P1/P2/P3 and full signal reasons
    if len(periods) >= 2:
        import numpy as np
        from data.transforms import _count_weekdays

        curr_ap = ppm_df[ppm_df[period_col] == periods[-1]]
        prev_ap = ppm_df[ppm_df[period_col] == periods[-2]]
        all_prior_ap = ppm_df[ppm_df[period_col] < periods[-1]]
        today_ap = pd.Timestamp.now().normalize()

        if not is_weekly:
            p_start = pd.Period(periods[-1], freq="M").start_time
            p_end = pd.Period(periods[-1], freq="M").end_time + pd.Timedelta(days=1)
        else:
            p_start = pd.Timestamp(periods[-1])
            p_end = p_start + pd.Timedelta(days=5)
        wd_elapsed = max(_count_weekdays(p_start, today_ap), 1)
        wd_total = max(_count_weekdays(p_start, p_end), 1)
        pace_factor = wd_total / wd_elapsed

        prev_clinic_refs = prev_ap.groupby("REFERRING_CLINIC")["REFERRAL_ID"].count()
        curr_clinic_refs = curr_ap.groupby("REFERRING_CLINIC")["REFERRAL_ID"].count()
        prior_clinics_set = set(all_prior_ap["REFERRING_CLINIC"].dropna())
        prior_provs_set = set(all_prior_ap["provider_id"].dropna())
        acct_map = ppm_df.groupby("REFERRING_CLINIC")["PARTNER_ASSIGNMENT"].first().to_dict()

        # Intake rates
        curr_intake = curr_ap.groupby("REFERRING_CLINIC").agg(refs=("REFERRAL_ID", "count"), intake=("intake_started", "sum")).reset_index()
        curr_intake["pct"] = curr_intake["intake"] / curr_intake["refs"]
        curr_intake_map = dict(zip(curr_intake["REFERRING_CLINIC"], curr_intake["pct"]))
        prev_intake = prev_ap.groupby("REFERRING_CLINIC").agg(refs=("REFERRAL_ID", "count"), intake=("intake_started", "sum")).reset_index()
        prev_intake["pct"] = prev_intake["intake"] / prev_intake["refs"]
        prev_intake_map = dict(zip(prev_intake["REFERRING_CLINIC"], prev_intake["pct"]))

        # New providers per clinic
        new_provs_map = {}
        for clinic in curr_ap["REFERRING_CLINIC"].dropna().unique():
            c_provs = set(curr_ap[curr_ap["REFERRING_CLINIC"] == clinic]["provider_id"].dropna())
            new_provs_map[clinic] = len(c_provs - prior_provs_set)

        scored = []
        for clinic in set(list(curr_clinic_refs.index) + list(prev_clinic_refs.index)):
            curr_r = curr_clinic_refs.get(clinic, 0)
            prev_r = prev_clinic_refs.get(clinic, 0)
            paced = int(curr_r * pace_factor)
            reasons = []
            score = 0
            sentiment = "neutral"
            ci = curr_intake_map.get(clinic, 0)
            pi = prev_intake_map.get(clinic, 0)
            new_p = new_provs_map.get(clinic, 0)

            if clinic not in prior_clinics_set and curr_r >= 3:
                reasons.append(f"New clinic, {curr_r} refs so far")
                score += 3; sentiment = "green"
            if prev_r >= 5 and paced > prev_r * 1.5:
                reasons.append(f"Volume surging {int((paced/prev_r-1)*100):+d}% vs prior")
                score += 3; sentiment = "green"
            if new_p >= 3:
                reasons.append(f"{new_p} new providers activating")
                score += 2; sentiment = "green"
            if ci >= 0.55 and curr_r >= 5:
                reasons.append(f"High intake conversion ({ci:.0%})")
                score += 2
                if sentiment == "neutral": sentiment = "green"
            if prev_r >= 5 and curr_r == 0:
                reasons.append(f"Silent: had {prev_r} refs last period, zero now")
                score += 4; sentiment = "red"
            if prev_r >= 5 and paced < prev_r * 0.5 and curr_r > 0:
                reasons.append(f"Volume dropped {int((paced/prev_r-1)*100):+d}% vs prior")
                score += 3; sentiment = "red"
            if (ci - pi) < -0.15 and curr_r >= 5:
                reasons.append(f"Intake rate dropped {(ci-pi)*100:+.0f}pp")
                score += 3; sentiment = "red"
            if ci < 0.35 and pi < 0.35 and curr_r >= 5 and prev_r >= 5:
                reasons.append(f"Persistently low intake: {ci:.0%} this period, {pi:.0%} last")
                score += 2; sentiment = "red"
            if paced > prev_r * 2 and prev_r >= 3 and sentiment != "red":
                reasons.append("Volume 2x+ vs prior")
                score += 2; sentiment = "green"

            if reasons:
                scored.append({
                    "clinic": clinic, "account": acct_map.get(clinic, ""),
                    "curr": curr_r, "paced": paced, "prev": prev_r,
                    "reasons": reasons, "score": score, "sentiment": sentiment,
                })

        if scored:
            scored.sort(key=lambda x: x["score"], reverse=True)
            p1 = [s for s in scored if s["score"] >= 4][:3]
            remaining = [s for s in scored if s not in p1]
            p2 = [s for s in remaining if s["score"] >= 2][:3]
            remaining2 = [s for s in remaining if s not in p2]
            p3 = remaining2[:3]

            pdf.section("Clinic Visit Plan")
            pdf.date_note(date_range)

            for label, items, color in [
                ("Priority 1 - Visit This Week", p1, (200, 50, 50)),
                ("Priority 2 - Visit This Month", p2, (180, 130, 30)),
                ("Priority 3 - Monitor / Schedule", p3, (100, 100, 100)),
            ]:
                if not items:
                    continue
                pdf.priority_label(label, color)
                for item in items:
                    pdf.priority_clinic(
                        item["clinic"][:30], item["account"][:20],
                        item["curr"], item["paced"], item["prev"],
                        item["reasons"], item["sentiment"],
                    )
                pdf.ln(2)

    # Top clinics
    clinic_table = compute_entity_table(ppm_df, "REFERRING_CLINIC", period_col, include_account=True)
    if not clinic_table.empty:
        pdf.section("Top Clinics")
        pdf.date_note(date_range)
        headers = ["Clinic", "Account", "Referrals", "% Booked", "Status"]
        rows = []
        for _, r in clinic_table.head(15).iterrows():
            rows.append([
                r["REFERRING_CLINIC"][:25], r["PARTNER_ASSIGNMENT"][:20],
                int(r["referrals"]), f"{r['pct_booked']:.1%}", r.get("category", ""),
            ])
        pdf.table(headers, rows, col_widths=[45, 40, 22, 22, 31])

    # Top providers
    prov_table = compute_entity_table(ppm_df, "REFERRING_PHYSICIAN", period_col)
    if not prov_table.empty:
        pdf.section("Top Providers")
        pdf.date_note(date_range)
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


def generate_account_report(df, account_names, period_col):
    """Generate a PDF report for one or more accounts."""
    filtered = df[df["PARTNER_ASSIGNMENT"].isin(account_names)]
    if filtered.empty:
        return None

    title = account_names[0] if len(account_names) == 1 else f"{len(account_names)} Accounts"
    pdf = ReportPDF(f"Account Report: {title}")
    pdf.add_page()
    date_range = _date_range_str(filtered)

    periods = sorted(filtered[period_col].dropna().unique())
    curr_period = periods[-2] if len(periods) >= 2 else periods[-1] if periods else None

    if curr_period:
        curr_df = filtered[filtered[period_col] == curr_period]
        m = compute_metrics(curr_df)
        pdf.section("Key Metrics - Last Complete Period")
        pdf.date_note(date_range)
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

        first_ever = curr_provs - all_prior_provs
        if first_ever:
            fp = curr_df[curr_df["provider_id"].isin(first_ever)]
            top_new = fp.groupby("REFERRING_PHYSICIAN").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Say Thank You to New Providers")
            for _, r in top_new.iterrows():
                pdf.action_item("+", _safe(f"{r['REFERRING_PHYSICIAN']}: {int(r['refs'])} referrals, first time ever"), (40, 140, 70))

        first_clinics_new = curr_clinics - all_prior_clinics
        if first_clinics_new:
            fc = curr_df[curr_df["REFERRING_CLINIC"].isin(first_clinics_new)]
            top_new_c = fc.groupby("REFERRING_CLINIC").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Welcome New Clinics")
            for _, r in top_new_c.iterrows():
                pdf.action_item("+", _safe(f"{r['REFERRING_CLINIC']}: {int(r['refs'])} referrals, first time ever"), (40, 140, 70))

        dropped_p = prev_provs - curr_provs
        if dropped_p:
            dp = prev_df[prev_df["provider_id"].isin(dropped_p)]
            top_dropped = dp.groupby("REFERRING_PHYSICIAN").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Re-engage Providers Who Stopped")
            for _, r in top_dropped.iterrows():
                pdf.action_item("!", _safe(f"{r['REFERRING_PHYSICIAN']}: {int(r['refs'])} referrals last period, zero now"), (200, 50, 50))

        dropped_c = prev_clinics - curr_clinics
        if dropped_c:
            dc = prev_df[prev_df["REFERRING_CLINIC"].isin(dropped_c)]
            top_dropped_c = dc.groupby("REFERRING_CLINIC").agg(refs=("REFERRAL_ID", "count")).reset_index().sort_values("refs", ascending=False).head(3)
            pdf.section("Action: Follow Up With Clinics That Went Silent")
            for _, r in top_dropped_c.iterrows():
                pdf.action_item("!", _safe(f"{r['REFERRING_CLINIC']}: {int(r['refs'])} referrals last period, zero now"), (200, 50, 50))

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
                    pdf.action_item("?", _safe(f"{r['REFERRING_CLINIC']}: {r['pct']:.0%} intake started, {int(r['refs'])} referrals"), (200, 130, 50))

    # Top clinics
    clinic_table = compute_entity_table(filtered, "REFERRING_CLINIC", period_col, include_account=len(account_names) > 1)
    if not clinic_table.empty:
        pdf.section("Top Clinics")
        pdf.date_note(date_range)
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
        pdf.date_note(date_range)
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


def generate_visit_prep_report(df, clinic_name, nearby_df, period_col, days_window=14, window_label=None):
    """Generate a PDF briefing for a clinic visit."""
    clinic_df = df[df["REFERRING_CLINIC"] == clinic_name]
    if clinic_df.empty:
        return None

    m = compute_metrics(clinic_df)
    accounts = ", ".join(clinic_df["PARTNER_ASSIGNMENT"].unique()[:3])
    zip_code = clinic_df["REFERRING_CLINIC_ZIP"].mode().iloc[0] if not clinic_df["REFERRING_CLINIC_ZIP"].mode().empty else "N/A"
    date_range = _date_range_str(clinic_df)

    pdf = ReportPDF(f"Visit Prep: {clinic_name}")
    pdf.add_page()

    pdf.section("Clinic Overview")
    pdf.date_note(date_range)
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

    # Top providers — join NPI via provider_id
    has_npi = "REFERRING_PROVIDER_NPI" in clinic_df.columns and "provider_id" in clinic_df.columns
    prov_agg = clinic_df.groupby("REFERRING_PHYSICIAN").agg(
        referrals=("REFERRAL_ID", "count"),
        visit_booked=("visit_booked", "sum"),
        last_ref=("REFERRAL_DATE", "max"),
    ).reset_index()
    if has_npi:
        npi_map = (
            clinic_df.dropna(subset=["REFERRING_PHYSICIAN", "REFERRING_PROVIDER_NPI"])
            .groupby("REFERRING_PHYSICIAN")["REFERRING_PROVIDER_NPI"]
            .first()
            .astype(str).str.replace(r"\.0$", "", regex=True)
            .replace({"nan": "", "None": ""})
        )
        prov_agg["npi"] = prov_agg["REFERRING_PHYSICIAN"].map(npi_map).fillna("")
    prov_agg["pct_booked"] = (prov_agg["visit_booked"] / prov_agg["referrals"]).fillna(0)
    prov_agg = prov_agg.sort_values("referrals", ascending=False).head(10)

    if not prov_agg.empty:
        pdf.section("Top Providers at This Clinic")
        pdf.date_note(date_range)
        if has_npi:
            headers = ["Provider", "NPI", "Referrals", "% Booked", "Last Referral"]
            col_widths = [45, 28, 20, 20, 30]
            rows = []
            for _, r in prov_agg.iterrows():
                rows.append([
                    str(r["REFERRING_PHYSICIAN"])[:22],
                    str(r.get("npi", ""))[:15],
                    int(r["referrals"]),
                    f"{r['pct_booked']:.1%}",
                    r["last_ref"].strftime("%Y-%m-%d") if pd.notna(r["last_ref"]) else "--",
                ])
        else:
            headers = ["Provider", "Referrals", "% Booked", "Last Referral"]
            col_widths = [50, 25, 25, 35]
            rows = []
            for _, r in prov_agg.iterrows():
                rows.append([
                    str(r["REFERRING_PHYSICIAN"])[:25],
                    int(r["referrals"]),
                    f"{r['pct_booked']:.1%}",
                    r["last_ref"].strftime("%Y-%m-%d") if pd.notna(r["last_ref"]) else "--",
                ])
        pdf.table(headers, rows, col_widths=col_widths)

    # Referral Status Report (before nearby clinics)
    section_label = window_label or (f"Last {days_window} Days" if days_window else "All Time")
    pdf.section(f"Referral Status Report - {section_label}")
    today = pd.Timestamp.now().normalize()
    if days_window is not None:
        cutoff = today - pd.Timedelta(days=days_window)
        recent = clinic_df[clinic_df["REFERRAL_DATE"] >= cutoff].sort_values("REFERRAL_DATE", ascending=False)
    else:
        recent = clinic_df.sort_values("REFERRAL_DATE", ascending=False)
        cutoff = clinic_df["REFERRAL_DATE"].min() if not clinic_df.empty else today

    if recent.empty:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _safe(f"No referrals in the selected window ({section_label})."), ln=True)
        pdf.ln(3)
    else:
        pdf.date_note(f"Referrals from {cutoff.strftime('%b %d')} to {today.strftime('%b %d, %Y')}")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, _safe(f"{len(recent)} referrals"), ln=True)
        pdf.ln(2)

        has_dob = "PATIENT_DOB" in recent.columns
        headers = ["Date", "Physician", "Patient", "DOB" if has_dob else "Age", "Status"]
        col_widths = [22, 38, 38, 22, 40]

        rows = []
        row_colors = []
        for _, r in recent.iterrows():
            status = _derive_status(r)

            ref_date = r["REFERRAL_DATE"].strftime("%m/%d/%Y") if pd.notna(r["REFERRAL_DATE"]) else ""
            physician = str(r.get("REFERRING_PHYSICIAN", ""))[:25]
            patient = str(r.get("patient_name", ""))[:25] if pd.notna(r.get("patient_name")) else ""

            if has_dob and pd.notna(r.get("PATIENT_DOB")):
                dob = r["PATIENT_DOB"].strftime("%m/%d/%Y") if hasattr(r["PATIENT_DOB"], "strftime") else str(r["PATIENT_DOB"])[:10]
            elif "PATIENT_AGE" in recent.columns and pd.notna(r.get("PATIENT_AGE")):
                dob = str(int(r["PATIENT_AGE"]))
            else:
                dob = ""

            rows.append([ref_date, physician, patient, dob, status])
            row_colors.append(_get_status_color(status))

        pdf.table(headers, rows, col_widths=col_widths, row_colors=row_colors)

        from collections import Counter
        status_counts = Counter([row[4] for row in rows])
        summary = " | ".join(f"{count} {status}" for status, count in sorted(status_counts.items(), key=lambda x: -x[1]))
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 5, _safe(summary), ln=True)
        pdf.ln(3)

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def generate_clinic_status_report(df_full: pd.DataFrame, clinic_name: str):
    """All-time clinic referral status report for sharing with the clinic."""
    clinic_df = df_full[df_full["REFERRING_CLINIC"] == clinic_name]
    if clinic_df.empty:
        return None

    m = compute_metrics(clinic_df)
    accounts = ", ".join(str(a) for a in clinic_df["PARTNER_ASSIGNMENT"].unique()[:3])
    zip_code = clinic_df["REFERRING_CLINIC_ZIP"].mode().iloc[0] if not clinic_df["REFERRING_CLINIC_ZIP"].mode().empty else "N/A"
    date_range = _date_range_str(clinic_df)

    pdf = ReportPDF(f"Clinic Referral Status: {clinic_name}")
    pdf.add_page()

    pdf.section("Clinic Overview (All Time)")
    pdf.date_note(date_range)
    pdf.kv("Clinic", clinic_name)
    pdf.kv("Account", accounts)
    pdf.kv("Total Referrals", f"{m['referrals']:,}")
    pdf.kv("Unique Providers", f"{m['unique_providers']:,}")
    pdf.kv("% Intake Started", f"{m['pct_intake']:.1%}")
    last_ref = clinic_df["REFERRAL_DATE"].max()
    if pd.notna(last_ref):
        days_since = (pd.Timestamp.now().normalize() - last_ref).days
        pdf.kv("Last Referral", f"{last_ref.strftime('%Y-%m-%d')} ({days_since}d ago)")
    pdf.ln(3)

    # Top providers
    prov_agg = (
        clinic_df.groupby("REFERRING_PHYSICIAN")
        .agg(referrals=("REFERRAL_ID", "count"), visit_booked=("visit_booked", "sum"),
             last_ref=("REFERRAL_DATE", "max"))
        .reset_index()
    )
    prov_agg["pct_booked"] = (prov_agg["visit_booked"] / prov_agg["referrals"]).fillna(0)
    prov_agg = prov_agg.sort_values("referrals", ascending=False).head(10)
    if not prov_agg.empty:
        pdf.section("Top Providers at This Clinic")
        pdf.date_note(date_range)
        headers = ["Provider", "Referrals", "% Booked", "Last Referral"]
        rows = []
        for _, r in prov_agg.iterrows():
            rows.append([
                str(r["REFERRING_PHYSICIAN"])[:25], int(r["referrals"]),
                f"{r['pct_booked']:.1%}",
                r["last_ref"].strftime("%Y-%m-%d") if pd.notna(r["last_ref"]) else "--",
            ])
        pdf.table(headers, rows, col_widths=[50, 25, 25, 35])

    # Full referral list
    all_refs = clinic_df.sort_values("REFERRAL_DATE", ascending=False)
    pdf.section(f"Full Referral Status Report - {len(all_refs)} referrals, all time")
    pdf.date_note(date_range)
    has_dob = "PATIENT_DOB" in all_refs.columns
    headers = ["Date", "Physician", "Patient", "DOB" if has_dob else "Age", "Status"]
    col_widths = [22, 38, 38, 22, 40]
    rows, row_colors = [], []
    for _, r in all_refs.iterrows():
        status = _derive_status(r)
        ref_date = r["REFERRAL_DATE"].strftime("%m/%d/%Y") if pd.notna(r["REFERRAL_DATE"]) else ""
        physician = str(r.get("REFERRING_PHYSICIAN", ""))[:25]
        patient = str(r.get("patient_name", ""))[:25] if pd.notna(r.get("patient_name")) else ""
        if has_dob and pd.notna(r.get("PATIENT_DOB")):
            dob = r["PATIENT_DOB"].strftime("%m/%d/%Y") if hasattr(r["PATIENT_DOB"], "strftime") else str(r["PATIENT_DOB"])[:10]
        else:
            dob = ""
        rows.append([ref_date, physician, patient, dob, status])
        row_colors.append(_get_status_color(status))
    pdf.table(headers, rows, col_widths=col_widths, row_colors=row_colors)

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def generate_provider_status_report(df_full: pd.DataFrame, provider_name: str):
    """All-time provider referral status report for sharing with the provider."""
    prov_df = df_full[df_full["REFERRING_PHYSICIAN"] == provider_name]
    if prov_df.empty:
        return None

    m = compute_metrics(prov_df)
    clinics = ", ".join(str(c) for c in prov_df["REFERRING_CLINIC"].dropna().unique()[:4])
    date_range = _date_range_str(prov_df)

    pdf = ReportPDF(f"Provider Referral Status: {provider_name}")
    pdf.add_page()

    pdf.section("Provider Overview (All Time)")
    pdf.date_note(date_range)
    pdf.kv("Provider", provider_name)
    pdf.kv("Clinics", clinics or "N/A")
    pdf.kv("Total Referrals", f"{m['referrals']:,}")
    pdf.kv("Unique Clinics", str(prov_df["REFERRING_CLINIC"].nunique()))
    pdf.kv("% Intake Started", f"{m['pct_intake']:.1%}")
    last_ref = prov_df["REFERRAL_DATE"].max()
    if pd.notna(last_ref):
        days_since = (pd.Timestamp.now().normalize() - last_ref).days
        pdf.kv("Last Referral", f"{last_ref.strftime('%Y-%m-%d')} ({days_since}d ago)")
    pdf.ln(3)

    # Full referral list
    all_refs = prov_df.sort_values("REFERRAL_DATE", ascending=False)
    pdf.section(f"Full Referral Status Report - {len(all_refs)} referrals, all time")
    pdf.date_note(date_range)
    has_dob = "PATIENT_DOB" in all_refs.columns
    headers = ["Date", "Clinic", "Patient", "DOB" if has_dob else "Age", "Status"]
    col_widths = [22, 45, 35, 22, 36]
    rows, row_colors = [], []
    for _, r in all_refs.iterrows():
        status = _derive_status(r)
        ref_date = r["REFERRAL_DATE"].strftime("%m/%d/%Y") if pd.notna(r["REFERRAL_DATE"]) else ""
        clinic = str(r.get("REFERRING_CLINIC", ""))
        patient = str(r.get("patient_name", ""))[:25] if pd.notna(r.get("patient_name")) else ""
        if has_dob and pd.notna(r.get("PATIENT_DOB")):
            dob = r["PATIENT_DOB"].strftime("%m/%d/%Y") if hasattr(r["PATIENT_DOB"], "strftime") else str(r["PATIENT_DOB"])[:10]
        else:
            dob = ""
        rows.append([ref_date, clinic, patient, dob, status])
        row_colors.append(_get_status_color(status))
    pdf.table(headers, rows, col_widths=col_widths, row_colors=row_colors)

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
